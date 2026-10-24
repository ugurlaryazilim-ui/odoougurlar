# -*- coding: utf-8 -*-
"""G8: GERÇEK UPS il/ilçe verisi (1014 satır) ile eşleme - 02-tasarim §8 "Veri (Rev-1)".

NEDEN: cargo.shipment (G3) gerektirmez. Eşleme kuralları çekirdekte sahte veriyle sınanır
(cargo/tests/test_area.py); burada aynı kurallar gerçek kayıtlara uygulanır.
"""
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import convert_file

# (il plaka kodu, girdi, beklenen UPS ilçe kodu) - kodlar kaynak CSV'den elle doğrulandı.
BEKLENEN = [
    ('07', 'Demre', 5889), ('07', 'İbradı', 90), ('35', 'Menderes', 492), ('65', 'Edremit', 885),
    ('10', 'Edremit', 147), ('34', 'Eyüpsultan', 444), ('06', 'Kahramankazan', 69), ('26', 'Beylikova', 351),
    ('34', 'Büyükçekmece', 441), ('20', 'Pamukkale', 2390), ('20', 'Kale', 279), ('53', 'Çamlıhemşin', 729),
    ('21', 'Kayapınar / Diyarbakır', 2456), ('21', 'Kayapınar Diyarbakır', 2456), ('01', 'ÇUKUROVA', 5820),
    ('11', 'Merkez', None),   # Bilecik büyükşehir değil: MERKEZ kaydı var, sayı aşağıda ayrıca doğrulanır
]
ESLESMEMELI = [('21', 'Diyarbakır'), ('21', 'Merkez'), ('11', 'Bilecik'), ('07', 'Aksu'), ('34', 'Merkez'),
               ('34', 'İstanbul'), ('34', ''), ('06', 'Çankayaaa')]


@tagged('post_install', '-at_install', 'cargo_ups')
class TestUpsArea(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Area = cls.env['cargo.area']
        cls.areas = cls.Area.sudo().search([('provider', '=', 'ups_tr')])

    def st(self, code):
        return self.env.ref('base.state_tr_%s' % code)

    def match(self, code, text):
        return self.Area._match('ups_tr', self.st(code), text)

    def test_veri_sayilari(self):
        self.assertEqual(len(self.areas), 1014, 'KKTC (IlKodu=1000) hariç')
        self.assertEqual(len(self.areas.mapped('state_id')), 81)
        self.assertEqual(len(set(self.areas.mapped('area_code'))), 1014)
        for area in self.areas:
            self.assertEqual(area.city_code, int(area.state_id.code), area.name)
            self.assertTrue(area.match_keys, area.name)

    def test_ozdes_esleme(self):
        """Her kaydın kendi adı kendine döner; istisna yalnız büyükşehir MERKEZ / <İL> MERKEZ (22, sabit)."""
        metropolitan = self.Area._TR_METROPOLITAN_STATE_CODES
        normalize = self.Area._normalize
        istisna, hatali = 0, []
        for area in self.areas:
            key, state_key = normalize(area.name), normalize(area.state_id.name)
            if area.state_id.code in metropolitan and key in ('MERKEZ', state_key + 'MERKEZ'):
                istisna += 1
                self.assertFalse(self.Area._match('ups_tr', area.state_id, area.name),
                                 '%s / %s otomatik eşleşmemeli' % (area.state_id.name, area.name))
            elif self.Area._match('ups_tr', area.state_id, area.name) != area:
                hatali.append('%s / %s' % (area.state_id.name, area.name))
        self.assertEqual(hatali, [])
        # NEDEN: sayı sabit; veri yenilenirse bilinçli güncellenir (19 büyükşehirde MERKEZ + Antalya/Mersin/Sakarya <İL> MERKEZ).
        self.assertEqual(istisna, 22)

    def test_81_ilin_her_biri_esleniyor(self):
        for state in self.areas.mapped('state_id'):
            with self.subTest(il=state.name):
                kayitlar = self.areas.filtered(lambda a: a.state_id == state)
                self.assertTrue([a for a in kayitlar if self.Area._match('ups_tr', state, a.name) == a])

    def test_gercek_veri_ornekleri(self):
        for code, text, area_code in BEKLENEN:
            with self.subTest(il=code, girdi=text):
                found = self.match(code, text)
                self.assertTrue(found, 'eşleşmeli')
                self.assertEqual(found.state_id, self.st(code))
                if area_code:
                    self.assertEqual(found.area_code, area_code)
                else:
                    self.assertEqual(found.name, 'MERKEZ')

    def test_eslesmemesi_gerekenler(self):
        for code, text in ESLESMEMELI:
            with self.subTest(il=code, girdi=text):
                self.assertFalse(self.match(code, text))

    def test_belirsiz_adaylar(self):
        """Bursa 'Osmangazi / Yıldırım' iki ayrı kaydı gösterir: sessiz seçim yok."""
        self.assertFalse(self.Area._match('ups_tr', self.st('16'), 'Osmangazi / Yıldırım'))
        adaylar = self.Area._match_candidates('ups_tr', self.st('16'), 'Osmangazi / Yıldırım')
        self.assertEqual(len(adaylar), 2)

    def test_takma_adlar_yalniz_kesin_degisiklikler(self):
        """Antakya/Yenişehir/Aksu EKLENMEZ (CD-12); veri yalnız 3 kesin ad değişikliğidir."""
        aliased = self.areas.filtered('alias_names')
        self.assertEqual(sorted(aliased.mapped('area_code')), [69, 351, 444])
        self.assertEqual(sorted(aliased.mapped('name')), ['BEYLIKAHIR(B.OVA)', 'EYUP', 'KAZAN'])

    def test_yonetici_takma_adi_update_sonrasi_korunur(self):
        """noupdate=1 kanıtı: `-u` yolu (convert_file, mode=update) var olan kaydın takma adını ezmez."""
        yonetici = new_test_user(self.env, login='g8_alan_yonetici', groups='base.group_user,cargo.group_cargo_manager')
        eyup = self.env.ref('cargo_ups.area_444')
        eyup.with_user(yonetici).write({'alias_names': 'Eyüpsultan, Yönetici Eki'})
        convert_file(self.env, 'cargo_ups', 'data/cargo_area_alias_data.xml', {}, mode='update', noupdate=False)
        self.assertEqual(eyup.alias_names, 'Eyüpsultan, Yönetici Eki')
        self.assertEqual(self.match('34', 'Yönetici Eki'), eyup)
        # NEDEN: koruma dosya düzeyindeki noupdate="1" ile sağlanır; xmlid satırının noupdate bayrağı
        # kayıtları CSV oluşturduğu için False kalır ve bu beklenen durumdur (burada denetlenmez).
        csv_data = self.env['ir.model.data'].search([('module', '=', 'cargo_ups'), ('name', '=', 'area_5820')])
        self.assertFalse(csv_data.noupdate, 'CSV her -u ile yenilenir (kod/ad düzeltmeleri gelsin)')
