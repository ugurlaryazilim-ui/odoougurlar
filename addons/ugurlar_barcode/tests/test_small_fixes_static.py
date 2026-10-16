"""Dal F / G19 frontend: KK-F4 (ön yüz), F5, F6, F7 + Ö-E10, Ö-E12, D1 için STATİK kaynak kontrolleri.

Projede JS test altyapısı yok; gerçek davranış Mod 2'de Playwright senaryolarıyla doğrulanır
(03-kabul-testleri.md "Dal F", P-F1..P-F9). Burada yalnızca kırılganlığı düşük, desen düzeyinde
kontroller var: belirli değişken adlarına değil, "kalıcı saklama / boş olmayan catch / uyarı
metni / kilit koruması" varlığına bakılır. Hepsi uygulama öncesi kırmızıdır.
"""
import re

from odoo.tests import TransactionCase, tagged
from odoo.tools import file_open

JS = 'ugurlar_barcode/static/src/js/'


def _src(name):
    with file_open(JS + name) as f:
        return f.read()


def _method_body(src, header_re):
    """`header_re` ile başlayan 4 girintili metodun gövdesi (kapanış `\\n    }\\n`)."""
    m = re.search(header_re + r'.*?\{\n(.*?)\n    \}\n', src, re.S)
    return m.group(1) if m else None


def _catch_bodies(body):
    """Gövdedeki `catch (x) { ... }` bloklarının yorumsuz içerikleri (tek seviye süslü parantez)."""
    out = []
    for m in re.finditer(r'catch\s*(?:\(\s*\w*\s*\))?\s*\{', body):
        depth, i = 1, m.end()
        while i < len(body) and depth:
            depth += {'{': 1, '}': -1}.get(body[i], 0)
            i += 1
        inner = body[m.end():i - 1]
        inner = re.sub(r'/\*.*?\*/', '', inner, flags=re.S)
        inner = re.sub(r'//[^\n]*', '', inner)
        out.append(inner.strip())
    return out


VISIBLE = re.compile(r'state\.\w*(error|Error|msg|Msg|message|Message)\w*\s*=|scanMsg\s*=|alert\(|'
                     r'notification|\.add\(')


