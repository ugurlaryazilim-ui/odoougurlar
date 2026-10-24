# -*- coding: utf-8 -*-
"""Etiket PDF'i birim testleri (G5). Yerleşim/boyut kabul testlerindedir (test_kabul_etiket); burada kardeş yollar:
saf fonksiyon, sayfa sırası, kısmi etiket, PDF yan işinin çökmesi, bozuk PNG, yeniden basımda aynı ek, durum kapısı.
"""
import base64
from unittest.mock import patch

from odoo.tests import tagged

from ..models.cargo_label import MM, build_label_pdf
from .kabul_taban import CargoKabulCase, make_label_png, read_pdf

_MODULE = 'odoo.addons.cargo.models.cargo_shipment'
_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


@tagged('post_install', '-at_install', 'cargo')
class TestLabelPdf(CargoKabulCase):

    def pages(self, shipment):
        return read_pdf(base64.b64decode(shipment.label_pdf_id.datas))

    def pdf_attachments(self, shipment):
        return self.attachments(shipment, 'application/pdf')

    # -- saf fonksiyon
    def test_saf_fonksiyon_sayfa_ve_boyutlar(self):
        for size, expected in (('10x15', (100 * MM, 150 * MM)), ('a4', (210 * MM, 297 * MM))):
            with self.subTest(size=size):
                pages = read_pdf(build_label_pdf([make_label_png(0), make_label_png(1), make_label_png(2)], size))
                self.assertEqual(len(pages), 3)
                for page in pages:
                    self.assertAlmostEqual(page['width'], expected[0], delta=0.5)
                    self.assertAlmostEqual(page['height'], expected[1], delta=0.5)
                    self.assertEqual(len(page['images']), 1)

    # -- üretim yolları
    def test_pdf_png_sirasiyla_uretilir(self):
        """Sayfa sırası paket sırasıdır (<name>-1, -2, -3 = sağlayıcının verdiği sıra)."""
        captured = []
        real = build_label_pdf

        def spy(images, size):
            captured.append(list(images))
            return real(images, size)
        with patch(_MODULE + '.build_label_pdf', spy):
            self.sent(package_count=3)
        self.assertEqual(captured, [[make_label_png(0), make_label_png(1), make_label_png(2)]])

    def test_kismi_etiket_sayfa_sayisi_eldeki_png_kadar(self):
        self.provider.plan['send'] = lambda s: dict(self.provider.ok_send(shipment=s), labels=[make_label_png(0)])
        shipment = self.sent(package_count=2)
        self.assertEqual(len(self.pages(shipment)), 1)
        self.assertFalse(shipment.label_missing)

    def test_pdf_yan_isi_cokerse_png_kalir_basim_yeniden_uretir(self):
        with patch(_MODULE + '.build_label_pdf', side_effect=RuntimeError('pdf coktu')), \
                self.assertLogs(_MODULE, 'WARNING') as logs:
            shipment = self.sent(package_count=2)
        self.assertEqual(shipment.state, 'created')
        self.assertFalse(shipment.label_pdf_id)
        self.assertFalse(shipment.label_missing, 'PNG var: etiket yok sayılmaz')
        self.assertEqual(len(self.attachments(shipment, 'image/png')), 2)
        self.assertFalse(any('pdf coktu' in line for line in logs.output), 'istisna metni loga yazılmaz')
        shipment.action_print_label()
        self.assertEqual(len(self.pages(shipment)), 2)

    def test_yeniden_basim_ayni_eki_gunceller(self):
        shipment = self.sent()
        first = shipment.label_pdf_id
        shipment.action_print_label()
        shipment.action_print_label()
        self.assertEqual(shipment.label_pdf_id, first)
        self.assertEqual(self.pdf_attachments(shipment), first, 'gönderide tek PDF eki')

    def test_bozuk_png_basimda_kullanici_hatasi(self):
        self.provider.plan['send'] = lambda s: dict(self.provider.ok_send(shipment=s), labels=[_PNG_MAGIC + b'bozuk'])
        with self.assertLogs(_MODULE, 'WARNING'):
            shipment = self.sent()
        self.assertFalse(shipment.label_pdf_id)
        with self.assertLogs(_MODULE, 'WARNING'):
            self.assert_user_error(shipment.action_print_label, r'(?i)etiket')

    def test_iptal_edilmis_basilamaz(self):
        shipment = self.sent()
        shipment.action_cancel()
        self.assertEqual(shipment.state, 'cancelled')
        self.assert_user_error(shipment.action_print_label, r'(?i)etiket')

    def test_diger_durumlar_basilamaz(self):
        for state in ('sending', 'uncertain'):
            with self.subTest(state=state):
                shipment = self.mk()
                shipment.sudo().write({'state': state})
                self.assert_user_error(shipment.action_print_label)

    def test_basim_baska_gonderinin_etiketini_karistirmaz(self):
        a = self.sent()
        b = self.sent()
        a.action_print_label()
        b.action_print_label()
        self.assertNotEqual(a.label_pdf_id, b.label_pdf_id)
        self.assertEqual(self.pdf_attachments(a), a.label_pdf_id)

    def test_form_gorunumunde_dugme_ve_uyari(self):
        arch = self.env['cargo.shipment'].with_user(self.user).get_view(view_type='form')['arch']
        self.assertIn('action_print_label', arch)
        self.assertIn('label_missing', arch)

    # -- güvenlik: etikete yalnız sağlayıcı PNG'leri girer
    def test_yabanci_ayni_adli_png_etikete_girmez(self):
        shipment = self.sent(package_count=2)
        foreign = make_label_png(5)
        for name in ('%s-1.png' % shipment.name, '%s-9.png' % shipment.name):
            self.env['ir.attachment'].sudo().create({
                'name': name, 'raw': foreign, 'mimetype': 'image/png',
                'res_model': 'cargo.shipment', 'res_id': shipment.id})
        captured = []
        real = build_label_pdf

        def spy(images, size):
            captured.append(list(images))
            return real(images, size)
        with patch(_MODULE + '.build_label_pdf', spy):
            shipment.action_print_label()
        self.assertEqual(captured, [[make_label_png(0), make_label_png(1)]], 'yalnız sağlayıcı PNG dosyaları, paket sırasıyla')
        self.assertEqual(len(shipment.label_png_ids), 2)
        self.assertEqual(len(self.pages(shipment)), 2)

    def test_label_png_ids_kopyalanmaz(self):
        shipment = self.sent()
        self.assertTrue(shipment.label_png_ids)
        self.assertFalse(shipment.copy().label_png_ids)
