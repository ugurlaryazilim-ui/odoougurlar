"""K2 (P3 temizlik): çift index, `_differs` normalize, iş yoksa DEBUG."""
import logging
from datetime import datetime
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

MODEL_LOGGER = 'odoo.addons.pazaryeri_question.models.marketplace_question'
CONNECTOR_LOGGER = 'odoo.addons.pazaryeri_question.models.trendyol_question_connector'


@tagged('post_install', '-at_install', 'pazaryeri_question')
class TestK2Cleanup(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Q = cls.env['marketplace.question']
        cls.conn = cls.env['trendyol.question.connector']
        cls.store = cls.env['trendyol.store'].create({
            'name': 'TY K2', 'api_key': 'k', 'api_secret': 's', 'seller_id': '9931',
            'question_sync_enabled': True,
        })

    # ── KK2: çift index ──

    def test_question_date_has_single_index(self):
        self.env.cr.execute("""
            SELECT indexname FROM pg_indexes
             WHERE tablename = 'marketplace_question'
               AND indexdef LIKE '%%(question_date)%%'""")
        names = [r[0] for r in self.env.cr.fetchall()]
        self.assertEqual(len(names), 1, "question_date için tek index olmalı: %s" % names)

    # ── KK4: `_differs` ──

    def _question(self, **vals):
        base = {
            'marketplace_type': 'trendyol', 'store_id': self.store.id,
            'external_question_id': 'K2-Q1', 'question_text': 'Beden?',
            'customer_name': 'Ali', 'status': 'waiting', 'is_public': True,
            'question_date': datetime(2026, 10, 1, 10, 0, 0),
        }
        base.update(vals)
        return self.Q.create(base)

    def test_differs_ignores_type_noise(self):
        q = self._question(customer_id_external='123')
        self.assertFalse(self.conn._differs(q, {'customer_id_external': 123}))
        self.assertFalse(self.conn._differs(q, {'question_text': 'Beden?  '}))
        self.assertFalse(self.conn._differs(q, {'answered_date_message': ''}))
        self.assertFalse(self.conn._differs(q, {'rejection_reason': None}))
        self.assertFalse(self.conn._differs(q, {'rejection_reason': False}))
        self.assertFalse(self.conn._differs(q, {'is_public': 1}))
        self.assertFalse(self.conn._differs(q, {'store_id': self.store.id}))
        self.assertFalse(self.conn._differs(q, {'store_id': self.store}))
        self.assertFalse(self.conn._differs(q, {'question_date': datetime(2026, 10, 1, 10, 0, 0)}))

    def test_differs_detects_real_changes(self):
        q = self._question(customer_id_external='123')
        self.assertTrue(self.conn._differs(q, {'customer_id_external': 124}))
        self.assertTrue(self.conn._differs(q, {'question_text': 'Renk?'}))
        self.assertTrue(self.conn._differs(q, {'answered_date_message': 'x'}))
        self.assertTrue(self.conn._differs(q, {'is_public': False}))
        self.assertTrue(self.conn._differs(q, {'status': 'answered'}))
        self.assertTrue(self.conn._differs(q, {'question_date': datetime(2026, 10, 1, 10, 0, 1)}))
        self.assertTrue(self.conn._differs(q, {'store_id': False}))

    # ── KK5: iş yoksa DEBUG ──

    def test_question_cron_idle_logs_no_info_but_work_does(self):
        stores_model = type(self.env['trendyol.store'])
        with patch.object(self.registry['trendyol.question.connector'], 'sync_questions_for_store',
                          return_value={'created': 0, 'updated': 0}), \
                patch.object(stores_model, 'search', return_value=self.store), \
                self.assertNoLogs(MODEL_LOGGER, logging.INFO):
            self.Q._cron_sync_all_questions()
        with patch.object(self.registry['trendyol.question.connector'], 'sync_questions_for_store',
                          return_value={'created': 2, 'updated': 0}), \
                patch.object(stores_model, 'search', return_value=self.store), \
                self.assertLogs(MODEL_LOGGER, logging.INFO) as logs:
            self.Q._cron_sync_all_questions()
        self.assertTrue(any('Yeni: 2' in r.getMessage() for r in logs.records))

    def test_connector_idle_logs_no_info(self):
        class Api:
            def _request(self, method, path, params=None):
                return {'success': True, 'data': {'content': [], 'totalPages': 0, 'totalElements': 0}}

        with patch.object(type(self.store), 'get_api', return_value=Api()), \
                self.assertNoLogs(CONNECTOR_LOGGER, logging.INFO):
            result = self.conn.sync_questions_for_store(self.store)
        self.assertEqual(result, {'created': 0, 'updated': 0})
