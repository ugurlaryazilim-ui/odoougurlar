# -*- coding: utf-8 -*-
"""KABUL: gonderi modeli ve on-dogrulama (KK-4, KK-5 model, KK-7, KK-13, KK-16, KK-18, KK-19, KK-19b, KK-19c).

Yesile donecegi gorev: G3 (cargo.shipment modeli, _cargo_check_ready, kilitler, ODP kurallari); gonderim akisi G4.
Sozlesme: dogrulama create'te (ValidationError) VEYA 'Gonder'de (UserError) reddedebilir; ikisi de kabul edilir,
ama reddedilen gonderi icin saglayiciya HIC cagri yapilmamali ve olusmus kayit 'draft' kalmali (KK-7).
"""
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .kabul_taban import CargoKabulCase


class DogrulamaBase(CargoKabulCase):

    def _mentions(self, error, field):
        label = self.env['cargo.shipment']._fields[field].string or ''
        text = str(error).lower()
        return field in text or (label and label.lower() in text)

    def attempt(self, over, user=None):
        """-> (shipment|None, error|None, provider_cagri_artisi): create sonra action_send; ilk reddeden hata doner."""
        before = self.provider.count('send')
        shipment, error = self.try_call(lambda: self.mk(user=user, **over))
        if error is None:
            _, error = self.try_call(shipment.action_send)
        return shipment, error, self.provider.count('send') - before

    def assert_rejected(self, over, field=None, regex=None, msg=''):
        shipment, error, calls = self.attempt(over)
        self.assertIsNotNone(error, 'REDDEDILMELIYDI %s %s' % (over, msg))
        self.assertEqual(calls, 0, 'reddedilen gonderide saglayici cagrilmamali %s' % over)
        if shipment:
            self.assertEqual(shipment.state, 'draft', 'reddedilen gonderi draft kalmali')
        if field:
            self.assertTrue(self._mentions(error, field), '%s alani hata metninde gecmeli: %s' % (field, error))
        if regex:
            self.assertRegex(str(error), regex)
        return error

    def assert_accepted(self, over):
        shipment, error, calls = self.attempt(over)
        self.assertIsNone(error, 'KABUL EDILMELIYDI %s -> %s' % (over, error))
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(calls, 1)
        return shipment


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulDogrulamaSiniri(DogrulamaBase):

    def test_ad_siniri(self):
        """KK-7: ad 3-40; 40'i asan ad REDDEDILMEZ, kisaltilir."""
        self.assert_rejected({'recipient_name': 'Ab'}, 'recipient_name')
        self.assert_rejected({'recipient_name': ''}, 'recipient_name')
        self.assert_accepted({'recipient_name': 'Abc'})
        self.assert_accepted({'recipient_name': 'Ab ' + 'c' * 37})

    def test_ad_kisaltma(self):
        original = 'Aaaaaaaaaa Bbbbbbbbbb Cccccccccc Dddddddddd Eeeeeeeeee'
        self.assertGreater(len(original), 40)
        shipment = self.assert_accepted({'recipient_name': original})
        sent_name = self.provider.of('send')[-1]['recipient_name']
        self.assertLessEqual(len(sent_name), 40)
        self.assertGreaterEqual(len(sent_name), 3)
        self.assertTrue(original.startswith(sent_name), 'kisaltilmis ad orijinalin oneki olmali: %r' % sent_name)
        self.assertEqual(original[len(sent_name)], ' ', 'kelime sinirinda kisaltilmali: %r' % sent_name)
        self.assertRegex(self.chatter(shipment), r'(?i)kısaltıl')
        # tam 41 karakter, bosluk 21. konumda
        exact = 'x' * 20 + ' ' + 'y' * 20
        self.assertEqual(len(exact), 41)
        self.assert_accepted({'recipient_name': exact})
        self.assertEqual(self.provider.of('send')[-1]['recipient_name'], 'x' * 20)

    def test_ad_40_kisaltilmaz(self):
        name = 'a' * 19 + ' ' + 'b' * 20
        self.assertEqual(len(name), 40)
        shipment = self.assert_accepted({'recipient_name': name})
        self.assertEqual(self.provider.of('send')[-1]['recipient_name'], name)
        self.assertNotRegex(self.chatter(shipment), r'(?i)kısaltıl')

    def test_adres_siniri(self):
        self.assert_rejected({'recipient_street': 'ab'}, 'recipient_street')
        self.assert_rejected({'recipient_street': ''}, 'recipient_street')
        self.assert_accepted({'recipient_street': 'abc'})
        self.assert_accepted({'recipient_street': 'a' * 255})
        self.assert_rejected({'recipient_street': 'a' * 256}, 'recipient_street')

    def test_il_ilce_dolu(self):
        self.assert_rejected({'recipient_state_id': False})
        self.assert_rejected({'recipient_district': ''}, 'recipient_district')
        self.assert_rejected({'recipient_district': False}, 'recipient_district')

    def test_il_turkiye_disi(self):
        us_state = self.env['res.country.state'].search([('country_id.code', '=', 'US')], limit=1)
        if not us_state:
            self.skipTest('ABD ili verisi yok')
        self.assert_rejected({'recipient_state_id': us_state.id})

    def test_telefon_siniri(self):
        """rakam disi temizlenir; 10-16 hane; en az bir telefon."""
        self.assert_rejected({'recipient_phone': ''}, 'recipient_phone')
        self.assert_rejected({'recipient_phone': False}, 'recipient_phone')
        self.assert_rejected({'recipient_phone': '532123456'}, 'recipient_phone')          # 9 hane
        self.assert_rejected({'recipient_phone': 'abc-xyz'}, 'recipient_phone')            # 0 hane
        self.assert_accepted({'recipient_phone': '5321234567'})                            # 10
        self.assert_accepted({'recipient_phone': '+90 (532) 123-45-67'})                   # temizlenince 12
        self.assert_accepted({'recipient_phone': '1' * 16})
        self.assert_rejected({'recipient_phone': '1' * 17}, 'recipient_phone')
        self.assert_rejected({'recipient_phone': '532 123 45'}, 'recipient_phone')         # bosluklarla 8 hane

    def test_eposta_siniri(self):
        self.assert_accepted({'recipient_email': False})
        self.assert_accepted({'recipient_email': 'a' * 52 + '@example.com'})               # 64
        self.assert_rejected({'recipient_email': 'a' * 53 + '@example.com'}, 'recipient_email')   # 65

    def test_paket_sayisi_siniri(self):
        self.assert_rejected({'package_count': 0}, 'package_count')
        self.assert_rejected({'package_count': -1}, 'package_count')
        self.assert_accepted({'package_count': 1})
        self.assert_accepted({'package_count': 99})
        self.assert_rejected({'package_count': 100}, 'package_count')

    def test_agirlik_siniri(self):
        self.assert_rejected({'package_weight': 0.0}, 'package_weight')
        self.assert_rejected({'package_weight': -1.0}, 'package_weight')
        self.assert_accepted({'package_weight': 0.01})
        self.assert_accepted({'package_weight': 70.0})
        self.assert_rejected({'package_weight': 70.01}, 'package_weight')

    def test_referans_fatura_aciklama_uzunluk(self):
        self.assert_accepted({'origin_ref': 'R' * 40, 'invoice_no': 'F' * 20})
        self.assert_rejected({'origin_ref': 'R' * 41}, 'origin_ref')
        self.assert_rejected({'invoice_no': 'F' * 21}, 'invoice_no')
        self.assert_rejected({'description': 'D' * 121}, 'description')

    def test_coklu_hata_tek_mesajda(self):
        """KK-7: eksik/hatali alan adlari LISTELENIR (tek hata iletisinde)."""
        error = self.assert_rejected({'recipient_name': 'A', 'recipient_phone': '123', 'package_count': 0})
        for field in ('recipient_name', 'recipient_phone', 'package_count'):
            self.assertTrue(self._mentions(error, field), 'tek mesajda tum hatalar listelenmeli (%s): %s' % (field, error))

    def test_gecerli_gonderi_hata_vermez(self):
        shipment, error, calls = self.attempt({})
        self.assertIsNone(error)
        self.assertEqual((shipment.state, calls), ('created', 1))


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulKilitlerVeKurallar(DogrulamaBase):

    LOCKED = {
        'recipient_name': 'Veli Ali', 'recipient_phone': '05449998877', 'recipient_email': 'x@example.com',
        'recipient_street': 'Yeni Sokak 9', 'recipient_district': 'Altindag', 'package_count': 2,
        'package_weight': 3.0, 'cod_amount': 10.0, 'cod_method': 'cash',
    }

    def _blocked_or_unchanged(self, shipment, user, vals, msg):
        """write reddedilir (UserError/AccessError) VEYA etkisiz kalir; alan degeri degismemeli."""
        before = {k: shipment.sudo()[k] for k in vals}
        try:
            with self.env.cr.savepoint():
                shipment.with_user(user).write(vals)
        except (UserError, AccessError):
            pass
        shipment.invalidate_recordset()
        for key in vals:
            self.assertEqual(shipment.sudo()[key], before[key], '%s: %s degismemeli' % (msg, key))

    def test_kilitli_durumlarda_yazma_reddi(self):
        """KK-13: sending/uncertain/created/ve sonrasi/cancelled durumlarinda alanlar degistirilemez (form, RPC write)."""
        for state in ('sending', 'uncertain', 'created', 'in_transit', 'out_for_delivery', 'delivered', 'returned',
                      'exception', 'cancelled'):
            shipment = self.mk()
            shipment.sudo().write({'state': state})
            for field, value in self.LOCKED.items():
                for user in (self.user, self.manager):
                    with self.subTest(state=state, field=field, user=user.login):
                        self._blocked_or_unchanged(shipment, user, {field: value}, 'durum %s' % state)

    def test_kilitli_durumda_tum_alanlar_tek_yazimda(self):
        shipment = self.sent()
        before = {k: shipment[k] for k in self.LOCKED}
        with self.assertRaises((UserError, AccessError)):
            shipment.with_user(self.user).write(dict(self.LOCKED))
        shipment.invalidate_recordset()
        self.assertEqual({k: shipment[k] for k in self.LOCKED}, before)

    def test_draft_duzenlenebilir(self):
        shipment = self.mk()
        shipment.with_user(self.user).write({'recipient_street': 'Degisti Cad. 4', 'package_count': 3})
        self.assertEqual(shipment.recipient_street, 'Degisti Cad. 4')
        self.assertEqual(shipment.package_count, 3)

    def test_failed_duzenlenir_ve_yeniden_gonderilir(self):
        """KK-9 zemini: failed gonderi duzeltilip tekrar gonderilebilir."""
        self.provider.plan['send'] = [self.provider.err_send('9001', 'Adres hatali'),
                                      lambda s: self.provider.ok_send(shipment=s)]
        shipment = self.mk()
        shipment.action_send()
        self.assertEqual(shipment.state, 'failed')
        shipment.with_user(self.user).write({'recipient_street': 'Duzeltilmis Cad. 10'})
        self.provider.plan['send'] = lambda s: self.provider.ok_send(shipment=s)
        shipment.action_send()
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(self.provider.count('send'), 2)

    def test_sistem_alanlari_kullanici_yazamaz(self):
        """state/tracking_ref/... yalniz sistem (env.su) ile yazilir; kullanici yazimi reddedilir ya da etkisizdir."""
        shipment = self.mk()
        for field, value in (('state', 'created'), ('tracking_ref', '1ZSAHTE'), ('sent_at', '2026-01-01 00:00:00'),
                             ('error_message', 'x'), ('label_missing', True), ('name', 'KRG/2026/HACK')):
            with self.subTest(field=field):
                self._blocked_or_unchanged(shipment, self.user, {field: value}, 'sistem alani')
                self._blocked_or_unchanged(shipment, self.manager, {field: value}, 'sistem alani (yonetici)')
        self.assertEqual(shipment.state, 'draft')

    def test_olusturmada_sistem_alani_ve_default_context(self):
        """default_state / default_tracking_ref context PoC'u: olusturulan kayit 'draft' ve takipsiz olmali (veya red)."""
        Shipment = self.env['cargo.shipment'].with_user(self.user)
        attempts = [
            lambda: Shipment.create(dict(self.vals(), state='created', tracking_ref='1ZSAHTE')),
            lambda: Shipment.with_context(default_state='created', default_tracking_ref='1ZSAHTE').create(self.vals()),
        ]
        for attempt in attempts:
            record, error = self.try_call(attempt)
            if error is None:
                self.assertEqual(record.state, 'draft', 'create ile state ayarlanamaz')
                self.assertFalse(record.tracking_ref)
            else:
                self.assertIsInstance(error, UserError)

    def test_silme_kurallari(self):
        draft = self.mk()
        draft.with_user(self.user).unlink()
        self.assertFalse(draft.exists(), 'kullanici draft kaydi silebilir')
        failed = self.mk()
        failed.sudo().write({'state': 'failed'})
        with self.assertRaises((UserError, AccessError)):
            failed.with_user(self.user).unlink()
        failed.with_user(self.manager).unlink()
        self.assertFalse(failed.exists(), 'yonetici failed kaydi silebilir')
        created = self.sent()
        for user in (self.user, self.manager):
            with self.assertRaises((UserError, AccessError), msg='created gonderi silinemez (%s)' % user.login):
                created.with_user(user).unlink()
        self.assertTrue(created.exists())

    def test_kopya_guvenli(self):
        shipment = self.sent(origin_ref='ORJ-1')
        copy, error = self.try_call(lambda: shipment.copy())
        if error is None:
            self.assertEqual(copy.state, 'draft')
            self.assertFalse(copy.tracking_ref)
            self.assertFalse(copy.origin_ref)
            self.assertFalse(copy.label_pdf_id)

    def test_duz_kullanici_gonderi_goremez_yaratamaz(self):
        for user in (self.plain, self.plain_sales):
            with self.assertRaises(AccessError, msg=user.login):
                self.env['cargo.shipment'].with_user(user).create(self.vals())
            with self.assertRaises(AccessError, msg=user.login):
                self.env['cargo.shipment'].with_user(user).search([])

    def test_origin_ref_kismi_benzersiz(self):
        """Ayni origin_ref ile iki AKTIF gonderi olmaz; cancelled/failed olan sonrasinda yenisi acilabilir."""
        first = self.mk(origin_ref='SIP-0001')
        with mute_logger('odoo.sql_db'):
            with self.assertRaises(Exception) as ctx:
                self.mk(origin_ref='SIP-0001')
        self.assertIn(type(ctx.exception).__name__, ('IntegrityError', 'UniqueViolation', 'ValidationError', 'UserError'))
        first.sudo().write({'state': 'failed'})
        second = self.mk(origin_ref='SIP-0001')
        self.assertTrue(second.exists())
        second.sudo().write({'state': 'cancelled'})
        third = self.mk(origin_ref='SIP-0001')
        self.assertTrue(third.exists())
        # bos referans serbest
        self.mk(origin_ref=False)
        self.mk(origin_ref=False)

    def test_ad_benzersiz_ve_bicim(self):
        a, b = self.mk(), self.mk()
        self.assertRegex(a.name, r'^KRG/\d{4}/')
        self.assertNotEqual(a.name, b.name)
        self.assertLessEqual(len(a.name), 40)


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulFirmaVeOdp(DogrulamaBase):

    def test_varsayilan_firma(self):
        """KK-4: firma verilmezse sirket varsayilani; draft'ta degisince saglayici yeni firmayi gorur."""
        vals = self.vals()
        vals.pop('carrier_id')
        shipment = self.env['cargo.shipment'].with_user(self.user).create(vals)
        self.assertEqual(shipment.carrier_id, self.carrier)
        shipment.write({'carrier_id': self.carrier_y.id})
        shipment.action_send()
        self.assertEqual(self.provider.of('send')[0]['carrier_id'], self.carrier_y.id)
        self.assertEqual(shipment.carrier_id, self.carrier_y)

    def test_firma_kilitli_durumda_degismez(self):
        shipment = self.sent()
        with self.assertRaises((UserError, AccessError)):
            shipment.with_user(self.user).write({'carrier_id': self.carrier_y.id})
        self.assertEqual(shipment.carrier_id, self.carrier)

    def test_odp_saglayiciya_iletilir(self):
        """KK-16 (cekirdek): saglayici cod_amount ve cod_method degerlerini kayittan gorur; ODP yoksa 0."""
        self.assert_accepted({'cod_amount': 1249.90, 'cod_method': 'cash'})
        call = self.provider.of('send')[-1]
        self.assertAlmostEqual(call['cod_amount'], 1249.90, places=2)
        self.assertEqual(call['cod_method'], 'cash')
        self.assert_accepted({})
        call = self.provider.of('send')[-1]
        self.assertEqual(call['cod_amount'], 0.0)
        self.assertFalse(call['cod_method'])

    def test_odp_negatif_ve_yontemsiz(self):
        """KK-18."""
        self.assert_rejected({'cod_amount': -1.0, 'cod_method': 'cash'}, 'cod_amount')
        self.assert_rejected({'cod_amount': 100.0, 'cod_method': False}, 'cod_method')
        self.assert_accepted({'cod_amount': 0.0, 'cod_method': False})

    def test_odp_ust_sinir(self):
        """KK-19: sinir 500; 500 olur, 500.01 olmaz; 0 = sinirsiz."""
        self.company.cargo_cod_max_amount = 500.0
        self.assert_accepted({'cod_amount': 500.0, 'cod_method': 'cash'})
        self.assert_rejected({'cod_amount': 500.01, 'cod_method': 'cash'}, 'cod_amount')
        self.company.cargo_cod_max_amount = 0.0
        self.assert_accepted({'cod_amount': 1000000.0, 'cod_method': 'cash'})

    def test_odp_etkin_olmayan_firma(self):
        """KK-19b."""
        error = self.assert_rejected({'carrier_id': self.carrier_nocod.id, 'cod_amount': 100.0, 'cod_method': 'cash'},
                                     regex=r'(?i)kapıda ödeme etkin değil')
        self.assertIsNotNone(error)
        self.assert_accepted({'carrier_id': self.carrier_nocod.id})
        # firmayi sonradan degistirmek de atlatma olmamali
        shipment = self.mk(cod_amount=100.0, cod_method='cash')
        shipment.write({'carrier_id': self.carrier_nocod.id})
        before = self.provider.count('send')
        _, error = self.try_call(shipment.action_send)
        self.assertIsNotNone(error, "ODP'siz firmaya gecirilerek tahsilatli gonderi gonderilemez")
        self.assertEqual(self.provider.count('send'), before)

    def test_odp_tahsil_sekilleri(self):
        """KK-19c: varsayilan yalniz nakit; kart/cek reddedilir; yonetici acinca kabul edilir."""
        self.assert_accepted({'cod_amount': 100.0, 'cod_method': 'cash'})
        self.assert_rejected({'cod_amount': 100.0, 'cod_method': 'card'}, 'cod_method')
        self.assert_rejected({'cod_amount': 100.0, 'cod_method': 'check'}, 'cod_method')
        self.carrier.with_user(self.manager).write({'cargo_cod_allow_card': True})
        self.assert_accepted({'cod_amount': 100.0, 'cod_method': 'card'})
        self.assert_rejected({'cod_amount': 100.0, 'cod_method': 'check'}, 'cod_method')
        self.carrier.with_user(self.manager).write({'cargo_cod_allow_card': False, 'cargo_cod_allow_check': True})
        self.assert_accepted({'cod_amount': 100.0, 'cod_method': 'check'})
        self.assert_rejected({'cod_amount': 100.0, 'cod_method': 'card'}, 'cod_method')
        self.carrier.with_user(self.manager).write({'cargo_cod_allow_cash': False})
        self.assert_rejected({'cod_amount': 100.0, 'cod_method': 'cash'}, 'cod_method')

    def test_test_modu_bayragi(self):
        """test_mode = prod_environment kapali; canli firmada False."""
        shipment = self.mk()
        self.assertTrue(shipment.test_mode)
        self.carrier.prod_environment = True
        shipment2 = self.mk()
        self.assertFalse(shipment2.test_mode)
