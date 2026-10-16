from odoo.tests import TransactionCase, tagged

DCF = 'DCF2026004839667'

# Canlı servisten (16.10.2026) kısaltılmış örnekler
DCF_INVOICE = {
    'id': DCF, 'transactionDate': 1791936000000, 'transactionType': 'Komisyon Faturası',
    'receiptId': None, 'description': '08 Ekim - 14 Ekim arası Trendyol hakediş tutarı',
    'debt': 2472.08, 'credit': 0.0, 'commissionInvoiceSerialNumber': DCF, 'paymentOrderId': None,
    'affiliate': 'TRENDYOLTR',
}
DDF_PLATFORM = {
    'id': 'DDF2026023484617', 'transactionDate': 1792013847518, 'transactionType': 'Platform Hizmet Bedeli',
    'receiptId': None, 'description': 'Platform Hizmet Bedeli faturasıdır.', 'debt': 250.61, 'credit': 0.0,
    'commissionInvoiceSerialNumber': 'DDF2026023484617', 'paymentOrderId': 78039405, 'affiliate': 'TRENDYOLTR',
}


def _sale(tid, order, commission, invoice=DCF, tx='Satış', credit=0.0, debt=0.0):
    return {'id': tid, 'transactionDate': 1791994155555, 'transactionType': tx, 'description': tx,
            'receiptId': 644841793, 'credit': credit, 'debt': debt, 'commissionRate': 21.5,
            'commissionAmount': commission, 'commissionInvoiceSerialNumber': invoice,
            'sellerRevenue': (credit or debt) - commission, 'orderNumber': order, 'affiliate': 'TRENDYOLTR'}


@tagged('post_install', '-at_install', 'trendyol_integration')
class TestCommissionInvoice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Settlement = cls.env['trendyol.settlement']
        cls.store = cls.env['trendyol.store'].create({
            'name': 'TY Komisyon', 'api_key': 'k', 'api_secret': 's', 'seller_id': '995',
        })

    def _load(self, items, source):
        for item in items:
            self.Settlement._process_settlement_item(item, self.store, source)

    def _get(self, tid, source):
        return self.Settlement.search([('store_id', '=', self.store.id), ('trendyol_id', '=', tid),
                                       ('source', '=', source)])

    def test_rows_linked_by_trendyol_number(self):
        """Satırlar Trendyol'un verdiği fatura no ile bağlanır; toplam tutarsa fatura doğrulanır,
        faturanın hakediş etkisi 0'dır, kesinti faturasına komisyon fatura no yazılmaz."""
        self._load([_sale('s1', '11682355754', 1612.29, credit=7499.0),
                    _sale('s2', '11700435283', 859.79, credit=3999.0),
                    _sale('s3', '111', 500.0, credit=2000.0, invoice='DCF_BASKA')], 'settlements')
        self._load([DCF_INVOICE, DDF_PLATFORM], 'otherfinancials')
        inv = self._get(DCF, 'otherfinancials')
        ddf = self._get('DDF2026023484617', 'otherfinancials')
        self.assertEqual(inv.transaction_type, 'commission')
        self.assertEqual(inv.commission_invoice_no, DCF)
        self.assertEqual(inv.signed_seller_revenue, 0.0)
        self.assertFalse(ddf.commission_invoice_no)

        res = self.Settlement._allocate_commission_invoices(self.store)
        self.assertEqual(res['allocated'], 1)
        self.assertEqual(inv.allocation_state, 'allocated')
        self.assertIn('2 sipariş', inv.allocation_note)
        rows = self.Settlement.search(inv.action_view_commission_rows()['domain'])
        self.assertEqual(set(rows.mapped('trendyol_id')), {'s1', 's2'})

    def test_return_reduces_and_missing_rows_warn(self):
        """İade komisyonu düşer; bağlı satırlar faturayı tutmuyorsa uyarı, sonra tamamlanınca doğrulanır."""
        self._load([_sale('s1', 'A', 1612.29, credit=7499.0)], 'settlements')
        self._load([DCF_INVOICE], 'otherfinancials')
        inv = self._get(DCF, 'otherfinancials')
        self.Settlement._allocate_commission_invoices(self.store)
        self.assertEqual(inv.allocation_state, 'warning')
        self.assertIn('fark', inv.allocation_note)

        # Eksik satış + iade gelir: 1612,29 + 1059,79 − 200 = 2472,08
        self._load([_sale('s2', 'B', 1059.79, credit=4999.0),
                    _sale('r1', 'A', 200.0, tx='İade', debt=1000.0)], 'settlements')
        self.Settlement._allocate_commission_invoices(self.store)
        self.assertEqual(inv.allocation_state, 'allocated')

    def test_number_filled_later_is_updated(self):
        """Fatura no satıştan sonra dolar: yeniden çekilen satır güncellenir, boş gelince silinmez."""
        self._load([_sale('s1', 'A', 100.0, credit=500.0, invoice=None)], 'settlements')
        row = self._get('s1', 'settlements')
        self.assertFalse(row.commission_invoice_no)
        self._load([_sale('s1', 'A', 100.0, credit=500.0)], 'settlements')
        self.assertEqual(row.commission_invoice_no, DCF)
        self._load([_sale('s1', 'A', 100.0, credit=500.0, invoice=None)], 'settlements')
        self.assertEqual(row.commission_invoice_no, DCF)

    def test_no_rows_is_unmatched(self):
        self._load([DCF_INVOICE], 'otherfinancials')
        self.Settlement._allocate_commission_invoices(self.store)
        self.assertEqual(self._get(DCF, 'otherfinancials').allocation_state, 'unmatched')
