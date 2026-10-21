# -*- coding: utf-8 -*-
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

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

    # NEDEN: ham SQL, başka sürecin commit ettiği yazımı taklit eder (ORM önbelleği eski kalır, DB satırı yeni).
    def test_fresh_token_from_other_process_is_adopted_without_google_call(self):
        acc = self.account.create({'name': 'YT2', 'platform': 'youtube', 'youtube_refresh_token': 'rt',
                                   'api_token': 'eski'})
        self.env.cr.execute("UPDATE social_media_account SET api_token = 'DIGER', write_date = "
                            "(now() at time zone 'UTC') - 60 * interval '1 second' WHERE id = %s", (acc.id,))
        with patch(POST, return_value=self._resp('YENI')) as post, \
                patch.object(type(acc), 'write', autospec=True) as w, \
                patch.object(acc.pool, 'cursor', return_value=nullcontext(self.env.cr)):
            self.assertTrue(acc._refresh_youtube_token())
        post.assert_not_called()
        w.assert_not_called()
        self.assertEqual(acc.api_token, 'DIGER')

    def test_old_token_in_db_is_refreshed_normally(self):
        acc = self.account.create({'name': 'YT3', 'platform': 'youtube', 'youtube_refresh_token': 'rt',
                                   'api_token': 'eski'})
        self.env.cr.execute("UPDATE social_media_account SET api_token = 'DIGER', write_date = "
                            "(now() at time zone 'UTC') - 4000 * interval '1 second' WHERE id = %s", (acc.id,))
        with patch(POST, return_value=self._resp('YENI')) as post, \
                patch.object(acc.pool, 'cursor', return_value=nullcontext(self.env.cr)):
            self.assertTrue(acc._refresh_youtube_token())
        self.assertEqual(post.call_count, 1)
        self.assertEqual(acc.api_token, 'YENI')

    def test_expiring_token_is_refreshed(self):
        # süre payından kısa token önbelleğe girmez → her çağrıda yenilenir
        with patch(POST, return_value=self._resp('T3', expires_in=100)) as post:
            self.account._refresh_youtube_token()
            self.account._refresh_youtube_token()
        self.assertEqual(post.call_count, 2)
