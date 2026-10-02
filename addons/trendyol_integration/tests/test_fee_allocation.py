from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

PO = '76962514'
AFF_AZ = 'TRENDYOLAZJV'
PKG_A, ORDER_A = '4017336046', '11435766946'
PKG_B, ORDER_B = '4008520872', '11425269883'


class FakeApi:
    """Trendyol finans servisinin paymentOrderId sorgularını taklit eder (gerçek kabul verisi)."""

    def __init__(self, invoices, sales):
        self.invoices = invoices
        self.sales = sales
        self.calls = []

    def _page(self, items):
        return {'success': True, 'data': {'content': items, 'totalPages': 1}}

    def get_other_financials(self, transaction_type=None, payment_order_id=None, **kw):
        self.calls.append(('other', transaction_type, payment_order_id))
        return self._page([i for i in self.invoices if str(i['paymentOrderId']) == str(payment_order_id)])

    def get_settlements(self, transaction_types=None, payment_order_id=None, **kw):
        self.calls.append(('settlements', tuple(transaction_types or ()), payment_order_id))
        return self._page([s for s in self.sales if str(s['paymentOrderId']) == str(payment_order_id)])


def _invoice(inv_id, tx_type, debt, po=PO, affiliate=AFF_AZ):
    return {'id': inv_id, 'transactionType': tx_type, 'debt': debt, 'credit': 0.0,
            'orderNumber': None, 'shipmentPackageId': None, 'paymentOrderId': int(po),
            'affiliate': affiliate, 'transactionDate': 1788385121995}


def _sale(pkg, order, tx_type, credit=0.0, debt=0.0, po=PO, affiliate=AFF_AZ):
    return {'id': f"{tx_type}-{pkg}", 'transactionType': tx_type, 'credit': credit, 'debt': debt,
            'orderNumber': order, 'shipmentPackageId': int(pkg), 'paymentOrderId': int(po),
            'affiliate': affiliate}


