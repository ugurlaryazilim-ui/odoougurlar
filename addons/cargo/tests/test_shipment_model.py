# -*- coding: utf-8 -*-
"""cargo.shipment model birim testleri: varsayılanlar, ilçe eşleme, doğrulama, kilitler, indeks, görünümler.

Gönder/uzlaştır/iptal akışı bu dosyada yoktur (ayrı görev); burada ``_cargo_check_ready`` doğrudan çağrılır.
"""
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import CargoTestCase


@tagged('post_install', '-at_install', 'cargo')
class TestShipmentModel(CargoTestCase):
    REQUIRES_MODELS = ('cargo.shipment', 'cargo.area')

    def setUp(self):
        super().setUp()
        # `fixed` tipi yönetilen firma sayılsın (cargo_managed kancası).
        self.stub_provider('fixed')

    def check(self, **over):
        """-> (taslak, hata|None); doğrulama başarısızsa gönderi taslak olarak kalır."""
        shipment = self.mk(**over)
        _, error = self.try_call(shipment._cargo_check_ready)
        return shipment, error

    def set_state(self, shipment, state):
        shipment.sudo().write({'state': state})

    # ------------------------------------------------------------------ varsayılanlar
    def test_varsayilanlar(self):
        shipment = self.mk()
        self.assertRegex(shipment.name, r'^KRG/\d{4}/\d{5}$')
        self.assertEqual(shipment.state, 'draft')
        self.assertTrue(shipment.test_mode, 'prod_environment kapalı firma = test')
        self.assertEqual(shipment.company_id, self.company)
        self.assertEqual(shipment.currency_id, self.company.currency_id)
        self.assertEqual(shipment.package_count, 1)

    def test_firma_ve_agirlik_sirket_varsayilani(self):
        self.company.cargo_default_weight = 2.5
        vals = self.vals()
        for key in ('carrier_id', 'package_weight'):
            vals.pop(key)
        shipment = self.env['cargo.shipment'].with_user(self.user).create(vals)
        self.assertEqual(shipment.carrier_id, self.carrier)
        self.assertEqual(shipment.package_weight, 2.5)
        # açık False da varsayılana düşer
        vals['carrier_id'] = False
        self.assertEqual(self.env['cargo.shipment'].with_user(self.user).create(vals).carrier_id, self.carrier)

    def test_varsayilan_firma_yoksa_hata(self):
        self.company.cargo_default_carrier_id = False
        vals = self.vals()
        vals.pop('carrier_id')
        with self.assertRaisesRegex(UserError, 'Varsayılan kargo firması ayarlı değil'):
            self.env['cargo.shipment'].with_user(self.user).create(vals)

    def test_test_modu_firma_degisince_taslakta_guncellenir(self):
        shipment = self.mk()
        self.carrier_y.prod_environment = True
        shipment.write({'carrier_id': self.carrier_y.id})
        self.assertFalse(shipment.test_mode)
        # kilitli kayıtta firma değişmez (kural), dolayısıyla test_mode de oynamaz
        self.set_state(shipment, 'created')
        with self.assertRaises(AccessError):
            shipment.with_user(self.user).write({'carrier_id': self.carrier.id})

    # ------------------------------------------------------------------ doğrulama sınırları
    def test_gecerli_gonderi(self):
        shipment, error = self.check()
        self.assertIsNone(error, error)
        self.assertEqual(shipment.state, 'draft')

    def test_sinir_tablosu(self):
        """(alan, değer, geçerli mi)."""
        cases = [
            ('recipient_name', 'ab', False), ('recipient_name', 'abc', True), ('recipient_name', '  ', False),
            ('recipient_phone', '1' * 9, False), ('recipient_phone', '1' * 10, True),
            ('recipient_phone', '1' * 16, True), ('recipient_phone', '1' * 17, False),
            ('recipient_phone', 'abc', False), ('recipient_phone', False, False),
            ('recipient_email', 'a' * 55 + '@b.com', True), ('recipient_email', 'a' * 60 + '@b.com', False),
            ('recipient_street', 'ab', False), ('recipient_street', 'abc', True),
            ('recipient_street', 'a' * 255, True), ('recipient_street', 'a' * 256, False),
            ('recipient_district', '', False), ('recipient_district', '   ', False),
            ('package_count', 0, False), ('package_count', 1, True), ('package_count', 99, True),
            ('package_count', 100, False),
            ('package_weight', 0.0, False), ('package_weight', -1.0, False), ('package_weight', 70.0, True),
            ('package_weight', 70.01, False),
            ('origin_ref', 'o' * 40, True), ('origin_ref', 'p' * 41, False),
            ('invoice_no', 'f' * 20, True), ('invoice_no', 'g' * 21, False),
            ('description', 'd' * 120, True), ('description', 'e' * 121, False),
        ]
        for field, value, valid in cases:
            with self.subTest(field=field, value=value):
                # ilçe boşken eşleme notu da hata verir; ilçe senaryosunda yalnız reddi beklemek yeterli
                _, error = self.check(**{field: value})
                if valid:
                    self.assertIsNone(error, error)
                else:
                    self.assertIsNotNone(error)
                    self.assertIn(self.env['cargo.shipment']._fields[field].string, str(error))

    def test_turkiye_disi_il_reddedilir(self):
        us_state = self.env['res.country.state'].search([('country_id.code', '=', 'US')], limit=1)
        if not us_state:
            self.skipTest('ABD ili verisi yok')
        _, error = self.check(recipient_state_id=us_state.id)
        self.assertIsNotNone(error)

    def test_coklu_hata_tek_mesaj(self):
        _, error = self.check(recipient_name='a', recipient_phone='1', recipient_street='a')
        text = str(error)
        for field in ('recipient_name', 'recipient_phone', 'recipient_street'):
            self.assertIn(self.env['cargo.shipment']._fields[field].string, text)

    def test_ad_kelime_sinirinda_kisaltilir(self):
        shipment, error = self.check(recipient_name='x' * 20 + ' ' + 'y' * 20)
        self.assertIsNone(error)
        self.assertEqual(shipment.recipient_name, 'x' * 20)
        self.assertRegex(self.chatter(shipment), 'kısaltıldı')
        sert, error = self.check(recipient_name='z' * 50)
        self.assertIsNone(error)
        self.assertEqual(sert.recipient_name, 'z' * 40)
        tam, error = self.check(recipient_name='a' * 19 + ' ' + 'b' * 20)
        self.assertEqual(len(tam.recipient_name), 40)
        self.assertNotRegex(self.chatter(tam), 'kısaltıldı')

    def test_telefon_rakama_indirgenir(self):
        shipment, error = self.check(recipient_phone='+90 (532) 123-45-67')
        self.assertIsNone(error)
        self.assertEqual(shipment.recipient_phone, '905321234567')

    def test_hatali_dogrulamada_veri_degismez(self):
        shipment, error = self.check(recipient_name='x' * 50, recipient_phone='+1 2', recipient_street='a')
        self.assertIsNotNone(error)
        self.assertEqual(shipment.recipient_name, 'x' * 50)
        self.assertEqual(shipment.recipient_phone, '+1 2')

    def test_yonetilmeyen_firma_reddedilir(self):
        other = self.make_carrier('Sağlayıcısız', ptype='fixed')
        # fixed yönetilen; yönetilmeyen = `base_on_rule` gibi *_cargo_send olmayan tip
        other.delivery_type = 'base_on_rule'
        _, error = self.check(carrier_id=other.id)
        self.assertIsNotNone(error)

    # ------------------------------------------------------------------ ODP
    def test_odp_kurallari(self):
        _, error = self.check(cod_amount=100.0, cod_method='cash')
        self.assertIsNone(error, error)
        _, error = self.check(cod_amount=-1.0, cod_method='cash')
        self.assertIn('Kapıda ödeme tutarı', str(error))
        _, error = self.check(cod_amount=100.0)
        self.assertIn('Tahsil şekli', str(error))
        self.assertRegex(str(self.check(cod_amount=100.0, cod_method='cash', carrier_id=self.carrier_nocod.id)[1]),
                         r'(?i)kapıda ödeme etkin değil')
        # tahsil şekilleri
        for method, allowed in (('card', False), ('check', False)):
            _, error = self.check(cod_amount=100.0, cod_method=method)
            self.assertIsNotNone(error, method)
        self.carrier.sudo().write({'cargo_cod_allow_card': True, 'cargo_cod_allow_cash': False})
        self.assertIsNone(self.check(cod_amount=100.0, cod_method='card')[1])
        self.assertIsNotNone(self.check(cod_amount=100.0, cod_method='cash')[1])

    def test_odp_ust_sinir(self):
        self.company.cargo_cod_max_amount = 500.0
        self.assertIsNone(self.check(cod_amount=500.0, cod_method='cash')[1])
        self.assertIn('Kapıda ödeme tutarı', str(self.check(cod_amount=500.01, cod_method='cash')[1]))
        self.company.cargo_cod_max_amount = 0.0
        self.assertIsNone(self.check(cod_amount=1000000.0, cod_method='cash')[1])

    def test_odp_yoksa_yontem_sorulmaz(self):
        self.assertIsNone(self.check(cod_amount=0.0, cod_method=False, carrier_id=self.carrier_nocod.id)[1])

    # ------------------------------------------------------------------ ilçe eşleme
    def test_ilce_otomatik_eslenir(self):
        shipment = self.mk()
        self.assertEqual(shipment.area_id, self.area_cankaya)
        self.assertFalse(shipment.area_match_note)
        self.assertEqual(self.mk(recipient_district='ÇANKAYA').area_id, self.area_cankaya)
        shipment.recipient_district = 'Kadikoy'     # il değişmedi (Ankara) -> eşleşmez
        self.assertFalse(shipment.area_id)

    def test_eslesmeyen_ilce_not_ve_ret(self):
        shipment, error = self.check(recipient_district='Bilinmeyenköy')
        self.assertFalse(shipment.area_id)
        self.assertIn('İlçe eşleşmedi', shipment.area_match_note)
        self.assertIn('Bilinmeyenköy', shipment.area_match_note)
        self.assertIn('İlçe eşleşmedi', str(error))

    def test_yasak_girdi_belirsiz_notu(self):
        for text in ('Merkez', 'Ankara', ''):
            with self.subTest(text=text):
                shipment, error = self.check(recipient_district=text)
                self.assertFalse(shipment.area_id)
                self.assertIsNotNone(error)
        self.assertIn('İlçe belirsiz', self.mk(recipient_district='Merkez').area_match_note)

    def test_cok_aday_belirsiz(self):
        self.make_area('06', 'ZETA BIR', alias='Ortak Ad')
        self.make_area('06', 'ZETA IKI', alias='Ortak Ad')
        shipment = self.mk(recipient_district='Ortak Ad')
        self.assertFalse(shipment.area_id)
        self.assertIn('İlçe belirsiz', shipment.area_match_note)
        self.assertIn('ZETA BIR', shipment.area_match_note)
        self.assertIn('ZETA IKI', shipment.area_match_note)

    def test_elle_secim(self):
        other = self.make_area('06', 'ELLE SECILEN')
        shipment = self.mk(recipient_district='Bilinmeyenköy', area_id=other.id)
        self.assertEqual(shipment.area_id, other)
        self.assertFalse(shipment.area_match_note)
        self.assertIsNone(self.try_call(shipment._cargo_check_ready)[1])
        self.assertEqual(shipment._cargo_area_manual_note(),
                         'İlçe elle seçildi: "Bilinmeyenköy" → ELLE SECILEN')
        self.assertEqual(self.mk()._cargo_area_manual_note(), '', 'otomatik eşleşmede not yok')

    def test_ilce_kapsam_kontrolu(self):
        with self.assertRaises(ValidationError):      # başka ilin ilçesi
            self.mk(area_id=self.area_kadikoy.id)
        other_provider = self.make_area('06', 'BASKA SAGLAYICI', provider='baska')
        with self.assertRaises(ValidationError):
            self.mk(area_id=other_provider.id)

    def test_sirket_ilcesi_eslesmezse_ret(self):
        self.company.city = 'Bilinmeyenköy'
        shipment, error = self.check()
        self.assertIn('Şirket adresinin ilçesi eşleşmedi', str(error))

    # ------------------------------------------------------------------ kilitler
    def test_taslak_ve_hatali_duzenlenir_digerleri_kilitli(self):
        for state, editable in (('draft', True), ('failed', True), ('sending', False), ('uncertain', False),
                                ('created', False), ('in_transit', False), ('delivered', False),
                                ('cancelled', False)):
            with self.subTest(state=state):
                shipment = self.mk()
                self.set_state(shipment, state)
                if editable:
                    shipment.with_user(self.user).write({'recipient_street': 'Yeni Sokak 9'})
                    self.assertEqual(shipment.recipient_street, 'Yeni Sokak 9')
                else:
                    with self.assertRaises(AccessError):
                        shipment.with_user(self.user).write({'recipient_street': 'Yeni Sokak 9'})
                    with self.assertRaises(AccessError):
                        shipment.with_user(self.manager).write({'recipient_street': 'Yeni Sokak 9'})

    def test_sistem_alanlarini_kullanici_yazamaz(self):
        shipment = self.mk()
        for field, value in (('state', 'created'), ('tracking_ref', 'X'), ('name', 'KRG/HACK'), ('test_mode', False),
                             ('error_message', 'x'), ('label_missing', True), ('sent_at', '2026-01-01 00:00:00'),
                             ('cancelled_at', '2026-01-01 00:00:00'), ('source_id', 5), ('source_model', 'x'),
                             ('error_code', 'x'), ('picking_id', 1), ('label_pdf_id', 1),
                             ('label_png_ids', [(6, 0, [])])):
            for user in (self.user, self.manager):
                with self.subTest(field=field, user=user.login), self.assertRaises(AccessError):
                    shipment.with_user(user).write({field: value})
        self.assertEqual(shipment.state, 'draft')

    def test_olusturmada_sistem_alani_reddedilir(self):
        with self.assertRaises(AccessError):
            self.env['cargo.shipment'].with_user(self.user).create(self.vals(state='created'))
        with self.assertRaises(AccessError):
            self.env['cargo.shipment'].with_user(self.user).create(self.vals(name='KRG/HACK'))

    def test_default_baglami_sistem_alanini_degistiremez(self):
        shipment = self.env['cargo.shipment'].with_user(self.user).with_context(
            default_state='created', default_tracking_ref='1ZSAHTE', default_test_mode=False,
            default_name='KRG/HACK', default_error_message='x').create(self.vals())
        self.assertEqual(shipment.state, 'draft')
        self.assertFalse(shipment.tracking_ref)
        self.assertFalse(shipment.error_message)
        self.assertTrue(shipment.test_mode)
        self.assertRegex(shipment.name, r'^KRG/')
        self.assertNotEqual(shipment.name, 'KRG/HACK')

    def test_kopya_temiz_taslak(self):
        shipment = self.mk(origin_ref='ORJ-1')
        shipment.sudo().write({'state': 'created', 'tracking_ref': 'T1', 'error_message': 'x'})
        copy = shipment.sudo().copy()
        self.assertEqual(copy.state, 'draft')
        self.assertFalse(copy.tracking_ref)
        self.assertFalse(copy.origin_ref)
        self.assertFalse(copy.error_message)
        self.assertNotEqual(copy.name, shipment.name)

    def test_silme_kurallari(self):
        draft = self.mk()
        draft.with_user(self.user).unlink()
        self.assertFalse(draft.exists())
        failed = self.mk()
        self.set_state(failed, 'failed')
        with self.assertRaises(AccessError):
            failed.with_user(self.user).unlink()
        failed.with_user(self.manager).unlink()
        self.assertFalse(failed.exists())
        for state in ('created', 'sending', 'uncertain', 'cancelled'):
            kept = self.mk()
            self.set_state(kept, state)
            for user in (self.user, self.manager):
                with self.subTest(state=state, user=user.login), self.assertRaises(AccessError):
                    kept.with_user(user).unlink()
            self.assertTrue(kept.exists())

    def test_duz_kullanici_erisemez(self):
        for user in (self.plain, self.plain_sales):
            with self.assertRaises(AccessError):
                self.env['cargo.shipment'].with_user(user).search([])
            with self.assertRaises(AccessError):
                self.env['cargo.shipment'].with_user(user).create(self.vals())

    def test_kullanici_kilitli_kaydi_okur_ve_not_dusebilir(self):
        shipment = self.mk()
        self.set_state(shipment, 'created')
        record = shipment.with_user(self.user)
        self.assertEqual(record.recipient_name, 'Ali Veli')     # DERSLER 6: okuma önkoşulu
        self.assertEqual(record.carrier_id.display_name, self.carrier.display_name)
        self.assertEqual(shipment._mail_post_access, 'read')
        record.message_post(body='Operatör notu', subtype_xmlid='mail.mt_note')
        self.assertIn('Operatör notu', self.chatter(shipment))

    # ------------------------------------------------------------------ iş referansı indeksi
    def test_origin_ref_kismi_benzersiz(self):
        first = self.mk(origin_ref='SIP-1')
        with mute_logger('odoo.sql_db'), self.assertRaises(Exception), self.env.cr.savepoint():
            self.mk(origin_ref='SIP-1')
        self.set_state(first, 'failed')
        second = self.mk(origin_ref='SIP-1')
        self.set_state(second, 'cancelled')
        self.assertTrue(self.mk(origin_ref='SIP-1').exists())

    def test_origin_ref_bos_normalize_edilir(self):
        a, b = self.mk(origin_ref=''), self.mk(origin_ref='  ')
        self.assertFalse(a.origin_ref)
        self.assertFalse(b.origin_ref)
        shipment = self.mk(origin_ref=' X1 ')
        self.assertEqual(shipment.origin_ref, 'X1')
        shipment.write({'origin_ref': ''})
        self.assertFalse(shipment.origin_ref)

    # ------------------------------------------------------------------ görünümler
    def test_gorunumler_ve_menu(self):
        views = self.env['cargo.shipment'].with_user(self.user).get_views(
            [(False, 'list'), (False, 'form'), (False, 'search')])
        self.assertEqual(set(views['views']), {'list', 'form', 'search'})
        self.assertTrue(self.env.ref('cargo.action_cargo_shipment').res_model == 'cargo.shipment')
        menu = self.env.ref('cargo.menu_cargo_shipment')
        self.assertEqual(menu.parent_id, self.env.ref('cargo.menu_cargo_root'))
        self.assertEqual(menu.with_user(self.user).name, 'Gönderiler')
