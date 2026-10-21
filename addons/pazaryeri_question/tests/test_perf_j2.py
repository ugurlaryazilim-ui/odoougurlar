from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'pazaryeri_question')
class TestQuestionPerfJ2(TransactionCase):
    """TODO-23: soru cron'u toplu arama, sahte değişiklik yok, remaining_* yalnız değişince yazılır."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Q = cls.env['marketplace.question']
        cls.conn = cls.env['trendyol.question.connector']
        cls.store = cls.env['trendyol.store'].create({
            'name': 'TY J2', 'api_key': 'k', 'api_secret': 's', 'seller_id': '9921',
        })
        cls.created_ms = int((datetime.now(timezone.utc) - timedelta(hours=5)).timestamp() * 1000) + 123

    def _payload(self, qid, answered=False):
        data = {
            'id': qid, 'text': 'Beden?', 'userName': 'Ali', 'showUserName': True, 'customerId': 7,
            'productName': 'Ürün', 'imageUrl': 'http://i', 'webUrl': 'http://w', 'productMainId': 'PM1',
            'status': 'WAITING_FOR_ANSWER', 'public': True, 'creationDate': self.created_ms,
        }
        if answered:
            data.update(status='ANSWERED', answer={'id': 55, 'text': 'Standart', 'creationDate': self.created_ms})
        return data

    def _run_page(self, payloads):
        cache = self.conn._prefetch_existing([str(p['id']) for p in payloads])
        return [self.conn._process_question(p, self.store, cache=cache) for p in payloads]

    def test_ts_is_utc_without_microseconds(self):
        value = self.conn._ts(1_700_000_000_123)
        self.assertEqual(value, datetime(2023, 11, 14, 22, 13, 20))

    def test_unchanged_question_not_written_and_not_counted(self):
        payloads = [self._payload(9100 + i, answered=bool(i % 2)) for i in range(4)]
        self.assertEqual(self._run_page(payloads), ['created'] * 4)
        with patch.object(self.registry['marketplace.question'], 'write', autospec=True) as write:
            self.assertEqual(self._run_page(payloads), ['unchanged'] * 4,
                             "değişmeyen soru güncellenmiş sayılmamalı")
        write.assert_not_called()
        self.assertEqual(self.env['marketplace.question.answer'].search_count(
            [('question_id.external_question_id', 'in', ['9101', '9103'])]), 2, "cevap geçmişi çoğalmamalı")

    def test_real_change_counted_and_written_once(self):
        payload = self._payload(9200)
        self._run_page([payload])
        payload['text'] = 'Beden tablosu?'
        self.assertEqual(self._run_page([payload]), ['updated'])
        self.assertEqual(self.Q.search([('external_question_id', '=', '9200')]).question_text, 'Beden tablosu?')

    def test_new_answer_counts_as_update(self):
        payload = self._payload(9300)
        self._run_page([payload])
        self.assertEqual(self._run_page([self._payload(9300, answered=True)]), ['updated'])
        self.assertEqual(self._run_page([self._payload(9300, answered=True)]), ['unchanged'])

    def test_page_uses_no_per_question_search(self):
        payloads = [self._payload(9400 + i, answered=True) for i in range(5)]
        self._run_page(payloads)
        cache = self.conn._prefetch_existing([str(p['id']) for p in payloads])
        calls = []
        orig = self.registry['marketplace.question.answer'].search

        def spy(model, *a, **kw):
            calls.append(a)
            return orig(model, *a, **kw)

        with patch.object(self.registry['marketplace.question.answer'], 'search', spy), \
                patch.object(self.registry['marketplace.question'], 'search', spy):
            for p in payloads:
                self.conn._process_question(p, self.store, cache=cache)
        self.assertFalse(calls, "önbellek verilince soru başına search yapılmamalı")

    def test_remaining_cron_writes_only_when_changed(self):
        waiting = self.Q.create({
            'marketplace_type': 'trendyol', 'external_question_id': 'J2R1', 'question_text': 'x',
            'status': 'waiting', 'question_date': fields.Datetime.now() - timedelta(hours=5, minutes=3),
        })
        self.assertEqual(waiting.remaining_hours, 66.0)  # 71h57m -> tam saate indirilir
        self.assertIn('2 gün 18 saat', waiting.remaining_time_display)  # 66.9 saat: ekran int(hours) ile aynı kalır
        with patch.object(self.registry['marketplace.question'], 'write', autospec=True) as write:
            self.Q._cron_update_remaining_time()
        write.assert_not_called()
        # Bayat değer -> cron düzeltir (yalnız bu kayıt)
        waiting.write({'remaining_hours': 1.0, 'remaining_time_display': 'eski'})
        self.Q._cron_update_remaining_time()
        self.assertEqual(waiting.remaining_hours, 66.0)
        self.assertIn('2 gün', waiting.remaining_time_display)