@tagged('post_install', '-at_install', 'trendyol_integration')
class TestFeeAllocation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Settlement = cls.env['trendyol.settlement']
        cls.store = cls.env['trendyol.store'].create({
            'name': 'TY Test', 'api_key': 'k', 'api_secret': 's', 'seller_id': '999',
        })
        Order = cls.env['trendyol.order']
        cls.order_a = Order.create({'store_id': cls.store.id, 'trendyol_order_number': ORDER_A,
                                    'shipment_package_id': PKG_A})
        cls.order_b = Order.create({'store_id': cls.store.id, 'trendyol_order_number': ORDER_B,
                                    'shipment_package_id': PKG_B})
        paid = fields.Datetime.now() - timedelta(days=3)
        for order, pkg, sale, sale_rev, disc, disc_rev in (
                (cls.order_a, PKG_A, 1799.99, 1520.99, 36.00, 30.42),
                (cls.order_b, PKG_B, 3499.00, 2957.15, 481.46, 406.83)):
            for tx, credit, debt, rev in (('Satış', sale, 0.0, sale_rev), ('İndirim', 0.0, disc, disc_rev)):
                cls.Settlement.create({
                    'trendyol_id': f"{tx}-{pkg}", 'store_id': cls.store.id, 'order_id': order.id,
                    'source': 'settlements', 'transaction_type': 'sale' if tx == 'Satış' else 'discount',
                    'transaction_type_raw': tx, 'credit': credit, 'debt': debt, 'seller_revenue': rev,
                    'order_number': order.trendyol_order_number, 'shipment_package_id': pkg,
                    'payment_order_id': PO, 'payment_date': paid,
                })
        cls.cargo = cls.Settlement.create({
            'trendyol_id': 'cargo_X_1', 'store_id': cls.store.id, 'order_id': cls.order_a.id,
            'source': 'cargo_invoice', 'transaction_type': 'shipping_cargo',
            'transaction_type_raw': 'Gönderi Kargo Bedeli', 'debt': 115.91, 'order_number': ORDER_A,
        })

    def _api(self, intl=286.89, platform=21.98):
        invoices = [_invoice('AZD2026000944475', 'AZ-Uluslararası Hizmet Bedeli', intl),
                    _invoice('AZD2026000953424', 'AZ-Platform Hizmet Bedeli', platform)]
        sales = [_sale(PKG_A, ORDER_A, 'Satış', credit=1799.99), _sale(PKG_A, ORDER_A, 'İndirim', debt=36.00),
                 _sale(PKG_B, ORDER_B, 'Satış', credit=3499.00), _sale(PKG_B, ORDER_B, 'İndirim', debt=481.46)]
        return FakeApi(invoices, sales)

    def _rows(self, order, tx_type):
        return order.settlement_ids.filtered(
            lambda s: s.source == 'fee_allocation' and s.transaction_type == tx_type)

    def test_acceptance_payment_order_76962514(self):
        res = self.Settlement._allocate_service_fees(self._api(), self.store, payment_order_ids={PO})
        self.assertEqual(res['allocated'], 2)
        self.assertEqual(res['rows'], 4)

        self.assertAlmostEqual(self._rows(self.order_a, 'international_fee').debt, 105.84, places=2)
        self.assertAlmostEqual(self._rows(self.order_b, 'international_fee').debt, 181.05, places=2)
        self.assertAlmostEqual(self._rows(self.order_a, 'platform_fee').debt, 10.99, places=2)
        self.assertAlmostEqual(self._rows(self.order_b, 'platform_fee').debt, 10.99, places=2)

        # Kaynak toplu faturalar: dağıtıldı, hakediş etkisi 0 (çift sayım yok)
        bulk = self.Settlement.search([('store_id', '=', self.store.id), ('source', '=', 'otherfinancials')])
        self.assertEqual(len(bulk), 2)
        self.assertEqual(set(bulk.mapped('allocation_state')), {'allocated'})
        self.assertEqual(set(bulk.mapped('signed_seller_revenue')), {0.0})
        self.assertEqual(set(bulk.mapped('affiliate')), {AFF_AZ})
        self.assertEqual(set(bulk.mapped('transaction_type')), {'international_fee', 'platform_fee'})

        # Panel: Satış 1.520,99 + İndirim −30,42 + Kargo −115,91 + Uluslararası −105,84 + Platform −10,99
        self.assertAlmostEqual(self.cargo.signed_seller_revenue, -115.91, places=2)
        self.assertAlmostEqual(sum(self.order_a.settlement_ids.mapped('signed_seller_revenue')), 1257.83, places=2)
        mid = sum(self.order_a.settlement_ids.filtered(
            lambda s: s.transaction_type in ('sale', 'discount', 'international_fee')).mapped('signed_seller_revenue'))
        self.assertAlmostEqual(mid, 1384.73, places=2)

        intl_row = self._rows(self.order_a, 'international_fee')
        self.assertEqual(intl_row.receipt_id, 'AZD2026000944475')
        self.assertEqual(intl_row.payment_order_id, PO)
        self.assertEqual(intl_row.shipment_package_id, PKG_A)
        self.assertIn('dağıtılmış, fatura AZD2026000944475', intl_row.description)

        # Sipariş özeti: Net Sipariş Tutarı = panel
        self.Settlement._update_order_financial_summary(self.store)
        self.assertAlmostEqual(self.order_a.international_fee, 105.84, places=2)
        self.assertAlmostEqual(self.order_a.platform_fee, 10.99, places=2)
        self.assertAlmostEqual(self.order_a.final_net_amount, 1257.83, places=2)

    def test_idempotent_and_amount_update(self):
        S = self.Settlement
        S._allocate_service_fees(self._api(), self.store, payment_order_ids={PO})
        count = S.search_count([('source', '=', 'fee_allocation'), ('store_id', '=', self.store.id)])
        S._allocate_service_fees(self._api(), self.store, payment_order_ids={PO})
        self.assertEqual(S.search_count([('source', '=', 'fee_allocation'), ('store_id', '=', self.store.id)]), count)

        # Fatura güncellendi (tutar değişti) → paylar yeniden hesaplanır, toplam faturaya eşit
        S._allocate_service_fees(self._api(intl=300.00), self.store, payment_order_ids={PO})
        rows = S.search([('source', '=', 'fee_allocation'), ('transaction_type', '=', 'international_fee'),
                         ('store_id', '=', self.store.id)])
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(sum(rows.mapped('debt')), 300.00, places=2)

    def test_platform_not_evenly_divisible_is_warning(self):
        res = self.Settlement._allocate_service_fees(self._api(platform=21.99), self.store, payment_order_ids={PO})
        self.assertEqual(res['warnings'], 1)
        invoice = self.Settlement.search([('trendyol_id', '=', 'AZD2026000953424'),
                                          ('store_id', '=', self.store.id)])
        self.assertEqual(invoice.allocation_state, 'warning')
        self.assertAlmostEqual(invoice.signed_seller_revenue, -21.99, places=2)
        self.assertFalse(self._rows(self.order_a, 'platform_fee'))

    def test_unmatched_when_no_packages(self):
        api = self._api()
        api.sales = []
        res = self.Settlement._allocate_service_fees(api, self.store, payment_order_ids={PO})
        self.assertEqual(res['unmatched'], 2)
        self.assertEqual(set(self.Settlement.search([('source', '=', 'otherfinancials'),
                                                     ('store_id', '=', self.store.id)]).mapped('allocation_state')),
                         {'unmatched'})

    def test_cron_scans_payment_order_without_invoice(self):
        """Satışı ödenmiş ama faturası Odoo'da olmayan ödeme emri cron'da sorgulanır, aynı gün tekrar sorgulanmaz."""
        api = self._api()
        res = self.Settlement._allocate_service_fees(api, self.store)
        self.assertEqual(res['allocated'], 2)
        self.assertIn(('other', 'DeductionInvoices', PO), api.calls)

    def test_split_amount_rounding(self):
        shares = self.Settlement._split_amount(100.0, {'a': 1, 'b': 1, 'c': 1})
        self.assertAlmostEqual(sum(shares.values()), 100.0, places=2)
        self.assertEqual(sorted(shares.values()), [33.33, 33.33, 33.34])
