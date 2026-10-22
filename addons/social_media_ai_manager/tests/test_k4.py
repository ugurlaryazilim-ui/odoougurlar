# -*- coding: utf-8 -*-
"""K4: webhook log, sırların URL'den çıkarılması + maskeleme, token alanlarının yönetici kısıtı."""
import hashlib
import hmac
import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from lxml import etree

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.social_media_ai_manager.controllers import oauth_meta
from odoo.addons.social_media_ai_manager.tools import make_oauth_state, mask_secrets

SECRET = 'SEKRETDEGER9'


def _resp(payload):
    m = MagicMock()
    m.json.return_value = payload
    m.ok = True
    return m


def _conn_error(token):
    # NEDEN: gerçek requests/urllib3 ConnectionError metni sorgu dizesini aynen taşır (A4 güvenlik D2)
    return requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='graph.facebook.com', port=443): Max retries exceeded with url: "
        "/v19.0/oauth/access_token?client_id=1&client_secret=%s&access_token=%s" % (SECRET, token))


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestMetaWebhookLog(HttpCase):
    """KK1: tam gövde INFO'da loglanmaz; DEBUG'da ve kısaltılmış."""
    URL = '/social_media_ai/webhook/meta'

    def test_body_logged_at_debug_truncated(self):
        self.env['social.media.account'].create({'name': 'FB', 'platform': 'facebook'})
        self.env['ir.config_parameter'].set_param('social_media_ai.enable_dms', 'True')
        self.env['ir.config_parameter'].set_param('social_media_ai.meta_app_secret', 'appsecret')
        body = json.dumps({'object': 'page', 'entry': [{'messaging': [{
            'sender': {'id': 'psid1'}, 'recipient': {'id': 'page1'},
            'message': {'mid': 'm1', 'text': 'BASLANGIC' + 'x' * 900 + 'SONISARET'},
        }]}]}).encode()
        sig = 'sha256=' + hmac.new(b'appsecret', body, hashlib.sha256).hexdigest()
        with self.assertLogs('odoo.addons.social_media_ai_manager.controllers.webhook_meta', level='DEBUG') as cm:
            res = self.url_open(self.URL, data=body, headers={
                'Content-Type': 'application/json', 'X-Hub-Signature-256': sig})
        self.assertEqual(res.status_code, 200)
        incoming = [r for r in cm.records if 'Incoming Meta Webhook' in r.getMessage()]
        self.assertTrue(incoming, 'DEBUG kaydı yok')
        for r in incoming:
            self.assertEqual(r.levelno, logging.DEBUG)
            self.assertLess(len(r.getMessage()), 700)
        for r in cm.records:
            self.assertNotIn('SONISARET', r.getMessage(), 'gövdenin sonu loglandı (kısaltma yok)')
            if r.levelno >= logging.INFO:
                self.assertNotIn('BASLANGIC', r.getMessage(), 'mesaj metni INFO+ seviyesinde loglandı')


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestMaskSecrets(TransactionCase):

    def test_mask_value_and_query_string(self):
        text = mask_secrets("url: /x?a=1&client_secret=ABCDEFG&access_token=TOK123 son", 'TOK123')
        self.assertNotIn('ABCDEFG', text)
        self.assertNotIn('TOK123', text)
        self.assertIn('a=1', text)
        self.assertEqual(mask_secrets('temiz metin', None, ''), 'temiz metin')


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestOAuthSecrets(TransactionCase):
    """KK3: OAuth çağrılarında sır URL'de gitmez; hata metni maskelenir, kullanıcıya genel mesaj + istisna adı."""

    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('social_media_ai.meta_app_id', '111')
        ICP.set_param('social_media_ai.meta_app_secret', SECRET)
        # NEDEN (A5 O1): OAuth uçları yalnız sistem yöneticisine açık ve imzalı state ister
        admin_env = self.env(user=new_test_user(
            self.env, login='k4_oauth_admin', groups='base.group_user,base.group_system'))
        self.fake_request = SimpleNamespace(env=admin_env, redirect=lambda url, **kw: ('REDIRECT', url))
        state = make_oauth_state(admin_env, 'meta', 0)
        # NEDEN: @http.route sarmalayıcısı dönüşü Response'a çevirir; gerçek metodu doğrudan çağırıyoruz
        ctrl = oauth_meta.MetaOAuthController()
        self.callback = lambda **kw: oauth_meta.MetaOAuthController.facebook_callback.__wrapped__(
            ctrl, state=state, **kw)

    def test_secrets_go_in_body_and_header_not_url(self):
        self.env['social.media.account'].create({'name': 'FB', 'platform': 'facebook', 'meta_page_id': 'p1'})

        def fake_post(url, data=None, **kw):
            if 'fb_exchange_token' in data:
                return _resp({'access_token': 'LONGTOK'})
            if 'code' in data:
                return _resp({'access_token': 'USERTOK'})
            return _resp({'success': True})   # sayfa webhook aboneliği
        with patch.object(oauth_meta, 'request', self.fake_request), \
                patch('requests.post', side_effect=fake_post) as post, \
                patch('requests.get', return_value=_resp({'access_token': 'PAGETOK', 'name': 'n'})) as get:
            out = self.callback(code='CODE1')
        self.assertEqual(out[0], 'REDIRECT')
        for call in post.call_args_list + get.call_args_list:
            self.assertNotRegex(call.args[0], r'SEKRET|TOK|CODE1|\?', 'sır/kod URL\'de gitti: %s' % call.args[0])
        self.assertEqual(post.call_args_list[0].kwargs['data']['client_secret'], SECRET)
        self.assertEqual(post.call_args_list[1].kwargs['data']['fb_exchange_token'], 'USERTOK')
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer LONGTOK')
        account = self.env['social.media.account'].search([('meta_page_id', '=', 'p1')])
        self.assertEqual(account.api_token, 'PAGETOK')

    def test_connection_error_not_leaked_to_user_or_log(self):
        with patch.object(oauth_meta, 'request', self.fake_request), \
                patch('requests.post', side_effect=_conn_error('USERTOK')), \
                self.assertLogs('odoo.addons.social_media_ai_manager.controllers.oauth_meta', level='ERROR') as cm:
            out = self.callback(code='CODE1')
        self.assertIn('ConnectionError', out)
        self.assertNotIn(SECRET, out)
        logged = '\n'.join(r.getMessage() + (r.exc_text or '') + str(r.exc_info) for r in cm.records)
        self.assertNotIn(SECRET, logged)
        self.assertNotIn('USERTOK', logged)


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestPostPublishSecrets(TransactionCase):
    """KK3: Instagram yayınında token gövdeyle gider; hata alanına sızmaz."""

    def setUp(self):
        super().setUp()
        self.account = self.env['social.media.account'].create({
            'name': 'IG', 'platform': 'instagram', 'meta_ig_id': 'ig1', 'api_token': 'IGSECRET1'})
        img = self.env['ir.attachment'].create({'name': 'a.jpg', 'mimetype': 'image/jpeg', 'raw': b'x', 'public': True})
        self.post = self.env['social.media.post'].create({
            'name': 'p', 'message': 'merhaba dünya', 'account_ids': [(6, 0, self.account.ids)],
            'image_ids': [(6, 0, img.ids)]})
        self.line = self.env['social.media.post.line'].create({'post_id': self.post.id, 'account_id': self.account.id})

    def test_token_in_body_not_url(self):
        with patch('requests.post', side_effect=[_resp({'id': 'c1'}), _resp({'id': 'pub1'})]) as post:
            self.assertTrue(self.line._publish_to_platform())
        self.assertEqual(self.line.state, 'success')
        for call in post.call_args_list:
            self.assertNotIn('?', call.args[0])
            self.assertNotIn('IGSECRET1', call.args[0])
            self.assertEqual(call.kwargs['data']['access_token'], 'IGSECRET1')
        first = post.call_args_list[0].kwargs['data']
        self.assertIn('/web/image/', first['image_url'])   # URL kodlaması requests'e bırakıldı
        self.assertEqual(first['caption'], 'merhaba dünya')

    def test_connection_error_masked_in_error_message(self):
        with patch('requests.post', side_effect=_conn_error('IGSECRET1')):
            self.assertFalse(self.line._publish_to_platform())
        self.assertEqual(self.line.state, 'error')
        self.assertIn('ConnectionError', self.line.error_message)
        self.assertNotIn('IGSECRET1', self.line.error_message)
        self.assertNotIn(SECRET, self.line.error_message)

    def test_publish_works_for_unprivileged_user(self):
        user = new_test_user(self.env, login='k4_pub', groups='base.group_user')
        line = self.line.with_user(user)
        with patch('requests.post', side_effect=[_resp({'id': 'c1'}), _resp({'id': 'pub1'})]) as post:
            self.assertTrue(line._publish_to_platform())
        self.assertEqual(post.call_args_list[0].kwargs['data']['access_token'], 'IGSECRET1')


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestAccountTokenAccess(TransactionCase):
    """KK4: token/secret alanları yalnız base.group_system; cron/webhook/gönderim sudo ile çalışmaya devam eder."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login='k4_user', groups='base.group_user')
        cls.admin = new_test_user(cls.env, login='k4_admin', groups='base.group_user,base.group_system')
        cls.account = cls.env['social.media.account'].create({
            'name': 'IG', 'platform': 'instagram', 'meta_ig_id': 'ig1', 'api_token': 'IGSECRET1',
            'webhook_secret': 'VERIFY1'})

    def test_all_secret_fields_are_admin_only(self):
        Account = self.env['social.media.account']
        secrets = [n for n in Account._fields if any(w in n for w in ('token', 'secret'))]
        self.assertTrue({'api_token', 'webhook_secret', 'youtube_refresh_token', 'tiktok_refresh_token'} <= set(secrets))
        for name in secrets:
            self.assertEqual(Account._fields[name].groups, 'base.group_system', name)

    def test_internal_user_cannot_read_or_search_tokens(self):
        acc = self.account.with_user(self.user)
        self.assertEqual(acc.name, 'IG')   # token dışı alanlar okunur
        for name in ('api_token', 'webhook_secret', 'youtube_refresh_token', 'tiktok_refresh_token'):
            with self.assertRaises(AccessError, msg=name):
                acc.read([name])
        with self.assertRaises(AccessError):
            self.env['social.media.account'].with_user(self.user).search_read([], ['name', 'api_token'])
        self.assertNotIn('api_token', self.env['social.media.account'].with_user(self.user).fields_get())

    def test_internal_user_cannot_write_tokens(self):
        with self.assertRaises(AccessError):
            self.account.with_user(self.user).write({'api_token': 'ele-gecirildi'})
        self.assertEqual(self.account.api_token, 'IGSECRET1')

    def test_admin_still_reads_tokens(self):
        self.assertEqual(self.account.with_user(self.admin).api_token, 'IGSECRET1')

    def test_form_view_loads_for_both_and_hides_fields(self):
        Account = self.env['social.media.account']
        arch_user = Account.with_user(self.user).get_view(view_type='form')['arch']
        arch_admin = Account.with_user(self.admin).get_view(view_type='form')['arch']
        names_user = set(etree.fromstring(arch_user).xpath('//field/@name'))
        names_admin = set(etree.fromstring(arch_admin).xpath('//field/@name'))
        self.assertFalse({'api_token', 'webhook_secret', 'youtube_refresh_token', 'tiktok_refresh_token'} & names_user)
        self.assertTrue({'api_token', 'webhook_secret', 'youtube_refresh_token', 'tiktok_refresh_token'} <= names_admin)
        self.assertIn('name', names_user)

    def _out_message(self, user, account, content='merhaba'):
        conv = self.env['social.media.conversation'].create({
            'account_id': account.id, 'social_user_id': 'u1', 'state': 'open'})
        self.env['social.media.message'].with_user(user).create({
            'conversation_id': conv.id, 'message_type': 'outgoing', 'content': content})

    def test_human_reply_from_inbox_sends_with_token_for_unprivileged_user(self):
        # NEDEN: create() gönderim hatasını yutar; token okuması AccessError verse mesaj sessizce gitmezdi
        with patch('requests.post', return_value=_resp({})) as post:
            self._out_message(self.user, self.account)
        self.assertTrue(post.called, 'mesaj platforma gönderilmedi')
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer IGSECRET1')

    def test_whatsapp_reply_for_unprivileged_user(self):
        wa = self.env['social.media.account'].create({
            'name': 'WA', 'platform': 'whatsapp', 'api_token': 'WAKEY1',
            'whatsapp_api_url': 'https://evo.example', 'whatsapp_instance_name': 'inst'})
        with patch('requests.post', return_value=_resp({})) as post:
            self._out_message(self.user, wa)
        self.assertEqual(post.call_args.kwargs['headers']['apikey'], 'WAKEY1')

    def test_whatsapp_test_button_admin_only(self):
        # A5 Y1: test düğmesi jetonu hesabın URL'sine gönderir; yalnız sistem yöneticisi
        wa = self.env['social.media.account'].create({
            'name': 'WA', 'platform': 'whatsapp', 'api_token': 'WAKEY1', 'phone_number': '905551112233',
            'whatsapp_api_url': 'https://evo.example', 'whatsapp_instance_name': 'inst'})
        with patch('requests.post', return_value=_resp({})) as post:
            with self.assertRaises(AccessError):
                wa.with_user(self.user).action_test_whatsapp()
            post.assert_not_called()
            with self.assertRaisesRegex(Exception, 'başarıyla gönderildi'):
                wa.with_user(self.admin).action_test_whatsapp()
        self.assertEqual(post.call_args.kwargs['headers']['apikey'], 'WAKEY1')

    def test_youtube_reply_and_token_refresh_for_unprivileged_user(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('social_media_ai.youtube_client_id', 'cid')
        ICP.set_param('social_media_ai.youtube_client_secret', 'sec')
        yt = self.env['social.media.account'].create({
            'name': 'YT', 'platform': 'youtube', 'api_token': 'OLD', 'youtube_refresh_token': 'RT1'})
        acc = yt.with_user(self.user)
        with patch('requests.post', return_value=_resp({'access_token': 'NEW1', 'expires_in': 3600})):
            self.assertTrue(acc._refresh_youtube_token())
        self.assertEqual(yt.api_token, 'NEW1')
        with patch('requests.post', return_value=_resp({})) as post:
            acc._send_youtube_comment_reply('c1', 'yanıt', acc)
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer NEW1')

    def test_ai_cron_sends_with_token(self):
        # Cron/kuyruk kök kullanıcıyla çalışır; token okuması ve gönderim değişmeden sürer
        conv = self.env['social.media.conversation'].create({
            'account_id': self.account.id, 'social_user_id': 'u1', 'state': 'bot'})
        self.env['social.media.message'].create({
            'conversation_id': conv.id, 'message_type': 'incoming', 'content': 'merhaba'})
        provider = type(self.env['social.media.ai.provider'])
        # NEDEN: kuyruk işlem başına commit eder; test imlecinde commit yasak, savepoint'li taklit yeter
        self.patch(self.env.cr, 'commit', lambda: None)
        with patch.object(provider, 'generate_response', return_value='cevap'), \
                patch('requests.post', return_value=_resp({})) as post:
            self.env['social.media.message']._cron_process_ai_queue(limit=10, time_budget=30)
        self.assertTrue(post.called, 'AI yanıtı platforma gönderilmedi')
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer IGSECRET1')

    def test_tiktok_refresh_for_unprivileged_user(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('social_media_ai.tiktok_client_key', 'ck')
        ICP.set_param('social_media_ai.tiktok_client_secret', 'cs')
        tt = self.env['social.media.account'].create({
            'name': 'TT', 'platform': 'tiktok', 'api_token': 'OLD', 'tiktok_refresh_token': 'RT2'})
        with patch('requests.post', return_value=_resp({'access_token': 'NEWTT', 'refresh_token': 'RT3'})):
            self.assertTrue(tt.with_user(self.user)._refresh_tiktok_token())
        self.assertEqual((tt.api_token, tt.tiktok_refresh_token), ('NEWTT', 'RT3'))


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestSettingsCronRead(TransactionCase):
    """Ayar ekranı get_values: ir.cron okuma hakkı olmayan kullanıcıda AccessError vermemeli."""

    def test_get_values_without_cron_access(self):
        user = new_test_user(self.env, login='k4_plain', groups='base.group_user')
        with self.assertRaises(AccessError):   # önkoşul: kullanıcı gerçekten ir.cron okuyamaz
            self.env['ir.cron'].with_user(user).search_read([], ['interval_number'], limit=1)
        values = self.env['res.config.settings'].with_user(user).get_values()
        cron = self.env.ref('social_media_ai_manager.ir_cron_publish_social_posts')
        self.assertEqual(values['social_post_cron_interval'], cron.interval_number)