@tagged('post_install', '-at_install')
class TestSmallFixesStatic(TransactionCase):

    # assertRegex hata iletisine tüm kaynak dosyayı döker; burada yalnız verilen mesaj çıkar.
    def _has(self, text, pattern, msg):
        self.assertTrue(re.search(pattern, text), msg)

    def _hasnt(self, text, pattern, msg):
        self.assertFalse(re.search(pattern, text), msg)

    # ─── KK-F5: Hareketler filtresi korunur ────────────
    def test_f5_movements_does_not_clear_product_filter_after_search(self):
        body = _method_body(_src('screens/movements.js'), r'async loadMovements\(\)')
        self.assertTrue(body, 'movements.js loadMovements bulunamadı')
        self._hasnt(
            body, r"this\.state\.productBarcode\s*=\s*''",
            'loadMovements aramadan sonra ürün filtresini siliyor: Dönem/Tür değişince '
            'filtre sessizce düşüyor')

    def test_f5_movements_persists_filters_across_reload_and_tab_return(self):
        src = _src('screens/movements.js')
        self._has(src, r'sessionStorage|localStorage',
                         'filtre (barkod/dönem/tür) yeniden yüklemede ve sekme dönüşünde '
                         'korunmak için kalıcı saklanmalı')

    # ─── KK-F6: barcode_scanner ────────────────────────
    def test_f6_scanner_does_not_swallow_keys_on_non_text_targets(self):
        """Düğme (Space ile tıklama), select, contenteditable üzerindeki tuşlar yutulmamalı.
        Bugün: `if (!isBarcodeInput || timeDiff < 200) preventDefault` -> barkod alanı olmayan
        HER hedefte (ör. odaktaki düğme) tek karakterli tuş, Space dahil, iptal ediliyor."""
        src = _src('barcode_scanner.js')
        self._hasnt(src, r'!\s*isBarcodeInput\s*\|\|',
                            'barkod alanı olmayan hedefte tuş koşulsuz yutuluyor (Space düğmeyi '
                            'tetiklemiyor)')

    def test_f6_scanner_handles_space_explicitly(self):
        src = _src('barcode_scanner.js')
        self._has(src, r"""ev\.key\s*[!=]==?\s*['"] ['"]|['"]Space['"]|ev\.code""",
                         'Space tuşu için açık davranış yok')

    # ─── KK-F7: sessiz catch blokları ──────────────────
    def _assert_visible_catch(self, fname, header_re):
        body = _method_body(_src('screens/' + fname), header_re)
        self.assertTrue(body, '%s: metot bulunamadı' % fname)
        catches = _catch_bodies(body)
        self.assertTrue(catches, '%s: catch bloğu bulunamadı' % fname)
        for c in catches:
            self.assertTrue(c, '%s: catch bloğu boş/yalnız yorum (sessiz)' % fname)
            self._has(c, VISIBLE, '%s: catch kullanıcıya görünür mesaj vermiyor' % fname)

    def test_f7_packing_load_batch_list_catch_is_visible(self):
        self._assert_visible_catch('packing.js', r'async loadBatchList\(\)')

    def test_f7_labels_load_templates_catch_is_visible(self):
        self._assert_visible_catch('labels.js', r'async loadTemplates\(\)')

    def test_f7_label_designer_load_templates_catch_is_visible(self):
        self._assert_visible_catch('label_designer.js', r'async loadTemplates\(\)')

    # ─── KK-F4 (ön yüz): Nebim hatası ayrı mesaj ───────
    def test_f4_sales_discount_shows_separate_nebim_message(self):
        src = _src('screens/sales_discount.js')
        self.assertIn('nebim_error', src, 'sales_discount.js nebim_error alanını okumuyor')
        self._has(src, r"Nebim.{1,2}e iletilemedi",
                         "\"Nebim'e iletilemedi\" mesajı yok")

    def test_f4_sales_discount_customer_search_surfaces_nebim_error(self):
        src = _src('screens/sales_discount.js')
        m = re.search(r"api/search_customer.{0,900}", src, re.S)
        self.assertTrue(m, 'search_customer çağrısı bulunamadı')
        self.assertIn('nebim_error', m.group(0),
                      'müşteri aramasında Nebim hatası "sonuç yok" gibi görünmemeli')

    # ─── Ö-E10: asılı sunucu için çıkış yolu mesajı ────
    def _assert_escape_hint(self, fname):
        src = _src('screens/' + fname)
        for header in (r'\n    _onQueueTimeout\(', r'async _waitForOrphans\(\)'):
            body = _method_body(src, header)
            self.assertTrue(body, '%s: %s bulunamadı' % (fname, header))
            self._has(
                body, r'(?i)ekrandan\s+çıkıp\s+tekrar\s+gir',
                '%s %s: yanıt gelmezse "ekrandan çıkıp tekrar girin" yönlendirmesi yok'
                % (fname, header))

    def test_e10_packing_hung_server_message_tells_how_to_leave(self):
        self._assert_escape_hint('packing.js')

    def test_e10_batch_picking_hung_server_message_tells_how_to_leave(self):
        self._assert_escape_hint('batch_picking.js')

    # ─── Ö-E12: shelf_move_all çift tetik ──────────────
    def test_e12_shelf_move_all_duplicate_of_locked_shelf_is_silent(self):
        src = _src('screens/shelf_move_all.js')
        m = re.search(r'this\._scanHandler\s*=\s*\(barcode\)\s*=>\s*\{(.*?)\n        \};', src, re.S)
        self.assertTrue(m, '_scanHandler bulunamadı')
        handler = m.group(1)
        warn = handler.find('Raflar kilitli')
        self.assertGreater(warn, 0, 'kilitli raf uyarısı (R5) korunmalı')
        before = handler[:warn]
        self._has(
            before, r'barcode\s*===?\s*this\.state\.(target|source)Barcode|'
                    r'this\.state\.(target|source)Barcode\s*===?\s*barcode',
            'bulunan rafın barkodu yeniden gelirse (çift tetik) uyarıdan ÖNCE sessizce '
            'geçilmeli')

    # ─── D1: Tamamla geç yanıtı sonrası düğme ──────────
    def test_d1_complete_button_has_guard_beyond_loading_and_pending(self):
        """Tamamla başarıyla biten rotada 'Paketle & Tamamla' yeniden etkinleşmemeli. Düğmenin
        t-if/t-att-disabled ifadesi, all_matched/loading/longOpPending dışında bir durum
        bayrağına (ör. tamamlandı) bağlanmalı."""
        src = _src('screens/packing.js')
        i = src.find('ub-packing-complete-btn')
        self.assertGreater(i, 0)
        bar_start = src.rfind('<div class="ub-action-bar"', 0, i)
        attrs = src[bar_start:src.find('</button>', i)]
        flags = set(re.findall(r'state\.(\w+)', attrs)) - {'all_matched', 'loading', 'longOpPending'}
        self.assertTrue(flags, 'düğme yalnız all_matched/loading/longOpPending\'e bağlı: '
                               'done picking için yeniden etkinleşiyor')

    # ─── R-F1: packing_complete {error} yanıtı görünür ──
    def test_rf1_packing_apply_complete_result_shows_server_error(self):
        """packing_complete `{error}` (rota yok / eksik ürün) döndürür; ekran bunu göstermeli,
        zaman aşımı mesajını temizlemeli ve completeDone'ı true yapmamalı (yeniden deneme açık)."""
        body = _method_body(_src('screens/packing.js'), r'\n    _applyCompleteResult\(res\)')
        self.assertTrue(body, '_applyCompleteResult bulunamadı')
        m = re.search(r'if\s*\(\s*res\.error\s*\)\s*\{(.*?)\n        \}', body, re.S)
        self.assertTrue(m, '_applyCompleteResult res.error dalı yok')
        branch = m.group(1)
        self._has(branch, r'state\.error\s*=\s*res\.error', 'hata state.error\'a yazılmıyor')
        self._has(branch, r"state\.scanMsg\s*=\s*''", 'zaman aşımı mesajı (scanMsg) temizlenmiyor')
        self._has(branch, r"speak\(\s*'packing_error'\s*\)", 'hata sesi yok')
        self._has(branch, r'\breturn\b', 'dal erken dönmüyor')
        self._hasnt(branch, r'completeDone\s*=\s*true', 'hata yanıtında completeDone true olmamalı')
        # Dal başarı mantığından ÖNCE olmalı
        self.assertLess(body.find('res.error'), body.find('completeDone = true'))
