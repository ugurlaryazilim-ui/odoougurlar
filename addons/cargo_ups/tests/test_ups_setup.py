# -*- coding: utf-8 -*-
"""G8: cargo_ups iskeleti - firma veri kaydı, sır alanları, Odoo delivery kancaları.

NEDEN: cargo.shipment (G3) gerektirmez; salt cargo + cargo_ups kurulu iken çalışır.
"""
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

SECRET_FIELDS = ('ups_tr_customer_number', 'ups_tr_shipper_account', 'ups_tr_username', 'ups_tr_password',
                 'ups_tr_track_username', 'ups_tr_track_password')
# O-1: sır değil ama faturayı/hizmeti belirler; varsayılandan farklı yazım değerleri.
SERVICE_VALUES = (('ups_tr_service_level', '1'), ('ups_tr_payment_type', '1'), ('ups_tr_package_type', 'D'),
                  ('ups_tr_sms_to_consignee', True))
# NEDEN: sentetik, tanınabilir sırlar; gerçek hesap bilgisi testlerde ve veride yoktur.
FAKE_SECRET = 'SENTETIK-SIR-G8'


@tagged('post_install', '-at_install', 'cargo_ups')
class TestUpsSetup(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Carrier = cls.env['delivery.carrier']
        cls.data = cls.env.ref('cargo_ups.carrier_ups_tr')
        cls.ups = cls.Carrier.create({
            'name': 'G8 UPS', 'delivery_type': 'ups_tr', 'integration_level': 'rate',
            'product_id': cls.env.ref('delivery.product_product_delivery').id,
            **{field: FAKE_SECRET for field in SECRET_FIELDS},
        })
        cls.cargo_user = new_test_user(cls.env, login='g8_kargo_kullanici', groups='base.group_user,cargo.group_cargo_user')
        cls.plain_user = new_test_user(cls.env, login='g8_duz_kullanici', groups='base.group_user')
        cls.cargo_manager = new_test_user(cls.env, login='g8_kargo_yonetici', groups='base.group_user,cargo.group_cargo_manager')

    def test_veri_kaydi_varsayilanlari(self):
        carrier = self.data.sudo()
        self.assertEqual(carrier.delivery_type, 'ups_tr')
        self.assertEqual(carrier.integration_level, 'rate')
        self.assertFalse(carrier.prod_environment, 'DB kopyası canlıya değil test ucuna gitmeli (K-26)')
        self.assertTrue(carrier.cargo_cod_enabled, 'S-1: UPS hesabında ODP açık')
        self.assertTrue(carrier.cargo_cod_allow_cash)
        self.assertFalse(carrier.cargo_cod_allow_card)
        self.assertFalse(carrier.cargo_cod_allow_check)
        self.assertEqual(carrier.product_id, self.env.ref('delivery.product_product_delivery'))
        self.assertEqual((carrier.ups_tr_service_level, carrier.ups_tr_payment_type, carrier.ups_tr_package_type),
                         ('3', '2', 'K'))
        self.assertFalse(carrier.ups_tr_sms_to_consignee)
        for field in SECRET_FIELDS:
            self.assertFalse(carrier[field], 'veri kaydında sır olmamalı: %s' % field)

    def test_veri_kayitlari_noupdate(self):
        """Yöneticinin firma ayarları (ODP bayrakları, hesap) -u ile ezilmesin."""
        data = self.env['ir.model.data'].sudo().search([('module', '=', 'cargo_ups'), ('name', '=', 'carrier_ups_tr')])
        self.assertTrue(data.noupdate)

    def test_cekirdek_yonetilen_ve_rate_zorunlu(self):
        self.assertTrue(self.ups._cargo_is_managed())
        self.assertIn('ups_tr', self.Carrier._cargo_managed_types())
        with self.assertRaises(ValidationError):
            self.ups.write({'integration_level': 'rate_and_ship'})

    def test_sirlar_normal_kullanici_okuyamaz(self):
        for user in (self.cargo_user, self.plain_user):
            carrier = self.ups.with_user(user)
            for field in SECRET_FIELDS:
                with self.subTest(field=field):
                    with self.assertRaises(AccessError):
                        carrier.read([field])
                    with self.assertRaises(AccessError):
                        carrier.search_read([('id', '=', self.ups.id)], [field])
                    with self.assertRaises(AccessError):
                        carrier[field]

    def test_sirlar_alan_listesiz_okumada_sizmaz(self):
        carrier = self.ups.with_user(self.cargo_user)
        try:
            text = str(carrier.read())
        except AccessError:
            return
        self.assertNotIn(FAKE_SECRET, text)

    def test_yonetici_okur_ve_yazar(self):
        carrier = self.ups.with_user(self.cargo_manager)
        self.assertEqual(carrier.ups_tr_password, FAKE_SECRET)
        carrier.write({'ups_tr_username': 'yeni'})
        self.assertEqual(self.ups.sudo().ups_tr_username, 'yeni')

    def test_form_gorunumu_yalniz_yoneticiye(self):
        """Hesap alanları formda yalnız Kargo / Yönetici için gelir (sır alanı düzeyinde de kapalı)."""
        arch = self.Carrier.with_user(self.cargo_manager).get_view(view_type='form')['arch']
        for field in SECRET_FIELDS:
            self.assertIn(field, arch)
        arch = self.Carrier.with_user(self.cargo_user).get_view(view_type='form')['arch']
        for field in SECRET_FIELDS:
            self.assertNotIn(field, arch)

    def test_alan_tanimlari_ve_kopya(self):
        for field in SECRET_FIELDS:
            definition = self.Carrier._fields[field]
            self.assertIn('cargo.group_cargo_manager', str(definition.groups))
            self.assertFalse(definition.copy)
        for field, _value in SERVICE_VALUES:
            self.assertEqual(self.Carrier._fields[field].groups, 'cargo.group_cargo_manager', field)
        copy = self.ups.sudo().copy()
        for field in SECRET_FIELDS:
            self.assertFalse(copy[field])

    def test_hizmet_alanlari_yalniz_kargo_yoneticisi_yazar(self):
        """O-1 (05-guvenlik): faturayi belirleyen hizmet alanlari; ACL'li stok/satis yoneticisi yazamaz.
        NEDEN: delivery.carrier ACL'si stock/sales yoneticisine 1,1,1,1 verir; koruma alan groups'udur."""
        stock_manager = new_test_user(self.env, login='o1_stok_yonetici', groups='base.group_user,stock.group_stock_manager')
        sale_manager = new_test_user(self.env, login='o1_satis_yonetici', groups='base.group_user,sales_team.group_sale_manager')
        values = dict(SERVICE_VALUES)
        for user in (stock_manager, sale_manager):
            carrier = self.ups.with_user(user)
            carrier.check_access('write')     # ACL var; reddi alan grubu verir
            for field, value in values.items():
                with self.subTest(user=user.login, field=field):
                    with self.assertRaises(AccessError):
                        carrier.write({field: value})
                    with self.assertRaises(AccessError):
                        carrier.read([field])
            with self.assertRaises(AccessError):
                self.Carrier.with_user(user).create({
                    'name': 'O1 sahte', 'delivery_type': 'fixed', 'ups_tr_payment_type': '1',
                    'product_id': self.env.ref('delivery.product_product_delivery').id})
        self.assertEqual(tuple(self.ups.sudo()[f] for f in values), ('3', '2', 'K', False), 'deger degismedi')
        # Kardes yol: UPS disi firma yonetimi stok yoneticisinde bozulmaz (varsayilanlar kullanici degeri sayilmaz).
        Carrier = self.Carrier.with_user(stock_manager)
        fixed = Carrier.create({'name': 'O1 sabit', 'delivery_type': 'fixed',
                                'product_id': self.env.ref('delivery.product_product_delivery').id})
        fixed.write({'name': 'O1 sabit 2'})
        self.assertEqual(fixed.sudo().ups_tr_payment_type, '2', 'varsayilan create yolunda yazildi')
        # NEDEN: copy() burada sinanmaz: stok yoneticisi copy_data'da groups'lu cargo_cod_* alanini okuyamaz
        # (cargo'da, bu degisiklikten once de var; DT1 raporunda bildirildi).
        # Kargo yoneticisi yazar.
        self.ups.with_user(self.cargo_manager).write(values)
        self.assertEqual(tuple(self.ups.sudo()[f] for f in values), tuple(values.values()))

    def test_odoo_kancalari(self):
        order = self.env['sale.order'].create({'partner_id': self.env['res.partner'].create({'name': 'G8 Müşteri'}).id})
        self.assertEqual(self.ups.ups_tr_rate_shipment(order),
                         {'success': False, 'price': 0.0, 'error_message': 'Fiyat hesaplanmaz', 'warning_message': False})
        picking = self.env['stock.picking'].new({'carrier_tracking_ref': '1ZG8TRACK 01'})
        with self.assertRaisesRegex(UserError, 'Kargo gönderisi formundan iptal edin'):
            self.ups.cancel_shipment(picking)
        link = self.ups.get_tracking_link(picking)
        self.assertTrue(link.startswith('https://'))
        self.assertIn('1ZG8TRACK%2001', link, 'takip no URL için kaçışlanır')
        self.assertNotIn(FAKE_SECRET, link)

    def test_secenek_listeleri(self):
        selections = {name: dict(self.Carrier._fields[name].selection)
                      for name in ('ups_tr_service_level', 'ups_tr_payment_type', 'ups_tr_package_type')}
        self.assertEqual(set(selections['ups_tr_service_level']), {'1', '3', '4', '5', '6'})
        self.assertEqual(set(selections['ups_tr_payment_type']), {'1', '2', '4'})
        self.assertEqual(set(selections['ups_tr_package_type']), {'D', 'K'})

    def test_ondelete_tanimli(self):
        """Modül kaldırılırken ups_tr firmaları fixed + arşivli olur (K-20)."""
        ondelete = self.Carrier._fields['delivery_type'].ondelete
        self.assertIn('ups_tr', ondelete)
        ondelete['ups_tr'](self.ups)
        self.assertEqual((self.ups.delivery_type, self.ups.active), ('fixed', False))
