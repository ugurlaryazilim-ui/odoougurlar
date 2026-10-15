from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


class SyncApi:
    """Tarih aralıklı finans servislerini taklit eder; istenen tipe göre kayıt döner."""

    def __init__(self, settlements=None, other=None, fail_payment_orders=False):
        self.settlements = settlements or []
        self.other = other or {}  # transactionType → kayıtlar
        self.fail_payment_orders = fail_payment_orders
        self.calls = []

    def _page(self, items):
        return {'success': True, 'data': {'content': items, 'totalPages': 1}}

    def get_settlements(self, start_date=None, end_date=None, transaction_types=None, **kw):
        self.calls.append(('settlements', kw.get('payment_order_id')))
        return self._page(self.settlements)

    def get_other_financials(self, start_date=None, end_date=None, transaction_type=None,
                             transaction_sub_type=None, **kw):
        self.calls.append(('other', transaction_type, transaction_sub_type))
        if transaction_sub_type:
            return self._page([])
        return self._page(self.other.get(transaction_type, []))

    def get_payment_orders(self, page=0):
        if self.fail_payment_orders:
            raise RuntimeError('ödeme servisi çöktü')
        return self._page([])

    def get_cargo_invoice_items(self, serial, page=0):
        return self._page([])


def _sale(tid, order, commission_invoice=None):
    return {'id': tid, 'transactionType': 'Satış', 'description': 'Satış', 'credit': 1000.0, 'debt': 0.0,
            'commissionRate': 15.0, 'commissionAmount': 150.0, 'sellerRevenue': 850.0,
            'commissionInvoiceSerialNumber': commission_invoice, 'orderNumber': order,
            'receiptId': 48376618, 'transactionDate': 1788385121995}


@tagged('post_install', '-at_install', 'trendyol_integration')
class TestFinanceSync(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Settlement = cls.env['trendyol.settlement']
        cls.store = cls.env['trendyol.store'].create({
            'name': 'TY Sync Test', 'api_key': 'k', 'api_secret': 's', 'seller_id': '998',
        })

    def _sync(self, api):
        self.patch(type(self.store), 'get_api', lambda store: api)
        return self.Settlement.sync_financials_for_store(self.store)

    def _records(self, **domain):
        return self.Settlement.search([('store_id', '=', self.store.id)]
                                      + [(k, '=', v) for k, v in domain.items()])

    def test_commission_invoice_no_stored_and_searchable(self):
        """Satışın komisyon fatura no'su (DCF) kaydedilir, sonradan dolar, boş gelince silinmez."""
        self._sync(SyncApi(settlements=[_sale('s1', '111')]))
        rec = self._records(trendyol_id='s1')
        self.assertTrue(rec)
        self.assertFalse(rec.commission_invoice_no)

        self._sync(SyncApi(settlements=[_sale('s1', '111', 'DCF2026004839667')]))
        self.assertEqual(rec.commission_invoice_no, 'DCF2026004839667')

        self._sync(SyncApi(settlements=[_sale('s1', '111')]))
        self.assertEqual(rec.commission_invoice_no, 'DCF2026004839667')

        # Dekont No araması komisyon fatura no'yu da bulur
        found = self.Settlement.search([('store_id', '=', self.store.id),
                                        '|', ('receipt_id', 'ilike', 'DCF2026004839667'),
                                        ('commission_invoice_no', 'ilike', 'DCF2026004839667')])
        self.assertEqual(found, rec)

    def test_new_other_financial_types(self):
        """Komisyon mutabakat, iade faturası ve düzeltme kayıtları çekilir ve sınıflandırılır."""
        other = {
            'CommissionAgreementInvoice': [{'id': 'ca1', 'transactionType': 'Bilinmeyen Ad', 'debt': 40.0,
                                            'credit': 0.0, 'transactionDate': 1788385121995}],
            'ReturnInvoice': [{'id': 'ri1', 'transactionType': 'X', 'debt': 0.0, 'credit': 300.0,
                               'transactionDate': 1788385121995}],
            'FinancialItem': [{'id': 'fi1', 'transactionType': 'Y', 'debt': 12.5, 'credit': 0.0,
                               'transactionDate': 1788385121995}],
        }
        api = SyncApi(other=other)
        self._sync(api)
        requested = {c[1] for c in api.calls if c[0] == 'other'}
        self.assertTrue({'CommissionAgreementInvoice', 'ReturnInvoice', 'FinancialItem'} <= requested)
        self.assertEqual(self._records(trendyol_id='ca1').transaction_type, 'commission_agreement')
        self.assertEqual(self._records(trendyol_id='ri1').transaction_type, 'return_invoice')
        fi = self._records(trendyol_id='fi1')
        self.assertEqual(fi.transaction_type, 'financial_item')
        self.assertAlmostEqual(fi.signed_seller_revenue, -12.5)

        # Ödeme no ile (tipsiz) gelen aynı kayıt, bilinen sınıfı 'Diğer'e düşürmez
        self.Settlement._process_settlement_item(
            {'id': 'fi1', 'transactionType': 'Y', 'debt': 12.5, 'credit': 0.0}, self.store, 'otherfinancials')
        self.assertEqual(fi.transaction_type, 'financial_item')

    def test_failing_step_does_not_stop_others(self):
        """Bir adım hata verse de önceki ve sonraki adımlar çalışır, hata sonuca yazılır."""
        res = self._sync(SyncApi(settlements=[_sale('s2', '222')], fail_payment_orders=True))
        self.assertTrue(self._records(trendyol_id='s2'))
        self.assertEqual(res['errors'], 1)
        self.assertIn('Ödeme emirleri', res['error_details'])

    def test_deep_scan_schedules_backfill(self):
        """Gece taraması son N günü otomatik tamamlama olarak planlar; süren iş varsa dokunmaz."""
        self.store.financial_deep_scan_days = 60
        other = self.env['trendyol.store'].create({
            'name': 'TY Busy', 'api_key': 'k', 'api_secret': 's', 'seller_id': '997',
            'backfill_from': fields.Date.today() - timedelta(days=90),
            'backfill_to': fields.Date.today(), 'backfill_next': fields.Date.today() - timedelta(days=30),
        })
        off = self.env['trendyol.store'].create({
            'name': 'TY Off', 'api_key': 'k', 'api_secret': 's', 'seller_id': '996',
            'financial_deep_scan_days': 0,
        })
        self.Settlement.cron_financial_deep_scan()
        today = fields.Date.context_today(self.Settlement)
        self.assertTrue(self.store.backfill_auto)
        self.assertEqual(self.store.backfill_from, today - timedelta(days=60))
        self.assertEqual(self.store.backfill_next, self.store.backfill_from)
        self.assertEqual(self.store.backfill_to, today)
        self.assertFalse(other.backfill_auto)
        self.assertEqual(other.backfill_next, fields.Date.today() - timedelta(days=30))
        self.assertFalse(off.backfill_next)

    def test_cron_active_flag(self):
        cron = self.env.ref('trendyol_integration.cron_trendyol_sync_financials')
        cron.active = False
        self.store.invalidate_recordset(['financial_cron_active'])
        self.assertFalse(self.store.financial_cron_active)
        self.store.action_activate_financial_cron()
        self.assertTrue(cron.active)
        self.assertEqual(cron.interval_number, 1)
        self.assertEqual(cron.interval_type, 'hours')
