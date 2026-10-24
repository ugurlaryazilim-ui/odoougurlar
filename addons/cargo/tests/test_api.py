# -*- coding: utf-8 -*-
"""create_and_send birim testleri (G7; kabul: test_kabul_api). Kabul testlerinin kapsamadığı kardeş yollar."""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .kabul_taban import CargoKabulCase


@tagged('post_install', '-at_install', 'cargo')
class TestCreateAndSend(CargoKabulCase):

    def call(self, **over):
        kwargs = dict(recipient_name='Ali Veli', phone='05321234567', street='Ataturk Mah. Gul Sk. No:5',
                      state=self.st('06'), district='Cankaya')
        kwargs.update(over)
        return self.env['cargo.shipment'].with_user(self.user).create_and_send(**kwargs)

    def test_veritabani_mukerrer_referansi_engeller(self):
        """KK-API-2 DB düzeyi: API'yi atlayan doğrudan create de aynı açık referansı ikinci kez açamaz."""
        self.call(reference='API-DB')
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'):
            self.mk(origin_ref='API-DB')

    def test_bos_referans_aranmaz(self):
        """Boş/boşluk referans 'aynı kayıt' sayılmaz: her çağrı yeni gönderi açar."""
        first = self.call(reference='  ')
        second = self.call()
        self.assertNotEqual(first, second)
        self.assertFalse(first.origin_ref)
        self.assertEqual(self.provider.count('send'), 2)

    def test_referans_kirpilir(self):
        first = self.call(reference=' API-TRIM ')
        self.assertEqual(first.origin_ref, 'API-TRIM')
        self.assertEqual(self.call(reference='API-TRIM'), first)

    def test_belirsiz_kayit_yeniden_gonderilmez(self):
        """uncertain kayıt aynı referansla yeniden çağrılınca döner; kargo firmasına ikinci send gitmez."""
        self.provider.plan['send'] = self.provider.uncertain_send()
        first = self.call(reference='API-UNC')
        self.assertEqual(first.state, 'uncertain')
        self.assertEqual(self.call(reference='API-UNC'), first)
        self.assertEqual(self.provider.count('send'), 1)

    def test_dogrulama_hatasi_yakalansa_da_kayit_kalmaz(self):
        """Çağıran UserError'ı yakalayıp devam ederse taslak kayıt açık işlemde kalmaz (savepoint)."""
        before = self.env['cargo.shipment'].sudo().search_count([])
        with self.assertRaises(UserError):
            self.call(phone='123', reference='API-BAD')
        self.assertEqual(self.env['cargo.shipment'].sudo().search_count([]), before)
        # Aynı referans, düzeltilmiş veriyle açılabilir.
        self.assertEqual(self.call(reference='API-BAD').state, 'created')

    def test_eszamanli_mukerrer_kullanici_hatasi(self):
        """Arama birinciyi göremeyip INSERT indeks ihlaline çarparsa UserError (ham IntegrityError değil)."""
        self.call(reference='API-RACE')
        Shipment = type(self.env['cargo.shipment'])
        with patch.object(Shipment, 'search', lambda this, *a, **k: this.browse()), \
                mute_logger('odoo.sql_db'):
            self.assert_user_error(lambda: self.call(reference='API-RACE'), r'zaten var')
        self.assertEqual(self.provider.count('send'), 1)

    def test_kaynak_ve_musteri(self):
        partner = self.env['res.partner'].create({'name': 'Musteri'})
        shipment = self.call(partner=partner, source=partner, email='x@example.com')
        self.assertEqual(shipment.partner_id, partner)
        self.assertEqual((shipment.source_model, shipment.source_id), ('res.partner', partner.id))
        self.assertEqual(shipment.recipient_email, 'x@example.com')
        self.assertEqual(shipment.create_uid, self.user, 'kayıt gerçek kullanıcı adına açılır')
