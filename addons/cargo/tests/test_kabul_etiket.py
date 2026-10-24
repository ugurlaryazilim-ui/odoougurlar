# -*- coding: utf-8 -*-
"""KABUL: etiket PDF'i (KK-20, KK-21).

Yesile donecegi gorev: G5. PDF yerlesimi PyPDF2/pypdf ile okunur (konteynerde yalniz PyPDF2 var; tasarimdaki
'pypdf' ifadesi bu nedenle test tarafinda iki kutuphaneyi de dener).

Olcu sozlesmesi (02-tasarim 1.5): 771x1033 px PNG yeniden ornekleme YOK, 96,5 x 137,2 mm fiziksel boyutta
(~273,5 x 388,9 pt) yerlestirilir. 10x15: sayfa 100x150 mm, etiket ortada; a4: sol ustte, 1 cm kenar.
"""
import base64

from odoo.exceptions import UserError
from odoo.tests import tagged

from .kabul_taban import BARCODE_BOX, CargoKabulCase, LABEL_PX, read_pdf

MM = 72.0 / 25.4
TOL = 1.5               # pt
IMG_W, IMG_H = 96.5 * MM, 137.2 * MM


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulEtiket(CargoKabulCase):

    def pdf_of(self, shipment):
        self.assertTrue(shipment.label_pdf_id, 'etiket PDF eki yok')
        return read_pdf(base64.b64decode(shipment.label_pdf_id.datas))

    def check_images_common(self, pages, count):
        self.assertEqual(len(pages), count, 'PDF sayfa sayisi = paket sayisi')
        for index, page in enumerate(pages):
            self.assertEqual(len(page['images']), 1, 'sayfa %d: tek etiket goruntusu' % (index + 1))
            image = page['images'][0]
            self.assertEqual((image['px_w'], image['px_h']), LABEL_PX, 'PNG yeniden ornekleme YOK (771x1033)')
            self.assertAlmostEqual(image['w'], IMG_W, delta=TOL)
            self.assertAlmostEqual(image['h'], IMG_H, delta=TOL)
            self.assertLess(image['rot'], 1e-6, 'goruntu donmemeli/egilmemeli')

    def test_10x15_yerlesim(self):
        self.assertEqual(self.company.cargo_label_size, '10x15')
        shipment = self.sent(package_count=3)
        pages = self.pdf_of(shipment)
        self.check_images_common(pages, 3)
        for page in pages:
            self.assertAlmostEqual(page['width'], 100 * MM, delta=TOL)
            self.assertAlmostEqual(page['height'], 150 * MM, delta=TOL)
            image = page['images'][0]
            self.assertAlmostEqual(image['x'], (page['width'] - IMG_W) / 2, delta=TOL, msg='yatay ortali')
            self.assertAlmostEqual(image['y'], (page['height'] - IMG_H) / 2, delta=TOL, msg='dikey ortali')

    def test_a4_yerlesim(self):
        self.company.cargo_label_size = 'a4'
        shipment = self.sent(package_count=2)
        pages = self.pdf_of(shipment)
        self.check_images_common(pages, 2)
        for page in pages:
            self.assertAlmostEqual(page['width'], 210 * MM, delta=TOL)
            self.assertAlmostEqual(page['height'], 297 * MM, delta=TOL)
            image = page['images'][0]
            self.assertAlmostEqual(image['x'], 10 * MM, delta=TOL, msg='sol kenar 1 cm')
            self.assertAlmostEqual(image['y'] + image['h'], page['height'] - 10 * MM, delta=TOL, msg='ust kenar 1 cm')

    def test_barkod_fiziksel_olculer(self):
        """KK-20: barkod >= 2 cm genis, >= 12 cm yuksek, yatay >= 200 dpi, ust/alt sessiz bolge >= 7 mm.

        TASARIM BELIRSIZLIGI: dikey cozunurluk 1033 px / 137,2 mm = ~191 dpi < 200 (V8 'en az 200 dpi'). Tasarim
        kasitli esnetmeyi kabul eder; test yatay >= 200, dikey >= 190 dpi'yi sinar ve bunu rapora yazar.
        """
        for size in ('10x15', 'a4'):
            with self.subTest(size=size):
                self.company.cargo_label_size = size
                shipment = self.sent()
                page = self.pdf_of(shipment)[0]
                image = page['images'][0]
                x0, y0, x1, y1 = BARCODE_BOX
                scale_x = image['w'] / image['px_w']
                scale_y = image['h'] / image['px_h']
                bar_w_cm = (x1 - x0) * scale_x / 72.0 * 2.54
                bar_h_cm = (y1 - y0) * scale_y / 72.0 * 2.54
                self.assertGreaterEqual(bar_w_cm, 2.0 - 0.02, 'barkod genisligi %.2f cm' % bar_w_cm)
                self.assertGreaterEqual(bar_h_cm, 12.0 - 0.02, 'barkod yuksekligi %.2f cm' % bar_h_cm)
                dpi_x = image['px_w'] / (image['w'] / 72.0)
                dpi_y = image['px_h'] / (image['h'] / 72.0)
                self.assertGreaterEqual(dpi_x, 200.0 - 0.5, 'yatay dpi %.1f' % dpi_x)
                self.assertGreaterEqual(dpi_y, 190.0, 'dikey dpi %.1f' % dpi_y)
                top_edge = image['y'] + image['h'] - y0 * scale_y
                bottom_edge = image['y'] + image['h'] - y1 * scale_y
                quiet_top_mm = (page['height'] - top_edge) / MM
                quiet_bottom_mm = bottom_edge / MM
                self.assertGreaterEqual(quiet_top_mm, 7.0, 'ust sessiz bolge %.1f mm' % quiet_top_mm)
                self.assertGreaterEqual(quiet_bottom_mm, 7.0, 'alt sessiz bolge %.1f mm' % quiet_bottom_mm)

    def test_yeniden_basim_saglayiciyi_cagirmaz(self):
        """KK-21: her basim PDF'i saklanan PNG'lerden yeniden uretir; saglayiciya cagri yok; chatter'a yazilir."""
        shipment = self.sent(package_count=2)
        calls_before = len(self.provider.calls)
        pngs_before = self.attachments(shipment, 'image/png').ids
        for _ in range(2):
            action = shipment.action_print_label()
            self.assertTrue(isinstance(action, dict), 'indirme eylemi donmeli')
            self.assertIn(str(shipment.label_pdf_id.id), repr(action), 'eylem PDF ekinin id\'sini icermeli')
        self.assertEqual(len(self.provider.calls), calls_before, 'basim saglayiciyi cagirmaz')
        self.assertEqual(self.attachments(shipment, 'image/png').ids, pngs_before, 'PNG ekleri degismemeli')
        self.assertEqual(self.chatter(shipment).count('Etiket basıldı'), 2, 'her basim chatter\'a yazilir')
        self.check_images_common(self.pdf_of(shipment), 2)

    def test_yeniden_basimda_yeni_boyut(self):
        """Yonetici ayari degistirip yeniden basinca PDF yeni boyutla uretilir (PDF onbellegi yok)."""
        shipment = self.sent()
        self.assertAlmostEqual(self.pdf_of(shipment)[0]['width'], 100 * MM, delta=TOL)
        self.company.cargo_label_size = 'a4'
        shipment.action_print_label()
        self.assertAlmostEqual(self.pdf_of(shipment)[0]['width'], 210 * MM, delta=TOL)
        self.company.cargo_label_size = '10x15'
        shipment.action_print_label()
        self.assertAlmostEqual(self.pdf_of(shipment)[0]['width'], 100 * MM, delta=TOL)

    def test_kargoya_verilmis_gonderi_basilabilir(self):
        shipment = self.sent()
        shipment.sudo().write({'state': 'in_transit'})
        action = shipment.action_print_label()
        self.assertTrue(action)

    def test_taslak_ve_hatali_basilamaz(self):
        draft = self.mk()
        self.assert_user_error(draft.action_print_label)
        failed = self.mk()
        failed.sudo().write({'state': 'failed'})
        self.assert_user_error(failed.action_print_label)

    def test_etiketi_olmayan_gonderi(self):
        self.provider.plan['send'] = lambda s: dict(self.provider.ok_send(shipment=s), labels=[])
        shipment = self.sent()
        self.assertTrue(shipment.label_missing)
        self.assert_user_error(shipment.action_print_label, r'(?i)etiket')

    def test_yetkisiz_basim(self):
        shipment = self.sent()
        with self.assertRaises(Exception) as ctx:
            shipment.with_user(self.plain).action_print_label()
        self.assertIsInstance(ctx.exception, UserError)
