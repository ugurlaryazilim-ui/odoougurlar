# -*- coding: utf-8 -*-
"""A5 düzeltme #1: hesap yazma yetkisi (Y1), OAuth yansıyan XSS (Y2), imzalı OAuth state (O1),
fix_youtube ön denetimi (D1), Evolution/Meta yanıt gövdesi maskesi (H3)."""
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from werkzeug.exceptions import Forbidden

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.social_media_ai_manager import tools
from odoo.addons.social_media_ai_manager.controllers import oauth_meta, tiktok_oauth, youtube_oauth

PAY = '<script>alert(1)</script>'


def _resp(payload, ok=True, text=''):
    m = MagicMock()
    m.json.return_value = payload
    m.ok = ok
    m.status_code = 200 if ok else 401
    m.text = text
    return m


class _Base(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login='a5s_user', groups='base.group_user')
        cls.admin = new_test_user(cls.env, login='a5s_admin', groups='base.group_user,base.group_system')
        cls.wa = cls.env['social.media.account'].create({
            'name': 'WA', 'platform': 'whatsapp', 'api_token': 'WAKEY1', 'phone_number': '905551112233',
            'whatsapp_api_url': 'https://evo.example', 'whatsapp_instance_name': 'inst'})
        cls.yt = cls.env['social.media.account'].create({'name': 'YT', 'platform': 'youtube'})
        ICP = cls.env['ir.config_parameter'].sudo()
        for k, v in (('youtube_client_id', 'cid'), ('youtube_client_secret', 'YTSEC1'),
                     ('tiktok_client_key', 'ck'), ('tiktok_client_secret', 'TTSEC1'),
                     ('meta_app_id', '111'), ('meta_app_secret', 'METASEC1')):
            ICP.set_param('social_media_ai.' + k, v)


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestAccountWriteAccess(_Base):
    """Y1: hesap kaydı (jetonun gideceği URL/platform) yalnız sistem yöneticisince değiştirilir."""

    def test_plain_user_cannot_write_create_unlink(self):
        acc = self.wa.with_user(self.user)
        self.assertEqual(acc.name, 'WA')   # okuma sürüyor (inbox/gönderi ekranları)
        for vals in ({'whatsapp_api_url': 'https://attacker.example'}, {'platform': 'whatsapp'}, {'name': 'x'}):
            with self.assertRaises(AccessError, msg=vals):
                acc.write(vals)
        with self.assertRaises(AccessError):
            self.env['social.media.account'].with_user(self.user).create({'name': 'X', 'platform': 'whatsapp'})
        with self.assertRaises(AccessError):
            acc.unlink()
        self.assertEqual(self.wa.whatsapp_api_url, 'https://evo.example')

    def test_admin_can_write(self):
        self.wa.with_user(self.admin).write({'whatsapp_instance_name': 'inst2'})
        self.assertEqual(self.wa.whatsapp_instance_name, 'inst2')

    def test_admin_buttons_reject_plain_user_before_any_call(self):
        acc = self.wa.with_user(self.user)
        with patch('requests.post') as post, patch('requests.get') as get, patch('requests.delete') as delete:
            for method in ('action_test_whatsapp', 'action_setup_webhook', 'action_logout_whatsapp',
                           'action_open_qr_wizard', 'action_subscribe_webhooks', 'action_login_facebook',
                           'action_login_youtube', 'action_login_tiktok', 'action_fix_youtube_errors'):
                with self.assertRaises(AccessError, msg=method):
                    getattr(acc, method)()
        self.assertFalse(post.called or get.called or delete.called, 'yetkisiz düğme dış servise gitti')


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestFixYoutubePrecheck(_Base):
    """D1: jeton/kanal yoksa ücretli AI çağrısından önce durur."""

    def test_missing_token_stops_before_ai(self):
        provider = type(self.env['social.media.ai.provider'])
        with patch.object(provider, 'generate_response', return_value='x') as gen, \
                patch('requests.post'), patch('requests.get'):
            conv = self.env['social.media.conversation'].create({
                'account_id': self.yt.id, 'social_user_id': 'u1', 'state': 'open'})
            self.env['social.media.message'].create({
                'conversation_id': conv.id, 'message_type': 'incoming', 'content': 'soru',
                'platform_message_id': 'c1'})
            self.env['social.media.message'].create({
                'conversation_id': conv.id, 'message_type': 'outgoing',
                'content': 'An error occurred with the Gemini service.'})
            with self.assertRaises(UserError):
                self.yt.with_user(self.admin).action_fix_youtube_errors()
        gen.assert_not_called()


