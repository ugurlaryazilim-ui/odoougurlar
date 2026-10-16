"""Dal E / G14-G17: KK-E1..E7 icin STATIK kaynak kontrolleri.

Projede JS test altyapisi yok; gercek davranis Mod 2'de Playwright senaryolariyla
dogrulanir (03-kabul-testleri.md "Dal E"). Burada yalnizca kiriligan olmayan, desen
duzeyinde kontroller var: degisken adlarina degil, "kuyruk/sira-no/sifirlama/rozet"
varligina bakilir. Hepsi uygulama oncesi kirmizidir.
"""
import re

from odoo.tests import TransactionCase, tagged
from odoo.tools import file_open

SCREENS = 'ugurlar_barcode/static/src/js/screens/'


def _src(name):
    with file_open(SCREENS + name) as f:
        return f.read()


def _method_body(src, header_re):
    """`header_re` ile baslayan metodun govdesini (girinti 4 kapanisina kadar) dondurur."""
    m = re.search(header_re + r'.*?\{\n(.*?)\n    \}\n', src, re.S)
    return m.group(1) if m else None


@tagged('post_install', '-at_install')
class TestScanRacesStatic(TransactionCase):

    # --- KK-E1 ---
    def test_e1_putaway_pending_scan_is_a_queue_not_a_single_slot(self):
        src = _src('putaway.js')
        self.assertNotRegex(src, r'_pendingScan\s*=\s*(bc|barcode)\s*;',
                            'bekleyen okutma tek degiskene yaziliyor: 2. okutma 1.yi eziyor')
        self.assertRegex(src, r'(?i)(pending|queue)\w*\.push\(',
                         'bekleyen okutmalar kuyruga eklenmeli (push)')
        self.assertRegex(src, r'(?i)(pending|queue)\w*\.shift\(',
                         'kuyruk sirayla bosaltilmali (shift)')

    # --- KK-E4 ---
    def test_e4_shelf_transfer_loading_scan_not_silently_dropped(self):
        src = _src('shelf_transfer.js')
        self.assertNotRegex(src, r'if\s*\(\s*this\.state\.loading\s*\)\s*return\s*;',
                            'loading sirasinda gelen okutma sessizce atiliyor')

    def test_e4_shelf_transfer_error_plays_error_sound_and_vibrates(self):
        src = _src('shelf_transfer.js')
        self.assertIn('playError', src, 'sunucu hatasinda playError cagrilmali')
        self.assertRegex(src, r'vibrateError\(|navigator\.vibrate',
                         'sunucu hatasinda titresim kalmali')

    # --- KK-E6 ---
    def test_e6_shelf_move_all_has_explicit_change_action(self):
        src = _src('shelf_move_all.js')
        self.assertRegex(src, r'(Değiştir|Sıfırla)',
                         'bulunan raf alanini acmak icin "Degistir/Sifirla" eylemi gerekli')

    # --- KK-E2 ---
    def test_e2_sales_discount_requests_carry_sequence_number(self):
        src = _src('sales_discount.js')
        self.assertRegex(src, r'(?i)\w*(seq|requestId|reqId|reqNo|reqCounter)\w*',
                         'istek sira numarasi yok: gecikmeli eski yanit yeniyi ezebilir')

    # --- KK-E3 ---
    def test_e3_packing_scans_are_serialized(self):
        self.assertRegex(_src('packing.js'), r'(?i)queue|chain',
                         'packing okutmalari seri kuyrukta degil')

    def test_e3_batch_picking_scans_are_serialized(self):
        self.assertRegex(_src('batch_picking.js'), r'(?i)queue|chain',
                         'batch_picking okutmalari seri kuyrukta degil')

    # --- KK-E5 ---
    def test_e5_packing_inc_picking_id_reset_before_request(self):
        body = _method_body(_src('packing.js'), r'async onScan\(\)')
        self.assertTrue(body, 'packing.js onScan bulunamadi')
        before_first_await = body.split('await', 1)[0]
        self.assertRegex(before_first_await, r'inc_picking_id\s*=\s*null',
                         'inc_picking_id her okutmada istekten ONCE sifirlanmali (bayat S1 id)')

    def test_e5_backorder_confirm_text_contains_order_name(self):
        body = _method_body(_src('packing.js'), r'async onBackorder\(')
        self.assertTrue(body, 'packing.js onBackorder bulunamadi')
        m = re.search(r'confirm\((.*?)\)\)\s*return', body, re.S)
        self.assertTrue(m, 'confirm cagrisi bulunamadi')
        self.assertRegex(m.group(1), r'\$\{|\+\s*\w|\w\s*\+',
                         'onay metni sabit: siparis adi (degisken) icermiyor')

    # --- KK-E7 ---
    def test_e7_counting_error_row_has_badge(self):
        self.assertRegex(_src('counting.js'), r"status\s*===?\s*'error'",
                         'hata durumundaki sayim satiri rozet/mesaj gostermiyor')

    def test_e7_counting_uses_open_camera_scanner_fallback(self):
        src = _src('counting.js')
        self.assertRegex(src, r'import\s*\{[^}]*openCameraScanner[^}]*\}\s*from', 'openCameraScanner import edilmeli')
        self.assertRegex(src, r'openCameraScanner\(',
                         'BarcodeDetector yoksa openCameraScanner kullanilmali')
        # eski davranis: desteklenmiyorsa alert ile vazgecme
        self.assertNotRegex(src, r"alert\(\s*'Bu tarayıcı kamera ile barkod okumayı desteklemiyor",
                            'BarcodeDetector yokken alert ile vazgeciliyor')
