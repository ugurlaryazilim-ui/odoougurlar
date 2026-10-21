# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo import SUPERUSER_ID, api
from odoo.tests import TransactionCase, tagged

POST = 'requests.post'


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestYoutubeTokenRefresh(TransactionCase):
    """TODO-22: geçerli YouTube token'ı her 10 dk'da yenilenmez / yeniden yazılmaz."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param('social_media_ai.youtube_client_id', 'cid')
        ICP.set_param('social_media_ai.youtube_client_secret', 'sec')
        cls.account = cls.env['social.media.account'].create({
            'name': 'YT', 'platform': 'youtube', 'youtube_refresh_token': 'rt',
        })

    def _resp(self, token='T1', expires_in=3600):
        r = MagicMock()
        r.json.return_value = {'access_token': token, 'expires_in': expires_in}
        return r

    # ── Çok süreç: GERÇEK ayrı bağlantılar ────────────────────────────────────────────
    # NEDEN: `_youtube_token_from_other_process` gerçek bir ikinci bağlantıyla okur (`pool.cursor()`); test
    # işlemi bunu göremez (kaydedilmemiş veri). Bu yüzden satır gerçekten commit edilir, "bu süreç" taze bir
    # bağlantıdır ve "diğer süreç" üçüncü bir bağlantıyla commit eder: üretimdeki anlık görüntü farkı birebir.

    def _commit_account(self, **vals):
        with self.registry.cursor() as cr:
            acc = api.Environment(cr, SUPERUSER_ID, {})['social.media.account'].create(dict(
                {'name': 'YT-MP', 'platform': 'youtube', 'youtube_refresh_token': 'rt', 'api_token': 'eski'},
                **vals))
            acc_id = acc.id
        self.addCleanup(self._drop_account, acc_id)
        return acc_id

    def _drop_account(self, acc_id):
        with self.registry.cursor() as cr:
            cr.execute("DELETE FROM social_media_account WHERE id = %s", (acc_id,))

    def _other_process_writes(self, acc_id, token, age_seconds):
        with self.registry.cursor() as cr:
            cr.execute("UPDATE social_media_account SET api_token = %s, write_date = "
                       "(now() at time zone 'UTC') - %s * interval '1 second' WHERE id = %s",
                       (token, age_seconds, acc_id))

    def _run_as_process(self, acc_id, other_token, age_seconds):
        """Anlık görüntüsü alınmış bir süreçte yenilemeyi çalıştır; diğer süreç araya commit eder."""
        with self.registry.cursor() as cr:
            acc = api.Environment(cr, SUPERUSER_ID, {})['social.media.account'].browse(acc_id)
            self.assertEqual(acc.api_token, 'eski')   # anlık görüntü burada alındı
            self._other_process_writes(acc_id, other_token, age_seconds)
            self.assertEqual(acc.api_token, 'eski')   # bu süreç diğerinin commit'ini göremez
            with patch(POST, return_value=self._resp('YENI')) as post, \
                    patch.object(type(acc.env['ir.config_parameter']), 'get_param',
                                 side_effect=lambda key, default=False: 'x'):
                result = acc._refresh_youtube_token()
            return result, post, acc.api_token

    def test_valid_token_is_not_refreshed_again(self):
        with patch(POST, return_value=self._resp()) as post:
            self.assertTrue(self.account._refresh_youtube_token())
            self.assertEqual(self.account.api_token, 'T1')
            with patch.object(type(self.account), 'write', autospec=True) as w:
                self.assertTrue(self.account._refresh_youtube_token())
            w.assert_not_called()
        self.assertEqual(post.call_count, 1)

    def test_changed_token_in_db_forces_refresh(self):
        with patch(POST, return_value=self._resp('T2')) as post:
            self.account._refresh_youtube_token()
            self.account.api_token = 'baska'  # yeniden bağlanma vb.
            self.account._refresh_youtube_token()
        self.assertEqual(post.call_count, 2)
        self.assertEqual(self.account.api_token, 'T2')

    def test_fresh_token_from_other_process_is_adopted_without_google_call(self):
        acc_id = self._commit_account()
        result, post, token = self._run_as_process(acc_id, 'DIGER', age_seconds=60)
        self.assertTrue(result)
        post.assert_not_called()
        self.assertEqual(token, 'DIGER')

    def test_old_token_in_db_is_refreshed_normally(self):
        acc_id = self._commit_account()
        _result, post, token = self._run_as_process(acc_id, 'DIGER', age_seconds=4000)
        # NEDEN: eski token benimsenmez, Google'a gidilir. Sonuç (True/False) bilerek denetlenmez: bu yapay
        # senaryoda (eski write_date'li yazım anlık görüntüden SONRA commit) yeni token yazımı gerçek
        # REPEATABLE READ altında serileştirme çakışmasına düşer; üretimde eski yazım zaten anlık görüntüden önce.
        self.assertEqual(post.call_count, 1)
        self.assertNotEqual(token, 'DIGER')

    def test_expiring_token_is_refreshed(self):
        # süre payından kısa token önbelleğe girmez → her çağrıda yenilenir
        with patch(POST, return_value=self._resp('T3', expires_in=100)) as post:
            self.account._refresh_youtube_token()
            self.account._refresh_youtube_token()
        self.assertEqual(post.call_count, 2)