class _OAuthBase(_Base):

    def setUp(self):
        super().setUp()
        # NEDEN: gerçek istekte login ve callback aynı oturumu paylaşır; nonce oturumda tutulur (N2)
        self.session = {}

    def _call(self, module, cls_name, meth, user, **kw):
        req = SimpleNamespace(env=self.env(user=user), session=self.session,
                              redirect=lambda url, **k: ('REDIRECT', url))
        ctrl = getattr(module, cls_name)()
        with patch.object(module, 'request', req):
            return getattr(getattr(module, cls_name), meth).__wrapped__(ctrl, **kw)

    def _state(self, provider, account_id, user=None):
        return tools.make_oauth_state(self.env(user=user or self.admin), provider, account_id, self.session)


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestOAuthReflectedXss(_OAuthBase):
    """Y2: ?error= ve sağlayıcı yanıtı kaçışlı döner; istisna metni kullanıcıya dönmez."""

    def test_error_param_escaped(self):
        for module, cls_name, meth in ((youtube_oauth, 'YouTubeOAuth', 'youtube_callback'),
                                       (tiktok_oauth, 'TikTokOAuth', 'tiktok_callback')):
            out = self._call(module, cls_name, meth, self.admin, error=PAY)
            self.assertNotIn('<script>', out, meth)
            self.assertIn('&lt;script&gt;', out, meth)

    def test_token_error_description_escaped(self):
        state = self._state('youtube', self.yt.id)
        with patch('requests.post', return_value=_resp({'error': 'x', 'error_description': PAY})):
            out = self._call(youtube_oauth, 'YouTubeOAuth', 'youtube_callback', self.admin, code='C', state=state)
        self.assertNotIn('<script>', out)

    def test_exception_text_not_returned(self):
        state = self._state('tiktok', self.yt.id)
        with patch('requests.post', side_effect=ValueError(PAY + ' TTSEC1')), \
                self.assertLogs('odoo.addons.social_media_ai_manager.controllers.tiktok_oauth', level='ERROR') as cm:
            out = self._call(tiktok_oauth, 'TikTokOAuth', 'tiktok_callback', self.admin, code='C', state=state)
        self.assertNotIn('<script>', out)
        self.assertIn('ValueError', out)
        self.assertNotIn('TTSEC1', '\n'.join(r.getMessage() for r in cm.records))

    def test_meta_error_response_escaped(self):
        state = self._state('meta', 0)
        with patch('requests.post', return_value=_resp({'error': {'message': PAY}})):
            out = self._call(oauth_meta, 'MetaOAuthController', 'facebook_callback', self.admin, code='C', state=state)
        self.assertNotIn('<script>', out)


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestOAuthState(_OAuthBase):
    """O1: state imzalı, kullanıcıya bağlı, süreli; uçlar yalnız sistem yöneticisine açık."""

    def _yt_callback(self, user, state):
        with patch('requests.post', return_value=_resp({'access_token': 'NEWYT', 'refresh_token': 'RT'})), \
                patch('requests.get', return_value=_resp({'items': [{'id': 'ch1', 'snippet': {'title': 't'}}]})):
            return self._call(youtube_oauth, 'YouTubeOAuth', 'youtube_callback', user, code='C', state=state)

    def test_valid_state_connects(self):
        out = self._yt_callback(self.admin, self._state('youtube', self.yt.id))
        self.assertEqual(out[0], 'REDIRECT')
        self.assertEqual((self.yt.api_token, self.yt.youtube_channel_id), ('NEWYT', 'ch1'))

    def test_forged_or_foreign_state_rejected(self):
        other_admin = new_test_user(self.env, login='a5s_admin2', groups='base.group_user,base.group_system')
        good = self._state('youtube', self.yt.id)
        payload, sig = good.rsplit('.', 1)
        bad_states = [
            str(self.yt.id),                                   # eski biçim: düz hesap id
            '%s.%s' % (payload, '0' * len(sig)),               # sahte imza
            good.replace('%d.' % self.yt.id, '%d.' % self.wa.id, 1),   # hesap değiştirilmiş
            self._state('tiktok', self.yt.id),                 # başka sağlayıcının state'i
            self._state('youtube', self.yt.id, user=other_admin),   # başka kullanıcının state'i
        ]
        for state in bad_states:
            out = self._yt_callback(self.admin, state)
            self.assertIn('Invalid or expired state', out, state)
        self.assertFalse(self.yt.api_token)

    def test_expired_state_rejected(self):
        old = SimpleNamespace(time=lambda: time.time() - tools.OAUTH_STATE_TTL - 5)
        with patch.object(tools, 'time', old):
            state = self._state('youtube', self.yt.id)
        self.assertIn('Invalid or expired state', self._yt_callback(self.admin, state))

    def test_meta_callback_requires_state(self):
        with patch('requests.post') as post:
            out = self._call(oauth_meta, 'MetaOAuthController', 'facebook_callback', self.admin, code='C')
        self.assertIn('Invalid or expired state', out)
        post.assert_not_called()

    def test_login_puts_signed_state(self):
        out = self._call(youtube_oauth, 'YouTubeOAuth', 'youtube_login', self.admin, account_id=str(self.yt.id))
        self.assertEqual(out[0], 'REDIRECT')
        from urllib.parse import parse_qs, urlparse
        state = parse_qs(urlparse(out[1]).query)['state'][0]
        self.assertEqual(
            tools.check_oauth_state(self.env(user=self.admin), 'youtube', state, self.session), self.yt.id)

    def test_state_is_single_use(self):
        state = self._state('youtube', self.yt.id)
        env = self.env(user=self.admin)
        self.assertEqual(tools.check_oauth_state(env, 'youtube', state, self.session), self.yt.id)
        self.assertIsNone(tools.check_oauth_state(env, 'youtube', state, self.session))
        # callback uçunda da: ikinci kullanım hesabı bağlamaz
        state2 = self._state('youtube', self.yt.id)
        self.assertEqual(self._yt_callback(self.admin, state2)[0], 'REDIRECT')
        self.assertIn('Invalid or expired state', self._yt_callback(self.admin, state2))

    def test_state_from_other_session_rejected(self):
        state = self._state('youtube', self.yt.id)
        self.assertIsNone(tools.check_oauth_state(self.env(user=self.admin), 'youtube', state, {}))

    def test_non_ascii_or_malformed_signature_rejected_not_500(self):
        env = self.env(user=self.admin)
        payload = self._state('youtube', self.yt.id).rsplit('.', 1)[0]
        for sig in ('ç' * 64, 'ı' + 'a' * 63, '', '%00'):
            self.assertIsNone(tools.check_oauth_state(env, 'youtube', payload + '.' + sig, self.session), sig)
        self.assertIn('Invalid or expired state', self._yt_callback(self.admin, payload + '.çş'))

    def test_nonce_store_is_bounded(self):
        for _i in range(tools._NONCE_MAX + 5):
            self._state('youtube', self.yt.id)
        self.assertLessEqual(len(self.session[tools._NONCE_KEY]), tools._NONCE_MAX)

    def test_plain_user_forbidden(self):
        cases = ((youtube_oauth, 'YouTubeOAuth', 'youtube_login', {'account_id': str(self.yt.id)}),
                 (youtube_oauth, 'YouTubeOAuth', 'youtube_callback', {'code': 'C'}),
                 (tiktok_oauth, 'TikTokOAuth', 'tiktok_login', {'account_id': str(self.yt.id)}),
                 (tiktok_oauth, 'TikTokOAuth', 'tiktok_callback', {'code': 'C'}),
                 (oauth_meta, 'MetaOAuthController', 'facebook_login', {}),
                 (oauth_meta, 'MetaOAuthController', 'facebook_callback', {'code': 'C'}))
        for module, cls_name, meth, kw in cases:
            with self.assertRaises(Forbidden, msg=meth):
                self._call(module, cls_name, meth, self.user, **kw)


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestResponseBodyMasked(_Base):
    """H3: servis hata gövdesi jetonu yankılasa da log maskeli."""

    def test_evolution_error_body_masked(self):
        with patch('requests.post', return_value=_resp({}, ok=False, text='bad apikey WAKEY1')), \
                self.assertLogs('odoo.addons.social_media_ai_manager.models.social_media_account', level='ERROR') as cm:
            self.assertFalse(self.wa._send_whatsapp_message('905550000000', 'merhaba'))
        logged = '\n'.join(r.getMessage() for r in cm.records)
        self.assertIn('***', logged)
        self.assertNotIn('WAKEY1', logged)

    def test_meta_error_body_masked(self):
        fb = self.env['social.media.account'].create({'name': 'FB', 'platform': 'facebook', 'api_token': 'FBTOK123'})
        with patch('requests.post', return_value=_resp({}, ok=False, text='{"token": "FBTOK123"}')), \
                self.assertLogs('odoo.addons.social_media_ai_manager.models.social_media_account', level='ERROR') as cm:
            fb._send_meta_message('psid', 'merhaba')
        self.assertNotIn('FBTOK123', '\n'.join(r.getMessage() for r in cm.records))
