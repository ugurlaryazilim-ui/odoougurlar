# -*- coding: utf-8 -*-
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

    def test_expiring_token_is_refreshed(self):
        # süre payından kısa token önbelleğe girmez → her çağrıda yenilenir
        with patch(POST, return_value=self._resp('T3', expires_in=100)) as post:
            self.account._refresh_youtube_token()
            self.account._refresh_youtube_token()
        self.assertEqual(post.call_count, 2)
