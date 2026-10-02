from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

PO = '76962514'
AFF_AZ = 'TRENDYOLAZJV'
PKG_A, ORDER_A = '4017336046', '11435766946'
PKG_B, ORDER_B = '4008520872', '11425269883'


class FakeApi:
    """Trendyol finans servisinin paymentOrderId sorgularını taklit eder (gerçek kabul verisi)."""

    def __init__(self, invoices, sales, delivery_types=None):
        self.invoices = invoices
        self.sales = sales
        self.delivery_types = delivery_types or {}  # orderNumber → fastDeliveryType
        self.calls = []

    def get_orders(self, order_number=None, **kw):
        self.calls.append(('orders', order_number))
        ftype = self.delivery_types.get(order_number)
        content = [{'orderNumber': order_number, 'fastDeliveryType': ftype}] if ftype else []
        return self._page(content)

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


def _sale(pkg, order, tx_type, credit=0.0, debt=0.0, po=PO, affiliate=AFF_AZ, country='Azerbaycan'):
    return {'id': f"{tx_type}-{pkg}", 'transactionType': tx_type, 'credit': credit, 'debt': debt,
            'orderNumber': order, 'shipmentPackageId': int(pkg), 'paymentOrderId': int(po),
            'affiliate': affiliate, 'country': country}


# Ödeme 77611914 (TR): 13 paket, Platform 164,27 = 12 × 13,19 + 1 × 5,99 (SameDayShipping)
PO_TR = '77611914'
TR_PACKAGES = [  # (paket, sipariş, satış, indirim)
    ('4087614599', '11518825608', 1399.99, 28.00),  # SameDayShipping
    ('4090439801', '11522040843', 1999.00, 139.93), ('4089858921', '11521475818', 2999.00, 209.98),
    ('4085035735', '11515806268', 2999.00, 159.98), ('4086273490', '11517219274', 3499.00, 219.98),
    ('4085344646', '11516101199', 3999.90, 180.00), ('4089947661', '11521566627', 4599.00, 677.68),
    ('4087339814', '11518549601', 5599.00, 795.68), ('4092552013', '11524630676', 5200.00, 364.00),
    ('4088340637', '11519589334', 5999.00, 842.88), ('4137817499', '11580008065', 6750.00, 802.58),
    ('4134576789', '11576285563', 8599.99, 1022.54), ('4086808925', '11517968034', 12499.00, 1609.88),
]

