import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


def _money(amount):
    return {'CurrencyCode': 'TRY', 'Amount': str(amount)}


@tagged('post_install', '-at_install', 'amazon_integration')
class TestAmazonSync(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        # Onayda Nebim'e gönderim yapılmasın
        ICP.set_param('odoougurlar.nebim_sync_customer_enabled', 'False')
        ICP.set_param('odoougurlar.nebim_sync_order_enabled', 'False')
        cls.Store = cls.env['amazon.store']
        cls.store = cls.Store.create({
            'name': 'Amazon Test',
            'lwa_client_id': 'x',
            'lwa_client_secret': 'y',
            'default_warehouse_id': cls.env['stock.warehouse'].search([], limit=1).id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Amazon Test Ürün',
            'default_code': 'AMZ-TEST-SKU-1',
            'barcode': 'AMZTESTSKU1',
            'type': 'consu',
            'list_price': 100,
        })

    def _order_data(self, order_id='405-0000000-0000001', status='Unshipped', total=900.0):
        return {
            'AmazonOrderId': order_id,
            'OrderStatus': status,
            'PurchaseDate': '2026-09-28T10:00:00Z',
            'FulfillmentChannel': 'MFN',
            'OrderTotal': _money(total),
        }

    def _items(self, price=1000.0, promotion=100.0, tax=0.0, qty=1):
        return [{
            'OrderItemId': '111',
            'SellerSKU': 'AMZTESTSKU1',
            'ASIN': 'B000TEST',
            'Title': 'Amazon Test Ürün',
            'QuantityOrdered': qty,
            'ItemPrice': _money(price),
            'ItemTax': _money(tax),
            'PromotionDiscount': _money(promotion),
        }]

    def _run(self, order_data, items, address=None, buyer=None, force_update=False):
        cls = type(self.store)
        address = address if address is not None else {
            'Name': 'Ayşe Yılmaz', 'AddressLine1': 'Atatürk Cad. No:1',
            'City': 'İzmir', 'Municipality': 'Karşıyaka', 'CountryCode': 'TR', 'Phone': '5550000000',
        }
        buyer = buyer if buyer is not None else {'BuyerEmail': 'abc123@marketplace.amazon.com.tr', 'BuyerName': 'Yılmaz'}
        with patch.object(cls, '_get_restricted_data_token', return_value='rdt'), \
                patch.object(cls, '_fetch_order_address', return_value=dict(address)), \
                patch.object(cls, '_fetch_order_buyer_info', return_value=dict(buyer)), \
                patch.object(cls, '_fetch_order_items', return_value=items), \
                patch.object(cls, '_fetch_easyship_tracking', return_value=''), \
                patch.object(cls, '_fetch_catalog_ean', return_value=''):
            return self.store._process_single_order(order_data, None, None, 'https://x', force_update=force_update)

    def _sale_order(self, order_id='405-0000000-0000001'):
        return self.env['sale.order'].search([('client_order_ref', '=', order_id)], limit=1)

    # ─── Satır hazırlama ───

    def test_promotion_reduces_line_price_and_tax_field_is_valid(self):
        """PromotionDiscount düşülür; KDV dahil vergi varsa tax_ids alanına yazılır (tax_id ValueError vermez)."""
        tax = self.env['account.tax'].create({
            'name': 'KDV %20 Dahil (test)', 'amount': 20, 'type_tax_use': 'sale',
            'price_include_override': 'tax_included',
        })
        self.product.taxes_id = tax
        self._run(self._order_data(), self._items(price=1000.0, promotion=100.0))
        so = self._sale_order()
        self.assertTrue(so, "Sipariş oluşmalı")
        self.assertEqual(so.state, 'sale')
        line = so.order_line
        self.assertEqual(line.product_id, self.product)
        self.assertAlmostEqual(line.price_unit, 900.0, places=2)
        self.assertTrue(line.tax_ids.price_include)
        self.assertEqual(line.tax_ids.amount, 20)
        self.assertAlmostEqual(so.amount_total, 900.0, places=2)

    # ─── Onaylı sipariş: satır silinmez, döngü yok ───

    def test_confirmed_order_amount_mismatch_does_not_touch_lines(self):
        self._run(self._order_data(), self._items())
        so = self._sale_order()
        self.assertEqual(so.state, 'sale')
        lines_before = so.order_line
        amazon_order = so.amazon_order_id
        # Tutar farklı gelse bile onaylı siparişte işlem yapılmaz, hata dönmez
        res = self._run(self._order_data(total=12345.0), self._items(price=5000.0, promotion=0))
        self.assertEqual(res[2], 0, "Hata sayılmamalı")
        self.assertEqual(so.order_line, lines_before)
        self.assertEqual(so.amazon_order_id, amazon_order)

    # ─── İptal ───

    def test_cancel_unshipped_order(self):
        self._run(self._order_data(), self._items())
        so = self._sale_order()
        self.assertEqual(so.state, 'sale')
        partners_before = self.env['res.partner'].search_count([('name', '=', 'Amazon Müşterisi')])
        # İptalde Amazon PII vermez → boş partner oluşturulmamalı
        self._run(self._order_data(status='Canceled'), self._items(), address={}, buyer={})
        self.assertEqual(so.state, 'cancel')
        self.assertEqual(so.amazon_order_id.order_status, 'Canceled')
        self.assertEqual(self.env['res.partner'].search_count([('name', '=', 'Amazon Müşterisi')]), partners_before)
        self.assertNotEqual(so.partner_id.name, 'Amazon Müşterisi')

    def test_cancel_blocked_when_shipped(self):
        self._run(self._order_data(), self._items())
        so = self._sale_order()
        picking = so.picking_ids[:1]
        self.assertTrue(picking)
        picking.move_ids.quantity = 1
        picking.move_ids.picked = True
        picking.with_context(skip_backorder=True, skip_sms=True)._action_done()
        self.assertEqual(picking.state, 'done')
        self._run(self._order_data(status='Canceled'), self._items(), address={}, buyer={})
        self.assertEqual(so.state, 'sale')
        self.assertIn('sevk edildiği', so.amazon_order_id.error_message)
        # İkinci çalıştırmada aynı uyarı tekrar yazılmaz
        msg_count = len(so.message_ids)
        self._run(self._order_data(status='Canceled'), self._items(), address={}, buyer={})
        self.assertEqual(len(so.message_ids), msg_count)

    # ─── Müşteri eşleştirme ───

    def test_partner_not_matched_by_name_only(self):
        other = self.env['res.partner'].create({
            'name': 'Ayşe Yılmaz', 'city': 'Bornova', 'street': 'Tedarikçi Sok. 5',
            'email': 'tedarikci@example.com',
        })
        self._run(self._order_data(), self._items())
        so = self._sale_order()
        self.assertNotEqual(so.partner_id, other)
        self.assertEqual(other.street, 'Tedarikçi Sok. 5')
        self.assertEqual(other.email, 'tedarikci@example.com')

    def test_partner_matched_by_amazon_email(self):
        self._run(self._order_data(), self._items())
        first = self._sale_order().partner_id
        self._run(self._order_data(order_id='405-0000000-0000002'), self._items(),
                  address={'Name': 'Ayşe Yılmaz', 'AddressLine1': 'Yeni Adres 7', 'City': 'İzmir',
                           'Municipality': 'Bayraklı', 'CountryCode': 'TR'})
        second = self._sale_order('405-0000000-0000002').partner_id
        self.assertEqual(first, second)
        self.assertEqual(second.street, 'Yeni Adres 7')
        self.assertEqual(second.phone, '5550000000', "Boş gelen telefon mevcut bilgiyi silmemeli")

    # ─── Pending bekleme (mevcut davranış korunur) ───

    def test_pending_order_not_created(self):
        self._run(self._order_data(status='Pending'), self._items(), address={}, buyer={})
        self.assertFalse(self._sale_order())

    # ─── Finans ───

    def test_finance_event_parse_and_upsert(self):
        self._run(self._order_data(), self._items())
        amazon_order = self._sale_order().amazon_order_id

        def m(v):
            return {'CurrencyCode': 'TRY', 'CurrencyAmount': v}
        events = {
            'ShipmentEventList': [{
                'AmazonOrderId': amazon_order.amazon_order_number,
                'PostedDate': '2026-09-30T08:00:00Z',
                'ShipmentItemList': [{
                    'SellerSKU': 'AMZTESTSKU1',
                    'ItemChargeList': [
                        {'ChargeType': 'Principal', 'ChargeAmount': m(750.0)},
                        {'ChargeType': 'Tax', 'ChargeAmount': m(150.0)},
                    ],
                    'ItemFeeList': [
                        {'FeeType': 'Commission', 'FeeAmount': m(-135.0)},
                        {'FeeType': 'FixedClosingFee', 'FeeAmount': m(-5.0)},
                    ],
                    'PromotionList': [{'PromotionAmount': m(-10.0)}],
                }],
            }],
            'RefundEventList': [],
        }
        Event = self.env['amazon.finance.event']
        self.assertEqual(Event._upsert_from_payload(self.store, amazon_order, events), (1, 0))
        self.assertEqual(Event._upsert_from_payload(self.store, amazon_order, events), (0, 1))
        ev = amazon_order.finance_event_ids
        self.assertEqual(len(ev), 1)
        self.assertAlmostEqual(ev.principal, 750.0)
        self.assertAlmostEqual(ev.tax, 150.0)
        self.assertAlmostEqual(ev.commission, -135.0)
        self.assertAlmostEqual(ev.other_fees, -5.0)
        self.assertAlmostEqual(ev.promotion, -10.0)
        self.assertAlmostEqual(ev.net_amount, 750.0)
        self.assertAlmostEqual(amazon_order.net_total, 750.0)
        self.assertAlmostEqual(amazon_order.fee_total, -140.0)

    # ─── Kişisel veri temizliği ───

    def test_pii_cleanup(self):
        self._run(self._order_data(status='Unshipped'), self._items())
        amazon_order = self._sale_order().amazon_order_id
        amazon_order.write({
            'order_status': 'Shipped',
            'order_date': fields.Datetime.now() - timedelta(days=45),
        })
        self.store.cron_amazon_pii_cleanup()
        self.assertFalse(amazon_order.pii_cleaned, "Ayar kapalıyken temizlenmemeli")

        self.store.pii_cleanup_enabled = True
        self.store.cron_amazon_pii_cleanup()
        self.assertTrue(amazon_order.pii_cleaned)
        self.assertFalse(amazon_order.customer_email)
        self.assertFalse(amazon_order.customer_phone)
        self.assertFalse(amazon_order.shipping_address)
        self.assertEqual(amazon_order.customer_name, 'A*** Y***')
        raw = json.loads(amazon_order.raw_payload)
        self.assertNotIn('ShippingAddress', raw)
        self.assertNotIn('BuyerInfo', raw)
        # Satış siparişinin müşterisi (fatura için) korunur
        self.assertEqual(self._sale_order().partner_id.name, 'Ayşe Yılmaz')
