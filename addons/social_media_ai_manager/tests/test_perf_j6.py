# -*- coding: utf-8 -*-
import ast
import os
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestSocialPerfJ6(TransactionCase):
    """J6 / TODO-30: AI kuyruk süre bütçesi + indeks, takılı gönderi, HTTP timeout."""

    def test_every_http_call_has_timeout(self):
        # NEDEN: timeout'suz requests çağrısı cron işçisini sonsuza dek tutar; yeni çağrılar da yakalansın.
        missing = []
        for sub in ('models', 'controllers'):
            for fn in sorted(os.listdir(os.path.join(MODULE_DIR, sub))):
                if not fn.endswith('.py'):
                    continue
                path = os.path.join(MODULE_DIR, sub, fn)
                with open(path, encoding='utf-8') as fh:
                    tree = ast.parse(fh.read())
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and isinstance(node.func.value, ast.Name) and node.func.value.id == 'requests'
                            and node.func.attr in ('get', 'post', 'put', 'patch', 'delete', 'request')
                            and not any(k.arg == 'timeout' for k in node.keywords)):
                        missing.append('%s:%s' % (fn, node.lineno))
        self.assertFalse(missing, 'timeout eksik: %s' % missing)

    def test_ai_queue_partial_index_exists(self):
        self.env.cr.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'social_media_message' AND indexdef ILIKE %s",
            ['%ai_processed%'])
        self.assertTrue(self.env.cr.fetchall(), 'AI kuyruğu kısmi indeksi yok')

    def _incoming(self):
        account = self.env['social.media.account'].create({'name': 'IG', 'platform': 'instagram'})
        conv = self.env['social.media.conversation'].create({
            'account_id': account.id, 'social_user_id': 'u1', 'state': 'bot'})
        return self.env['social.media.message'].create({
            'conversation_id': conv.id, 'message_type': 'incoming', 'content': 'merhaba'})

    def test_ai_queue_stops_when_time_budget_is_spent(self):
        msg = self._incoming()
        provider = type(self.env['social.media.ai.provider'])
        with patch.object(provider, 'generate_response', return_value='x') as gen:
            self.env['social.media.message']._cron_process_ai_queue(limit=10, time_budget=0)
        gen.assert_not_called()
        self.assertFalse(msg.ai_processed)

    def test_stuck_posting_post_is_failed_recent_one_is_kept(self):
        Post = self.env['social.media.post']
        account = self.env['social.media.account'].create({'name': 'FB', 'platform': 'facebook'})
        stuck = Post.create({'name': 'eski', 'message': 'm', 'state': 'posting'})
        fresh = Post.create({'name': 'yeni', 'message': 'm', 'state': 'posting'})
        line = self.env['social.media.post.line'].create({'post_id': stuck.id, 'account_id': account.id})
        self.env.cr.execute(
            "UPDATE social_media_post SET write_date = now() at time zone 'utc' - interval '2 hours' WHERE id = %s",
            [stuck.id])
        (stuck | fresh).invalidate_recordset()
        failed = Post._fail_stuck_posting_posts()
        self.assertEqual(failed, stuck)
        self.assertEqual(stuck.state, 'error')
        self.assertEqual(line.state, 'error')
        self.assertEqual(fresh.state, 'posting')
