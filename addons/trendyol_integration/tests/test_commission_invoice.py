from datetime import datetime

from odoo.tests import TransactionCase, tagged

DCF = 'DCF2026004839667'


@tagged('post_install', '-at_install', 'trendyol_integration')
class TestCommissionInvoice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Settlement = cls.env['trendyol.settlement']
        cls.store = cls.env['trendyol.store'].create({
            'name': 'TY Komisyon', 'api_key': 'k', 'api_secret': 's', 'seller_id': '995',
        })
        cls.n = 0

    def _row(self, when, commission, tx='sale', affiliate='TRENDYOLTR', order='100'):
        """Settlements kaydı; when: UTC. Satış alacak (+komisyon), iade borç (−komisyon)."""
        type(self).n += 1
        credit, debt = (1000.0, 0.0) if tx == 'sale' else (0.0, 1000.0)
        return self.Settlement.create({
            'trendyol_id': f"r{self.n}", 'store_id': self.store.id, 'source': 'settlements',
            'transaction_type': tx, 'transaction_type_raw': tx, 'credit': credit, 'debt': debt,
            'commission_amount': commission, 'seller_revenue': 1000.0 - commission,
            'transaction_date': when, 'order_number': order, 'affiliate': affiliate,
        })

    def _invoice(self, debt, desc='08 Ekim - 14 Ekim arası Trendyol hakediş tutarı'):
        return self.Settlement.create({
            'trendyol_id': DCF, 'commission_invoice_no': DCF, 'store_id': self.store.id,
            'source': 'otherfinancials', 'transaction_type': 'commission', 'transaction_type_raw': 'Komisyon',
            'description': desc, 'debt': debt, 'transaction_date': datetime(2026, 10, 14, 0, 0),
        })

    def test_period_parsed_from_description(self):
        inv = self._invoice(10.0)
        self.assertEqual(tuple(str(d) for d in inv._commission_invoice_period()), ('2026-10-08', '2026-10-14'))
        inv.description = 'Komisyon'
        self.assertEqual(tuple(str(d) for d in inv._commission_invoice_period()), ('2026-10-08', '2026-10-14'))
        inv.write({'description': '25 Aralık - 31 Aralık arası', 'transaction_date': datetime(2027, 1, 1)})
        self.assertEqual(tuple(str(d) for d in inv._commission_invoice_period()), ('2026-12-25', '2026-12-31'))

    def test_allocates_period_rows(self):
        """Dönemdeki komisyonlar faturayı tutuyorsa kayıtlara fatura no yazılır; dönem dışı ve AZ
        kayıtlar karışmaz; faturanın hakediş etkisi 0'dır."""
        a = self._row(datetime(2026, 10, 7, 21, 30), 150.0, order='A')   # 08.10 00:30 TR → dahil
        b = self._row(datetime(2026, 10, 14, 20, 0), 100.0, order='B')   # 14.10 23:00 TR → dahil
        r = self._row(datetime(2026, 10, 10, 9, 0), 20.0, tx='return', order='A')  # iade: −20
        out = self._row(datetime(2026, 10, 14, 21, 30), 999.0, order='C')  # 15.10 00:30 TR → hariç
        az = self._row(datetime(2026, 10, 9, 9, 0), 55.0, affiliate='TRENDYOLAZJV', order='D')
        inv = self._invoice(230.0)
        self.assertEqual(inv.signed_seller_revenue, 0.0)

        res = self.Settlement._allocate_commission_invoices(self.store)
        self.assertEqual(res['allocated'], 1)
        self.assertEqual(inv.allocation_state, 'allocated')
        self.assertEqual((a | b | r).mapped('commission_invoice_no'), [DCF] * 3)
        self.assertFalse(out.commission_invoice_no)
        self.assertFalse(az.commission_invoice_no)
        self.assertIn('2 sipariş', inv.allocation_note)

        action = inv.action_view_commission_rows()
        self.assertEqual(self.Settlement.search(action['domain']), a | b | r)

    def test_mismatch_is_warning_and_not_written(self):
        a = self._row(datetime(2026, 10, 9, 9, 0), 150.0)
        inv = self._invoice(500.0)
        self.Settlement._allocate_commission_invoices(self.store)
        self.assertEqual(inv.allocation_state, 'warning')
        self.assertFalse(a.commission_invoice_no)
        self.assertIn('fark', inv.allocation_note)
        # Dönemdeki kayıtlar yine görülebilir
        self.assertEqual(self.Settlement.search(inv.action_view_commission_rows()['domain']), a)

    def test_no_rows_is_unmatched(self):
        inv = self._invoice(100.0)
        self.Settlement._allocate_commission_invoices(self.store)
        self.assertEqual(inv.allocation_state, 'unmatched')
