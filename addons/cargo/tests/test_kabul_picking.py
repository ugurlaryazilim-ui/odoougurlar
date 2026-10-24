# -*- coding: utf-8 -*-
"""KABUL: transfer (stock.picking) entegrasyonu (KK-5 picking, KK-14, KK-15, KK-33).

Yesile donecegi gorev: G6 (G1-G4'e bagli). Pazaryeri modullerinin cogu test DB'sinde kurulu degildir:
kurulu olmayan pazaryeri alanlari atlanir (subTest + skip). Shopify testi shopify kurulu kopyada elle/Mod 2'de kosulur.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from .kabul_taban import CargoKabulCase

MARKETPLACE_FIELDS = ('trendyol_order_id', 'hb_order_id', 'amazon_order_id', 'pazarama_order_id', 'n11_order_id',
                      'flo_order_id', 'idefix_order_id', 'pttavm_order_id', 'shopify_order_id')


class PickingBase(CargoKabulCase):
    REQUIRES_MODELS = ('cargo.shipment', 'cargo.area')

    @classmethod
    def _kur(cls):
        super()._kur()
        cls.product = cls.env['product.product'].create({'name': 'KK Urun', 'type': 'consu', 'list_price': 100.0})
        # NEDEN: Odoo 19 res.partner'da 'mobile' alani yok; telefon yalniz 'phone' alanindan gelir.
        cls.cust = cls.make_partner('Ayse Musteri', phone='05321234567')
        cls.cust_landline = cls.make_partner('Fatma Telefon', phone='03129998877')

    @classmethod
    def make_partner(cls, name, phone=False, **kw):
        vals = {'name': name, 'street': 'Ataturk Mah. Gul Sk. No:5', 'street2': 'D:3', 'city': 'Cankaya',
                'state_id': cls.st('06').id, 'country_id': cls.tr.id, 'zip': '06100',
                'phone': phone, 'email': 'musteri@example.com'}
        vals.update(kw)
        return cls.env['res.partner'].create(vals)

    def make_picking(self, partner=None, **order_over):
        order = self.env['sale.order'].create(dict({
            'partner_id': (partner or self.cust).id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 2.0})],
        }, **order_over))
        order.action_confirm()
        picking = order.picking_ids[:1]
        self.assertTrue(picking, 'on kosul: onayli satis siparisi giden transfer uretmeli')
        picking.partner_id = (partner or self.cust).id
        return picking

    def open_action(self, picking, user=None):
        return picking.with_user(user or self.user).action_cargo_shipment_open()

    def shipment_of(self, picking):
        return picking.sudo().cargo_shipment_ids.sorted('id')[-1:]


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulTransferGonderi(PickingBase):

    def test_teslimat_adresinden_taslak(self):
        """KK-14."""
        picking = self.make_picking()
        action = self.open_action(picking)
        shipment = self.shipment_of(picking)
        self.assertEqual(len(shipment), 1)
        self.assertEqual(action.get('res_model'), 'cargo.shipment')
        self.assertEqual(action.get('res_id'), shipment.id)
        self.assertEqual(shipment.state, 'draft')
        self.assertEqual(shipment.recipient_name, 'Ayse Musteri')
        self.assertEqual(shipment.recipient_phone, '05321234567')
        self.assertIn('Ataturk Mah. Gul Sk. No:5', shipment.recipient_street)
        self.assertIn('D:3', shipment.recipient_street)
        self.assertEqual(shipment.recipient_state_id, self.st('06'))
        self.assertEqual(shipment.recipient_district, 'Cankaya')
        self.assertEqual(shipment.area_id, self.area_cankaya)
        self.assertEqual(shipment.origin_ref, picking.name)
        self.assertEqual(shipment.carrier_id, self.carrier)
        self.assertEqual(shipment.picking_id, picking)
        self.assertEqual(picking.sudo().cargo_shipment_ids, shipment)
        self.assertFalse(picking.sudo().cargo_marketplace_name, 'pazaryeri siparisi degil')

    def test_ortagin_telefonu_tasinir(self):
        picking = self.make_picking(partner=self.cust_landline)
        self.open_action(picking)
        self.assertEqual(self.shipment_of(picking).recipient_phone, '03129998877')

    def test_acik_gonderi_varsa_ayni_gonderi_acilir(self):
        picking = self.make_picking()
        first = self.open_action(picking)
        second = self.open_action(picking)
        self.assertEqual(second.get('res_id'), first.get('res_id'))
        self.assertEqual(len(picking.sudo().cargo_shipment_ids), 1)

    def test_basarisiz_veya_iptal_sonrasi_yeni_taslak(self):
        picking = self.make_picking()
        self.open_action(picking)
        old = self.shipment_of(picking)
        for state in ('failed', 'cancelled'):
            with self.subTest(state=state):
                old.sudo().write({'state': state})
                action = self.open_action(picking)
                new = self.env['cargo.shipment'].sudo().browse(action['res_id'])
                self.assertNotEqual(new, old)
                self.assertEqual(new.state, 'draft')
                self.assertEqual(new.origin_ref, picking.name)
                old = new

    def test_varsayilan_firma_yoksa_hata(self):
        """KK-5."""
        self.company.cargo_default_carrier_id = False
        picking = self.make_picking()
        self.assert_user_error(lambda: self.open_action(picking), r'Varsayılan kargo firması ayarlı değil')
        self.assertFalse(picking.sudo().cargo_shipment_ids)

    def test_giden_olmayan_veya_iptal_transfer(self):
        picking = self.make_picking()
        picking.sudo().action_cancel()
        self.assert_user_error(lambda: self.open_action(picking))
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        incoming = self.env['stock.picking'].create({
            'picking_type_id': warehouse.in_type_id.id, 'partner_id': self.cust.id,
            'location_id': warehouse.in_type_id.default_location_src_id.id or self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': warehouse.in_type_id.default_location_dest_id.id or warehouse.lot_stock_id.id})
        self.assert_user_error(lambda: self.open_action(incoming))
        self.assertFalse(self.env['cargo.shipment'].sudo().search([('picking_id', 'in', (picking | incoming).ids)]))

    def test_yetkisiz_kullanici(self):
        picking = self.make_picking()
        with self.assertRaises(UserError):
            picking.with_user(self.plain).action_cargo_shipment_open()
        self.assertFalse(picking.sudo().cargo_shipment_ids)

    def test_gorunumde_dugmeler_ve_onay_metni(self):
        """KK-15 (otomatik kisim): formda iki dugme ve pazaryeri onay metni bulunur; diyalog davranisi elle dogrulanir."""
        arch = self.env['stock.picking'].get_view(view_type='form')['arch']
        self.assertGreaterEqual(arch.count('action_cargo_shipment_open'), 2, 'normal + pazaryeri dugmesi')
        self.assertRegex(arch, r'Bu sipariş pazaryeri kargosuyla gider\. Yine de .*gönderisi açılsın mı\?')


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulTransferTakip(PickingBase):

    def test_canli_gonderide_picking_takip_yazilir(self):
        """KK-14: created olunca picking'e carrier_id ve carrier_tracking_ref yazilir (canli ortam)."""
        self.carrier.prod_environment = True
        picking = self.make_picking()
        self.open_action(picking)
        shipment = self.shipment_of(picking)
        shipment.with_user(self.user).action_send()
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(picking.carrier_tracking_ref, shipment.tracking_ref)
        self.assertEqual(picking.carrier_id, self.carrier)

    def test_test_modu_picking_a_yazilmaz(self):
        self.assertFalse(self.carrier.prod_environment)
        picking = self.make_picking()
        self.open_action(picking)
        shipment = self.shipment_of(picking)
        shipment.with_user(self.user).action_send()
        self.assertEqual(shipment.state, 'created')
        self.assertTrue(shipment.test_mode)
        self.assertFalse(picking.carrier_tracking_ref, 'test gonderisi picking takibini kirletmemeli')
        self.assertFalse(picking.carrier_id)

    def test_pazaryeri_siparisinde_picking_a_yazilmaz(self):
        """KK-15 zemini + S-6: pazaryeri/Shopify siparisinde takip no picking'e yazilmaz (pazaryeri kendi yazar)."""
        self.carrier.prod_environment = True
        Sale = self.env['sale.order']
        seen = 0
        for fname in MARKETPLACE_FIELDS:
            if fname not in Sale._fields:
                continue
            with self.subTest(alan=fname):
                comodel = Sale._fields[fname].comodel_name
                record, error = self.try_call(lambda: self.env[comodel].create({}))
                if error or not record:
                    self.skipTest('%s kaydi bos degerlerle olusturulamadi' % comodel)
                picking = self.make_picking(**{fname: record.id})
                self.assertTrue(picking.sudo().cargo_marketplace_name, '%s pazaryeri olarak taninmali' % fname)
                self.open_action(picking)
                shipment = self.shipment_of(picking)
                shipment.with_user(self.user).action_send()
                self.assertEqual(shipment.state, 'created')
                self.assertFalse(picking.carrier_tracking_ref, '%s: takip no picking\'e yazilmamali' % fname)
                self.assertFalse(picking.carrier_id)
                seen += 1
        if not seen:
            self.skipTest('hicbir pazaryeri modulu kurulu degil')

    def test_trendyol_pazaryeri_adi(self):
        if 'trendyol_order_id' not in self.env['sale.order']._fields:
            self.skipTest('trendyol_integration kurulu degil')
        order = self.env['trendyol.order'].create({})
        picking = self.make_picking(trendyol_order_id=order.id)
        self.assertIn('rendyol', picking.sudo().cargo_marketplace_name or '')

    def test_iptalde_picking_temizlenir(self):
        self.carrier.prod_environment = True
        picking = self.make_picking()
        self.open_action(picking)
        shipment = self.shipment_of(picking)
        shipment.with_user(self.user).action_send()
        self.assertTrue(picking.carrier_tracking_ref)
        shipment.with_user(self.user).action_cancel()
        self.assertEqual(shipment.state, 'cancelled')
        self.assertFalse(picking.carrier_tracking_ref)

    def test_iptalde_baskasinin_takibi_silinmez(self):
        """Picking'teki takip no bizim degilse (baska entegrasyon yazdi) iptal onu silmez."""
        self.carrier.prod_environment = True
        picking = self.make_picking()
        self.open_action(picking)
        shipment = self.shipment_of(picking)
        shipment.with_user(self.user).action_send()
        picking.carrier_tracking_ref = 'BASKA-TAKIP-1'
        shipment.with_user(self.user).action_cancel()
        self.assertEqual(picking.carrier_tracking_ref, 'BASKA-TAKIP-1')

    def test_iptal_sonrasi_yeni_gonderi_takibi_yazar(self):
        self.carrier.prod_environment = True
        picking = self.make_picking()
        self.open_action(picking)
        first = self.shipment_of(picking)
        first.with_user(self.user).action_send()
        first.with_user(self.user).action_cancel()
        action = self.open_action(picking)
        second = self.env['cargo.shipment'].sudo().browse(action['res_id'])
        self.assertNotEqual(second, first)
        second.with_user(self.user).action_send()
        self.assertEqual(picking.carrier_tracking_ref, second.tracking_ref)


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulTransferOnayiGonderi(PickingBase):

    def test_validate_otomatik_gonderi_acmaz(self):
        """KK-33: yonetilen firmali transferin dogrulanmasi saglayiciyi cagirmaz, send_to_shipper tetiklenmez."""
        picking = self.make_picking()
        picking.sudo().write({'carrier_id': self.carrier.id})
        picking.picking_type_id.sudo().print_label = True
        for move in picking.move_ids:
            move.write({'quantity': move.product_uom_qty, 'picked': True})
        with patch.object(type(picking), 'send_to_shipper') as send_to_shipper:
            picking.with_context(skip_backorder=True, skip_sms=True, skip_immediate=True).button_validate()
        self.assertEqual(picking.state, 'done', 'on kosul: transfer dogrulanabilmeli')
        send_to_shipper.assert_not_called()
        self.no_provider_calls('transfer onayi kargo saglayicisini cagirmamali')
        self.assertFalse(picking.carrier_tracking_ref)
        self.assertFalse(picking.sudo().cargo_shipment_ids, 'otomatik gonderi acilmamali')
