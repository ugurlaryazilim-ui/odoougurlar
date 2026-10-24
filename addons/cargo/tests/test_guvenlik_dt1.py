# -*- coding: utf-8 -*-
"""Düzeltme turu #1 güvenlik maddeleri (05-guvenlik): D-1 şirket taşıma, D-2 iş referansı, D-3 değişiklik izi."""
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .test_kabul_picking import PickingBase


@tagged('post_install', '-at_install', 'cargo')
class TestGuvenlikDt1(PickingBase):

    def api(self, reference, **kw):
        return self.env['cargo.shipment'].with_user(self.user).create_and_send(**dict(
            recipient_name='Ali Veli', phone='05321234567', street='Gercek adres Gul Sk. No:5', state=self.st('06'),
            district='Cankaya', reference=reference), **kw)

    # ------------------------------------------------------------------ Ö3
    def test_transferden_send_to_shipper_acik_hata(self):
        """Ö3 PoC: send_to_shipper ups_tr'de None[0] TypeError veriyordu; ``<tip>_send_shipping``'i olan tipte
        (burada fixed) kargo gönderisi açmadan Odoo'nun kendi gönderimini yapıyordu."""
        picking = self.make_picking()
        picking.carrier_id = self.carrier
        with self.assertRaisesRegex(UserError, 'kargo gönderisi formundan gönderin'):
            picking.send_to_shipper()
        with self.assertRaisesRegex(UserError, 'Kargo gönderisi formundan iptal edin'):
            picking.cancel_shipment()
        self.assertEqual(self.provider.count('send'), 0)
        self.assertEqual(self.provider.count('cancel'), 0)

    # ------------------------------------------------------------------ B-1
    def test_iptal_basarisinda_ceviri_uyarisi_yok(self):
        """B-1: staticmethod'daki ``_()`` env bulamayıp her iptalde 'no translation language' uyarısı basıyordu."""
        shipment = self.sent()
        with self.assertNoLogs('odoo.tools.translate', 'WARNING'):
            shipment.with_user(self.user).action_cancel()
            self.assertEqual(shipment._cargo_error_text(False, False), 'ayrıntı verilmedi')
        self.assertEqual(shipment.state, 'cancelled')

    # ------------------------------------------------------------------ B-2
    def test_il_ilce_alan_hatasinda_esleme_notu_tekrarlanmaz(self):
        for over, expected in (({'recipient_district': ''}, 'boş olamaz'),
                               ({'recipient_state_id': False}, 'Türkiye ili seçin')):
            with self.subTest(over=over):
                shipment = self.mk(**over)
                with self.assertRaisesRegex(UserError, expected) as caught:
                    shipment._cargo_check_ready()
                message = str(caught.exception)
                self.assertNotIn('İlçe belirsiz', message)
                self.assertNotIn('İl seçilmedi', message)
        # alan hatası yokken eşleme notu yine söylenir
        shipment = self.mk(recipient_district='Olmayan Ilce Adi')
        with self.assertRaisesRegex(UserError, 'İlçe eşleşmedi'):
            shipment._cargo_check_ready()

    # ------------------------------------------------------------------ Shopify sinyali
    def test_pazaryeri_kaydi_ile_baglanan_siparis_taninir(self):
        """05-inceleme: sipariş alanı boşken pazaryeri kaydı (shopify.order.sale_order_id) siparişi işaret eder.
        Kurulu olmayan modül yerine aynı biçimde siparişe bağlı sale.order.line ile sınanır."""
        picking = self.make_picking()
        self.assertFalse(picking.cargo_marketplace_name)
        with patch('odoo.addons.cargo.models.stock_picking._CARGO_MARKETPLACE_MODELS',
                   (('olmayan.model', 'x', 'Yok'), ('sale.order.line', 'order_id', 'Shopify'))):
            picking.invalidate_recordset(['cargo_marketplace_name'])
            self.assertEqual(picking.cargo_marketplace_name, 'Shopify')

    # ------------------------------------------------------------------ D-1
    def test_gonderi_erisilemeyen_sirkete_tasinamaz(self):
        other = self.env['res.company'].create({'name': 'D1 Diger Sirket'})
        shipment = self.mk()
        with self.assertRaises(AccessError):
            shipment.with_user(self.user).write({'company_id': other.id})
        self.assertEqual(shipment.company_id, self.env.company)
        # iki şirkete yetkili kullanıcı (ikisi de etkin) taşıyabilir
        self.user.sudo().company_ids = [(4, other.id)]
        shipment.with_user(self.user).with_context(
            allowed_company_ids=[self.env.company.id, other.id]).write({'company_id': other.id})
        self.assertEqual(shipment.company_id, other)

    # ------------------------------------------------------------------ D-2
    def test_baska_kaydin_referansi_donmez(self):
        """PoC: önceden aynı referansla açılmış (saldırgan) taslak create_and_send çağıranına dönmez."""
        squatter = self.mk(origin_ref='WH/OUT/99999', recipient_street='Saldirgan adresi Gul Sk.')
        with self.assertRaisesRegex(UserError, squatter.name):
            self.api('WH/OUT/99999')
        self.assertEqual(self.provider.count('send'), 0)

    def test_kaynaksiz_cagri_elle_acilmis_kaynaksiz_kaydi_donmez(self):
        """PoC (otomatik tarama): formla açılıp gönderilmiş kaynaksız kayıt, kaynaksız API çağrısına dönmez.

        Önceden (False, 0) == (False, 0) eşleşip saldırganın adresi/ODP'si çağırana dönüyordu."""
        squatter = self.sent(origin_ref='D2-KAYNAKSIZ', recipient_street='Saldirgan adresi Gul Sk.')
        self.assertEqual(squatter.state, 'created')
        with self.assertRaisesRegex(UserError, squatter.name):
            self.api('D2-KAYNAKSIZ')
        # kaynaksız API kaydı kaynaksız ikinci çağrıya döner (KK-API-2), kaynaklı çağrıya dönmez
        first = self.api('D2-API-KAYNAKSIZ')
        self.assertEqual(self.api('D2-API-KAYNAKSIZ'), first)
        with self.assertRaisesRegex(UserError, first.name):
            self.api('D2-API-KAYNAKSIZ', source=self.cust)
        self.assertEqual(self.provider.count('send'), 2)

    def test_ayni_kaynagin_gonderilmis_kaydi_doner(self):
        first = self.api('D2-KAYNAK', source=self.cust)
        self.assertEqual(first.state, 'created')
        self.assertEqual(self.api('D2-KAYNAK', source=self.cust), first)
        for source in (self.cust_landline, None):
            with self.subTest(source=source), self.assertRaisesRegex(UserError, first.name):
                self.api('D2-KAYNAK', source=source)
        self.assertEqual(self.provider.count('send'), 1)

    def test_ayni_kaynagin_taslagi_donmez(self):
        picking = self.make_picking()
        self.open_action(picking)
        draft = self.shipment_of(picking)
        with self.assertRaisesRegex(UserError, draft.name):
            self.api(picking.name, source=picking)
        self.assertEqual(self.provider.count('send'), 0)

    def test_yabanci_ayni_referans_transferi_kilitlemez_aciklar(self):
        picking = self.make_picking()
        squatter = self.mk(origin_ref=picking.name)
        with self.assertRaisesRegex(UserError, squatter.name):
            self.open_action(picking)
        self.assertFalse(picking.sudo().cargo_shipment_ids)
        # engelleyen kaldırılınca transferden gönderi açılır
        squatter.with_user(self.user).unlink()
        self.open_action(picking)
        self.assertEqual(self.shipment_of(picking).origin_ref, picking.name)

    def test_gorunmeyen_ayni_referans_kullanici_hatasi(self):
        """Ön denetimin göremediği (eşzamanlı) kayıtta UniqueViolation sunucu hatası değil UserError; işlem sağlam."""
        picking = self.make_picking()
        self.mk(origin_ref=picking.name)
        Shipment = type(self.env['cargo.shipment'])
        original = Shipment.search

        def blind_search(this, domain, *args, **kwargs):
            if domain and domain[0][0] == 'origin_ref':
                return this.browse()
            return original(this, domain, *args, **kwargs)
        with patch.object(Shipment, 'search', blind_search), \
                self.assertRaisesRegex(UserError, 'Birkaç saniye sonra'):
            self.open_action(picking)
        self.assertFalse(picking.sudo().cargo_shipment_ids)
        self.env.cr.execute('SELECT 1')     # savepoint geri alındı: işlem kullanılabilir

    # ------------------------------------------------------------------ D-3
    def test_alici_odp_firma_degisikligi_izlenir(self):
        shipment = self.mk()
        # NEDEN: mail.thread create'te aynı işlemdeki izlemeyi precommit'e kadar kapatır (_track_discard);
        # gerçek kullanımda oluşturma ve düzenleme ayrı isteklerdir.
        self.env.flush_all()
        self.env.cr.precommit.run()
        shipment.with_user(self.user).write({
            'cod_amount': 50.0, 'cod_method': 'cash', 'recipient_street': 'Yeni adres Gul Sk. No:9',
            'recipient_name': 'Veli Ali', 'recipient_phone': '05329998877', 'recipient_email': 'yeni@example.com',
            'recipient_state_id': self.st('34').id, 'recipient_district': 'Kadikoy', 'carrier_id': self.carrier_y.id,
        })
        self.env.flush_all()
        self.env.cr.precommit.run()
        tracked = self.env['mail.tracking.value'].sudo().search([
            ('mail_message_id.model', '=', 'cargo.shipment'), ('mail_message_id.res_id', '=', shipment.id)])
        names = set(tracked.field_id.mapped('name'))
        self.assertLessEqual({
            'cod_amount', 'cod_method', 'carrier_id', 'recipient_name', 'recipient_phone', 'recipient_email',
            'recipient_street', 'recipient_state_id', 'recipient_district'}, names)
        street = tracked.filtered(lambda value: value.field_id.name == 'recipient_street')
        self.assertEqual(street.old_value_char, 'Ataturk Mah. Gul Sk. No:5 D:3')