# Ödeme 59738577 (mikro ihracat, TRENDYOLTR): gönderi başı platform faturası, ülke başı uluslararası fatura
PO_MICRO = '59738577'
MICRO_PACKAGES = [  # (paket, sipariş, ülke, satış, indirim)
    ('3980404368', '11390665663', 'Romanya', 2399.99, 196.00),
    ('3954449050', '11360259235', 'Romanya', 1299.99, 100.00),
    ('3919434107', '11319535322', 'Romanya', 1251.90, 100.00),
    ('3917490614', '11317270217', 'Yunanistan', 2407.04, 200.00),
]
MICRO_INVOICES = [('DDF2026017137385', 'Uluslararası Hizmet Bedeli', 273.35),
                  ('DDF2026017018272', 'Uluslararası Hizmet Bedeli', 132.42),
                  ('DDF2026016507091', 'Platform Hizmet Bedeli', 13.19),
                  ('DDF2026015780073', 'Platform Hizmet Bedeli', 13.19),
                  ('DDF2026014655353', 'Platform Hizmet Bedeli', 13.19),
                  ('DDF2026014644948', 'Platform Hizmet Bedeli', 13.19)]


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

    # ── Gruplu dağıtım: Bugün Kargoda (TR) ve mikro ihracat ────────────────

    def _row(self, pkg, tx_type, po):
        return self.Settlement.search([('store_id', '=', self.store.id), ('source', '=', 'fee_allocation'),
                                       ('shipment_package_id', '=', pkg), ('transaction_type', '=', tx_type),
                                       ('payment_order_id', '=', po)])

    def test_tr_same_day_platform_fee(self):
        """77611914: 164,27 = 12 × 13,19 + 5,99 — SameDayShipping paketi siparişin ham JSON'undan bilinir."""
        same_day_pkg, same_day_order = TR_PACKAGES[0][:2]
        order = self.env['trendyol.order'].create({
            'store_id': self.store.id, 'trendyol_order_number': same_day_order,
            'shipment_package_id': same_day_pkg, 'raw_data': '{"fastDeliveryType": "SameDayShipping"}'})
        sales = []
        for pkg, on, sale, disc in TR_PACKAGES:
            sales += [_sale(pkg, on, 'Satış', credit=sale, po=PO_TR, affiliate='TRENDYOLTR', country='Türkiye'),
                      _sale(pkg, on, 'İndirim', debt=disc, po=PO_TR, affiliate='TRENDYOLTR', country='Türkiye')]
        api = FakeApi([_invoice('DDF2026021976654', 'Platform Hizmet Bedeli', 164.27, po=PO_TR,
                                affiliate='TRENDYOLTR')], sales)
        res = self.Settlement._allocate_service_fees(api, self.store, payment_order_ids={PO_TR})
        self.assertEqual((res['allocated'], res['warnings'], res['rows']), (1, 0, 13))
        self.assertAlmostEqual(self._row(same_day_pkg, 'platform_fee', PO_TR).debt, 5.99, places=2)
        for pkg, *_ in TR_PACKAGES[1:]:
            self.assertAlmostEqual(self._row(pkg, 'platform_fee', PO_TR).debt, 13.19, places=2)
        self.assertEqual(order.fast_delivery_type, 'SameDayShipping')  # ham veriden alana yazıldı

    def test_same_day_type_from_order_service(self):
        """Odoo'da siparişi olmayan paketin teslimat tipi sipariş servisinden sorgulanır."""
        same_day_pkg, same_day_order = TR_PACKAGES[0][:2]
        sales = []
        for pkg, on, sale, disc in TR_PACKAGES:
            sales.append(_sale(pkg, on, 'Satış', credit=sale, po=PO_TR, affiliate='TRENDYOLTR'))
        api = FakeApi([_invoice('DDF2026021976654', 'Platform Hizmet Bedeli', 164.27, po=PO_TR,
                                affiliate='TRENDYOLTR')], sales, delivery_types={same_day_order: 'SameDayShipping'})
        res = self.Settlement._allocate_service_fees(api, self.store, payment_order_ids={PO_TR})
        self.assertEqual(res['allocated'], 1)
        self.assertIn(('orders', same_day_order), api.calls)
        self.assertAlmostEqual(self._row(same_day_pkg, 'platform_fee', PO_TR).debt, 5.99, places=2)

    def _micro_api(self, invoices=MICRO_INVOICES):
        sales = []
        for pkg, on, country, sale, disc in MICRO_PACKAGES:
            sales += [_sale(pkg, on, 'Satış', credit=sale, po=PO_MICRO, affiliate='TRENDYOLTR', country=country),
                      _sale(pkg, on, 'İndirim', debt=disc, po=PO_MICRO, affiliate='TRENDYOLTR', country=country)]
        return FakeApi([_invoice(i, t, amt, po=PO_MICRO, affiliate='TRENDYOLTR') for i, t, amt in invoices], sales)

    def test_micro_export_per_shipment_and_country_invoices(self):
        """59738577: 4 ayrı platform faturası (gönderi başı) + ülke başı uluslararası fatura."""
        res = self.Settlement._allocate_service_fees(self._micro_api(), self.store, payment_order_ids={PO_MICRO})
        self.assertEqual((res['allocated'], res['warnings'], res['unmatched']), (6, 0, 0))
        expected_intl = {'3980404368': 132.24, '3954449050': 72.00, '3919434107': 69.11, '3917490614': 132.42}
        for pkg, amount in expected_intl.items():
            row = self._row(pkg, 'international_fee', PO_MICRO)
            self.assertAlmostEqual(row.debt, amount, places=2)
            self.assertAlmostEqual(self._row(pkg, 'platform_fee', PO_MICRO).debt, 13.19, places=2)
        # Yunanistan paketi yalnız Yunanistan faturasından pay alır
        self.assertEqual(self._row('3917490614', 'international_fee', PO_MICRO).receipt_id, 'DDF2026017018272')
        self.assertEqual(self._row('3980404368', 'international_fee', PO_MICRO).receipt_id, 'DDF2026017137385')

    def test_new_invoice_recomputes_group(self):
        """Gönderi başı faturaların biri henüz gelmemişse grup tutmaz (uyarı); gelince grup baştan dağıtılır."""
        partial = [inv for inv in MICRO_INVOICES if inv[0] != 'DDF2026014644948']
        res = self.Settlement._allocate_service_fees(self._micro_api(partial), self.store,
                                                     payment_order_ids={PO_MICRO})
        self.assertEqual(res['warnings'], 3)  # 3 × 13,19 = 39,57 dört pakete tutmaz
        res = self.Settlement._allocate_service_fees(self._micro_api(), self.store, payment_order_ids={PO_MICRO})
        self.assertEqual(res['warnings'], 0)
        platform = self.Settlement.search([('store_id', '=', self.store.id), ('source', '=', 'otherfinancials'),
                                           ('payment_order_id', '=', PO_MICRO),
                                           ('transaction_type', '=', 'platform_fee')])
        self.assertEqual(len(platform), 4)
        self.assertEqual(set(platform.mapped('allocation_state')), {'allocated'})
        rows = self.Settlement.search([('store_id', '=', self.store.id), ('source', '=', 'fee_allocation'),
                                       ('payment_order_id', '=', PO_MICRO), ('transaction_type', '=', 'platform_fee')])
        self.assertEqual(len(rows), 4)
        self.assertAlmostEqual(sum(rows.mapped('debt')), 52.76, places=2)
