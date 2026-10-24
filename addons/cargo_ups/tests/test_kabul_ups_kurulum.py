# -*- coding: utf-8 -*-
"""KABUL: cargo_ups kurulumu - KK-1 (firma verisi), KK-2 (sirlar), KK-19b/19c (UPS verisi), KK-32 (sayilar), KK-33.

Yesile donecegi gorev: G8 (cargo_ups iskeleti + veri); KK-33'un UPS kancalari G8/G9.
"""
import os

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .kabul_taban import SECRETS, UpsCase

SECRET_FIELDS = ('ups_tr_customer_number', 'ups_tr_shipper_account', 'ups_tr_username', 'ups_tr_password',
                 'ups_tr_track_username', 'ups_tr_track_password')
SECRET_VALUES = [SECRETS[k] for k in ('customer', 'shipper', 'user', 'password', 'track_user', 'track_password')]
MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul', 'cargo_ups_kabul')
class TestKabulUpsKurulum(UpsCase):

    def data_carrier(self):
        """cargo_ups veri dosyasindan gelen UPS firma kaydi (xmlid'e bagli degil)."""
        data = self.env['ir.model.data'].sudo().search([('module', '=', 'cargo_ups'), ('model', '=', 'delivery.carrier')])
        self.assertTrue(data, 'cargo_ups veri dosyasi bir UPS firma kaydi (delivery.carrier) getirmeli')
        return self.env['delivery.carrier'].browse(data.mapped('res_id')).exists()

    def test_veri_kaydi_varsayilanlari(self):
        """KK-1 / 02-tasarim 1.1, 4.3: test ucu, ODP acik (yalniz nakit), hizmet urunu cekirdek urunu."""
        carriers = self.data_carrier()
        self.assertEqual(len(carriers), 1)
        carrier = carriers.sudo()
        self.assertEqual(carrier.delivery_type, 'ups_tr')
        self.assertFalse(carrier.prod_environment, 'DB kopyasi canliya gitmesin: test ucu varsayilani')
        self.assertEqual(carrier.integration_level, 'rate')
        self.assertTrue(carrier.cargo_cod_enabled, 'S-1: UPS hesabinda ODP acik')
        self.assertTrue(carrier.cargo_cod_allow_cash)
        self.assertFalse(carrier.cargo_cod_allow_card, 'kart kodu canlida dogrulanana kadar kapali')
        self.assertFalse(carrier.cargo_cod_allow_check)
        self.assertEqual(carrier.product_id, self.env.ref('delivery.product_product_delivery'))
        self.assertEqual((carrier.ups_tr_service_level, carrier.ups_tr_payment_type, carrier.ups_tr_package_type),
                         ('3', '2', 'K'))
        self.assertFalse(carrier.ups_tr_sms_to_consignee)
        for field in SECRET_FIELDS:
            self.assertFalse(carrier[field], 'veri kaydinda sir bulunmamali: %s' % field)

    def test_delivery_type_ve_alan_tanimlari(self):
        selection = dict(self.env['delivery.carrier']._fields['delivery_type'].selection)
        self.assertIn('ups_tr', selection, 'anahtar ups degil ups_tr (Enterprise delivery_ups ile cakismaz)')
        for field in SECRET_FIELDS:
            definition = self.env['delivery.carrier']._fields[field]
            self.assertIn('cargo.group_cargo_manager', str(definition.groups), '%s yonetici grubuna bagli' % field)
            self.assertFalse(definition.copy, '%s kopyalanmamali' % field)

    def test_firma_cekirdek_yonetilen(self):
        self.assertTrue(self.ups._cargo_is_managed())
        self.assertTrue(hasattr(self.ups, 'ups_tr_cargo_send'))
        self.assertTrue(hasattr(self.ups, 'ups_tr_cargo_cancel'))
        self.assertTrue(hasattr(self.ups, 'ups_tr_cargo_find'))

    def test_sirlar_kargo_kullanicisina_okunmaz(self):
        """KK-2: read / search_read / web_read / web_search_read / search ile sir alani AccessError."""
        carrier = self.ups.with_user(self.user)
        for field in SECRET_FIELDS:
            with self.subTest(field=field):
                with self.assertRaises(AccessError):
                    carrier.read([field])
                with self.assertRaises(AccessError):
                    carrier.search_read([('id', '=', self.ups.id)], [field])
                with self.assertRaises(AccessError):
                    carrier.web_read({field: {}})
                with self.assertRaises(AccessError):
                    carrier.web_search_read([('id', '=', self.ups.id)], {field: {}})
                with self.assertRaises(AccessError):
                    carrier.search([('id', '=', self.ups.id), (field, '!=', False)])
                with self.assertRaises(AccessError):
                    carrier[field]

    def test_alan_listesiz_okuma_sizdirmaz(self):
        """Alan listesi verilmeyen read/default_get/copy_data sirlari dondurmez (AccessError ya da sessizce eksik)."""
        carrier = self.ups.with_user(self.user)
        for func in (lambda: carrier.read(), lambda: carrier.web_read({'name': {}}), lambda: carrier.copy_data(),
                     lambda: carrier.default_get(list(SECRET_FIELDS))):
            try:
                result = func()
            except AccessError:
                continue
            text = str(result)
            for secret in SECRET_VALUES:
                self.assertNotIn(secret, text, 'okuma sir sizdirdi')

    def test_yonetici_okur_ve_yazar(self):
        carrier = self.ups.with_user(self.manager)
        self.assertEqual(carrier.ups_tr_password, SECRETS['password'])
        carrier.write({'ups_tr_username': 'yeni_kullanici'})
        self.assertEqual(self.ups.sudo().ups_tr_username, 'yeni_kullanici')

    def test_kopyada_sirlar_yok(self):
        copy = self.ups.sudo().copy()
        for field in SECRET_FIELDS:
            self.assertFalse(copy[field], 'kopya sir tasimamali: %s' % field)

    def test_rate_shipment_fiyat_hesaplanmaz(self):
        order = self.env['sale.order'].create({'partner_id': self.env['res.partner'].create({'name': 'Siparis Musterisi'}).id})
        self.assertEqual(self.ups.ups_tr_rate_shipment(order),
                         {'success': False, 'price': 0.0, 'error_message': 'Fiyat hesaplanmaz', 'warning_message': False})

    def picking(self, tracking='1ZTRACK0001'):
        warehouse = self.env['stock.warehouse'].search([], limit=1)
        return self.env['stock.picking'].create({
            'picking_type_id': warehouse.out_type_id.id, 'location_id': warehouse.out_type_id.default_location_src_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id, 'carrier_tracking_ref': tracking,
        })

    def test_cekirdek_iptal_dugmesi_gonderiyi_iptal_etmez(self):
        """KK-33: stock_delivery 'Cancel' dugmesi ups_tr_cancel_shipment'i cagirirsa UserError; UPS'e cagri yok."""
        picking = self.picking()
        with self.assertRaisesRegex(UserError, 'Kargo gönderisi formundan iptal edin'):
            self.ups.ups_tr_cancel_shipment(picking)
        self.assertEqual(self.net.requests, [])

    def test_takip_baglantisi_sirsiz(self):
        picking = self.picking('1ZTRACK0001')
        link = self.ups.get_tracking_link(picking)
        self.assertTrue(link)
        self.assertIn('1ZTRACK0001', link)
        self.assertTrue(link.startswith('https://'))
        for secret in SECRET_VALUES + [SECRETS['session'], 'LabelKey']:
            self.assertNotIn(secret, link)

    def test_ups_firmasi_rate_and_ship_olamaz(self):
        """KK-33: yonetilen UPS firmasinda otomatik gonderim (rate_and_ship) reddedilir."""
        with self.assertRaises(ValidationError):
            self.ups.write({'integration_level': 'rate_and_ship'})
        with self.assertRaises(ValidationError):
            self.env['delivery.carrier'].create({
                'name': 'UPS ikinci', 'delivery_type': 'ups_tr', 'product_id': self._service_product().id,
                'integration_level': 'rate_and_ship'})

    def test_odp_izinleri_ups_icin(self):
        """KK-19b/19c UPS tarafi: kart kapaliyken kart reddedilir, UPS'e cagri yok."""
        self.assert_user_error(lambda: self.mk(**self.ups_vals(cod_amount=200.0, cod_method='card')).action_send())
        self.assertEqual(self.net.requests, [])
        self.ups.with_user(self.manager).write({'cargo_cod_enabled': False})
        self.assert_user_error(lambda: self.mk(**self.ups_vals(cod_amount=200.0, cod_method='cash')).action_send())
        self.assertEqual(self.net.requests, [])

    def test_veri_sayilari(self):
        """KK-32: 1014 ilce, 81 il (KKTC haric); (provider, area_code) benzersiz."""
        areas = self.env['cargo.area'].sudo().search([('provider', '=', 'ups_tr')])
        self.assertEqual(len(areas), 1014)
        self.assertEqual(len(areas.mapped('state_id')), 81)
        self.assertEqual(len(set(areas.mapped('area_code'))), 1014)
        self.assertEqual({int(c) for c in areas.mapped('state_id.code')}, set(range(1, 82)))
        for area in areas[:50]:
            self.assertEqual(area.city_code, int(area.state_id.code), 'city_code = il plaka kodu')
            self.assertEqual(area.state_id.country_id, self.tr)

    def test_veri_dosyalari_ve_manifest(self):
        import ast
        with open(os.path.join(MODULE_DIR, '__manifest__.py'), encoding='utf-8') as handle:
            manifest = ast.literal_eval(handle.read())
        self.assertEqual(manifest['depends'], ['cargo'], 'cargo_ups yalniz cargo\'ya bagli (yeni bagimlilik yok)')
        csv_path = os.path.join(MODULE_DIR, 'data', 'cargo.area.csv')
        self.assertTrue(os.path.exists(csv_path), 'data/cargo.area.csv')
        with open(csv_path, encoding='utf-8-sig') as handle:
            header = handle.readline()
        self.assertNotIn('alias_names', header, 'CSV takma ad tasimaz (noupdate xml\'de)')
        self.assertIn('data/cargo.area.csv', manifest['data'])
