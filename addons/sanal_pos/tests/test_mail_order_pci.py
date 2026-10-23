# -*- coding: utf-8 -*-
"""Mail Order PCI statik testleri (KK-17): kart verisi için kalıcı alan, rota parametresi veya
sağlayıcı çağrı parametresi yoktur.

Eşleştirici (``is_card_field``) kendi birim testiyle sınanır; "olumlu çapa" olarak yeni
``sanal.pos.mail.order.wizard`` modelinin ve kart sayfası rotasının varlığı denetlenir.
"""
import ast
import base64
import hashlib
import inspect
import os
import re

from odoo import http
from odoo.tests import tagged

from .common import SanalPosCase

ALLOWED = {'card_last4', 'expires_at', 'expiry_hours'}
TOKEN_RES = [re.compile(p) for p in (
    r'(^|_)(pan|cvv|cvc|cvv2)(_|$)', r'card_?(no|number|owner|holder|pan|cvv|token)',
    r'expiry_?(month|year|date)', r'name_?on_?card', r'cardholder', r'(^|_)card_?exp')]


def is_card_field(name):
    if name in ALLOWED:
        return False
    return any(rx.search(name.lower()) for rx in TOKEN_RES)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestPciStatic(SanalPosCase):

    def sanal_models(self):
        return [m for name, m in self.env.registry.items() if name.startswith('sanal.pos.')]

    def test_eslestirici_birimi(self):
        for bad in ('pan', 'cvv', 'cvc', 'card_pan', 'card_number', 'card_owner', 'card_holder', 'cardholder_name',
                    'expiry_month', 'expiryYear', 'name_on_card', 'customer_pan', 'cvv2', 'card_no'):
            self.assertTrue(is_card_field(bad), bad)
        for good in ('company_id', 'card_last4', 'expires_at', 'expiry_hours', 'panel_id', 'span', 'company_ids',
                     'customer_name', 'provider_token', 'paid_amount', 'installment_count', 'channel_sms'):
            self.assertFalse(is_card_field(good), good)

    def test_modellerde_kart_alani_yok(self):
        names = sorted(m._name for m in self.sanal_models())
        self.assertIn('sanal.pos.mail.order.wizard', names)        # olumlu çapa: yeni model var
        self.assertIn('sanal.pos.payment', names)
        self.assertIn('sanal.pos.payment.attempt', names)   # Aşama 3 (K-17)
        offenders = []
        for model in self.sanal_models():
            offenders += ['%s.%s' % (model._name, f) for f in model._fields if is_card_field(f)]
        self.assertEqual(offenders, [])

    def test_veritabani_sutunlarinda_kart_alani_yok(self):
        self.env.cr.execute("""SELECT table_name, column_name FROM information_schema.columns
                                WHERE table_schema = 'public' AND table_name LIKE 'sanal_pos_%'""")
        rows = self.env.cr.fetchall()
        self.assertTrue([r for r in rows if r[0] == 'sanal_pos_payment'])
        self.assertEqual(['%s.%s' % r for r in rows if is_card_field(r[1])], [])

    @staticmethod
    def sanal_pos_controllers():
        """sanal_pos'un tüm ``http.Controller`` alt sınıfları (yeni controller dosyası da kapsanır)."""
        import importlib
        import pkgutil
        from odoo.addons.sanal_pos import controllers as pkg
        # NEDEN: __init__'e eklenmemiş bir dosya da taransın; yalnız import edilmiş sınıflar görünür
        # (rota kaydı da aynı importa bağlı olduğundan eksik import zaten rota üretmez).
        for info in pkgutil.iter_modules(pkg.__path__):
            importlib.import_module('%s.%s' % (pkg.__name__, info.name))
        found, todo = [], list(http.Controller.__subclasses__())
        while todo:
            cls = todo.pop()
            todo.extend(cls.__subclasses__())
            if cls.__module__.startswith('odoo.addons.sanal_pos.controllers'):
                found.append(cls)
        return found

    def test_rota_imzalarinda_kart_parametresi_yok(self):
        found, offenders = set(), []
        controllers = self.sanal_pos_controllers()
        modules = {c.__module__.rsplit('.', 1)[-1] for c in controllers}
        self.assertTrue({'main', 'mail_order'} <= modules, modules)      # tarayıcı tüm dosyaları görüyor
        for cls in controllers:
            for name, fn in inspect.getmembers(cls, inspect.isfunction):
                routing = getattr(fn, 'original_routing', None)
                if not routing:
                    continue
                routes = routing.get('routes', [])
                found.update(routes)
                params = list(inspect.signature(fn).parameters)
                offenders += ['%s.%s(%s)' % (cls.__name__, name, p) for p in params if is_card_field(p)]
                offenders += ['%s: %s' % (name, r) for r in routes if is_card_field(r.rsplit('/', 1)[-1])]
        # olumlu çapalar: kart rotası (mail_order.py) ve dönüş rotası (main.py) taranmış olmalı
        self.assertIn('/sanal_pos/mail_order/pay/<int:payment_id>', found)
        self.assertIn('/sanal_pos/mail_order/result', found)
        self.assertIn(BIN_PATH, found)           # A2: BIN ucu (yalnız ``payment_id`` ve ``bin`` alır)
        self.assertIn('/sanal_pos/paratika/mo_return', found)
        self.assertEqual(offenders, [])

    def test_saglayici_tum_metotlari_kart_parametresi_gondermez(self):
        provider = self.env['sanal.pos.provider.paratika']
        payment = self.make_mail_order(state='sending', provider_token=False, sent_at=False, expires_at=False)
        provider.create_session(payment)
        provider.query_installments(payment)
        provider.direct_post_url(self.make_mail_order(provider_token='T', invoice_no='PCI-2'))
        provider.query_status(payment)
        # link ve iade yolu da (G5 teslimi: sağlayıcının tüm arayüz metotları)
        link = self.make_payment(state='sending', invoice_no='PCI-3', provider_token=False)
        provider.create_link(link)
        provider.find_link(link)
        provider.resend(link, ['sms'])
        provider.cancel_link(link)
        paid = self.make_paid(self.make_payment(invoice_no='PCI-4'))
        provider.void(paid, self.make_refund_line(paid, paid.amount, kind='void', state='processing'))
        paid2 = self.make_paid(self.make_payment(invoice_no='PCI-5'), tran_ref='T5')
        provider.refund(paid2, self.make_refund_line(paid2, 10.0, state='processing'))
        self.assertGreaterEqual(len(self.mock.calls), 9)
        for call in self.mock.calls:
            for key in call.params:
                self.assertFalse(key.upper().startswith('CARD'), key)
                self.assertNotIn(key.upper(), ('PAN', 'CVV', 'CVC', 'NAMEONCARD', 'EXPIRYMONTH', 'EXPIRYYEAR'))

    def test_manifest_surumu_ve_kart_icerigi_yok(self):
        import ast
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '__manifest__.py')
        with open(path, encoding='utf-8') as fh:
            manifest = ast.literal_eval(fh.read())
        self.assertEqual(manifest['version'], '19.0.1.4.0')


# ======================================================================================
# Aşama 1: kart sayfası betiği statik denetimi (KK-1.15, NFR-1.1, NFR-1.2, PCI 6.4.3/11.6.1)
# ======================================================================================
MODULE_DIR = os.path.dirname(os.path.dirname(__file__))
JS_FILE = os.path.join(MODULE_DIR, 'static', 'src', 'js', 'mail_order_card.js')
CSS_FILE = os.path.join(MODULE_DIR, 'static', 'src', 'css', 'mail_order.css')
# NEDEN: NFR-1.1 betik bütçesi; Aşama 2'de BIN sorgusuyla 8 KB'tan 12 KB'a çıktı, aşılırsa sınır
# yükseltilmez, tasarım mimara döner (bkz. KARARLAR K-16 eki).
SCRIPT_MAX_BYTES = 12288
BIN_PATH = '/sanal_pos/mail_order/bin'

# PCI 11.6.1 değişiklik tespiti: betik her değiştiğinde bu sabit KOD İNCELEMESİNDE ayrıca güncellenir
# (README "Ödeme sayfası script envanteri" ve çalışma anı onayı tools.MAIL_ORDER_SCRIPT_SHA256 aynı
# değeri yazar; eşitlik test edilir).
# DIKKAT: betik diff'i ile bu sabitin diff'i AYNI commit'te ve aynı incelemede görünür (A1-G3 sözleşmesi);
# sabiti incelemesiz ayrı bir commit'le değiştirmek PCI 6.4.3/11.6.1 kontrolünü boşa çıkarır.
SCRIPT_SHA256 = 'shzuFBD/bBX6iqmULEIgTR1nKugJ2sWS6Fr6eosXgo0='

# Yasak belirteçler (KK-1.15 + tasarım §3.5/7). Yorum satırları çıkarıldıktan sonra aranır.
FORBIDDEN_TOKENS = {
    # 'fetch': Aşama 2'de TEK çağrı serbest (BIN ucu); bkz. test_kk_2_fetch_tek_cagri_yalniz_bin_ucu
    'XMLHttpRequest': r'XMLHttpRequest',
    'sendBeacon': r'sendBeacon',
    'WebSocket': r'WebSocket',
    'EventSource': r'EventSource',
    'import(': r'\bimport\s*\(',
    'import/export': r'^\s*(import|export)\b',
    'eval': r'\beval\b',
    'Function(': r'\bFunction\s*\(',
    "setTimeout/setInterval('metin')": r'\bset(Timeout|Interval)\s*\(\s*[\'"`]',
    'localStorage': r'localStorage',
    'sessionStorage': r'sessionStorage',
    'indexedDB': r'indexedDB',
    'document.cookie': r'document\s*\.\s*cookie',
    'console.': r'\bconsole\s*\.',
    'postMessage': r'postMessage',
    'window.open': r'window\s*\.\s*open',
    'innerHTML': r'innerHTML',
    'outerHTML': r'outerHTML',
    'insertAdjacentHTML': r'insertAdjacentHTML',
    'document.write': r'document\s*\.\s*write',
    'createElement': r'createElement',
    'new Image': r'\bnew\s+Image\b',
    '.src': r'\.src\b',
    '.href': r'\.href\b',
    'FormData': r'\bFormData\b',
    'setAttribute(src|href|on*|srcdoc)': r'setAttribute\s*\(\s*[\'"](src|href|srcdoc|on\w+)[\'"]',
    'form.action/formAction atama': r'\.(action|formAction)\s*=[^=]',
    'importScripts/Worker': r'importScripts|\bnew\s+(Shared)?Worker\b',
}
RAW_FORBIDDEN = {'</script': r'(?i)</script', '<!--': r'<!--'}


def _read_js():
    with open(JS_FILE, 'rb') as handle:
        return handle.read()


def _strip_comments(source):
    """Blok ve tam satır ``//`` yorumlarını siler (yorumdaki açıklama yasak sözcük sayılmasın)."""
    source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    return re.sub(r'(?m)^\s*//.*$', '', source)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestCardScriptStatic(SanalPosCase):

    def source(self):
        self.assertTrue(os.path.isfile(JS_FILE), 'betik dosyası yok: static/src/js/mail_order_card.js')
        return _read_js().decode('utf-8')

    def test_nfr_1_1_boyut_12_kb_ve_utf8(self):
        self.source()
        self.assertEqual(SCRIPT_MAX_BYTES, 12288)
        self.assertLessEqual(len(_read_js()), 12288, 'betik 12 KB\'ı (sıkıştırmasız) aşmamalı (NFR-1.1, K-16 eki)')
        _read_js().decode('utf-8')

    @staticmethod
    def _fetch_call(code):
        """``fetch(`` çağrısının parantez içi metni (dengeli parantez); yoksa None."""
        start = re.search(r'\bfetch\s*\(', code)
        if not start:
            return None
        depth, index = 1, start.end()
        while depth and index < len(code):
            depth += {'(': 1, ')': -1}.get(code[index], 0)
            index += 1
        return code[start.end():index - 1]

    def test_kk_2_fetch_tek_cagri_yalniz_bin_ucu(self):
        """A2-G3: KK-1.15 yasak listesinde ``fetch`` yalnız BIN çağrısı için serbest: tek çağrı, tek
        sabit adres, kart alanı yok; kimlik bilgisi/yönlendirme/önbellek/referrer ayarları sabit."""
        code = _strip_comments(self.source())
        self.assertEqual(len(re.findall(r'\bfetch\b', code)), 1, 'fetch tam bir kez geçmeli')
        call = self._fetch_call(code)
        self.assertIsNotNone(call, 'fetch( çağrısı yok')
        self.assertEqual(code.count(BIN_PATH), 1, 'BIN yolu betikte tek sabit olarak geçmeli')
        for pattern, why in (
                (r"method\s*:\s*['\"]POST['\"]", 'method POST'),
                (r"credentials\s*:\s*['\"]same-origin['\"]", 'credentials same-origin'),
                (r"redirect\s*:\s*['\"]error['\"]", 'redirect error'),
                (r"cache\s*:\s*['\"]no-store['\"]", 'cache no-store'),
                (r"referrerPolicy\s*:\s*['\"]no-referrer['\"]", 'referrerPolicy no-referrer'),
                (r"Content-Type['\"]?\s*:\s*['\"]application/json['\"]", 'Content-Type json'),
                (r"JSON\.stringify", 'gövde JSON.stringify'),
                (r"\bsignal\b", 'AbortController signal')):
            self.assertRegex(call, pattern, why)
        self.assertNotRegex(call, r'(?i)\bmode\s*:', 'mode: no-cors/cors verilmez')
        # BIN çağrısının gövdesi yalnız payment_id ve bin taşır; kart alanı adı geçmez
        for token in ('pan', 'cvv', 'cardOwner', 'expiryMonth', 'expiryYear'):
            self.assertNotRegex(call, r'(?i)\b%s\b' % token, 'fetch çağrısında kart alanı: %s' % token)
        self.assertIn('AbortController', code, 'zaman aşımı için AbortController (6 sn) gerekir')
        self.assertRegex(code, r'\b6000\b|\b6\s*\*\s*1000\b', '6 sn zaman aşımı sabiti')

    def test_kk_2_diger_ag_yuzeyleri_yasak_kalir(self):
        code = _strip_comments(self.source())
        for token in ('XMLHttpRequest', 'sendBeacon', 'WebSocket', 'EventSource', 'importScripts',
                      'localStorage', 'sessionStorage', 'indexedDB', 'document.cookie', 'postMessage'):
            self.assertNotIn(token, code, token)
        self.assertNotRegex(code, r'\bnew\s+Image\b')

    def test_kk_1_15_yasak_belirtec_yok(self):
        code = _strip_comments(self.source())
        found = [name for name, pattern in FORBIDDEN_TOKENS.items()
                 if re.search(pattern, code, re.M)]
        self.assertEqual(found, [], 'betikte yasak belirteç(ler)')

    def test_kk_1_15_script_blogunu_bozan_dizgi_yorumlarda_da_yok(self):
        raw = self.source()
        found = [name for name, pattern in RAW_FORBIDDEN.items() if re.search(pattern, raw)]
        self.assertEqual(found, [])

    def test_kk_1_15_cvv_degeri_okunmaz(self):
        code = _strip_comments(self.source())
        offenders = []
        for segment in re.split(r'[;\n]', code):
            if re.search(r'cvv', segment, re.I) and re.search(r'\.value\b|\.valueAsNumber\b', segment):
                offenders.append(segment.strip())
        self.assertEqual(offenders, [], 'cvv ile .value aynı ifadede geçemez')

    def test_betik_tek_iife_strict_ve_dikkat_yorumu(self):
        raw = self.source()
        code = _strip_comments(raw)
        self.assertIn("'use strict'", code.replace('"use strict"', "'use strict'"))
        self.assertRegex(code.lstrip(), r'^\(function\s*\(|^\(\s*\(\s*\)\s*=>|^\(\s*function')
        self.assertIn('DIKKAT', raw[:2000], 'başındaki DIKKAT yorumu yok')
        self.assertIn('K-16', raw)

    def test_betik_kullanici_girdisini_dom_disina_cikarmaz_ag_yok(self):
        code = _strip_comments(self.source())
        # ağ/yönlendirme yüzeyleri (yasak listesinin tamamlayıcısı): konum değiştirme, form hedefi
        for pattern in (r'location\s*[.=]', r'\bnavigator\s*\.', r'\.target\s*=[^=]'):
            self.assertIsNone(re.search(pattern, code), pattern)

    def test_manifest_assets_betik_ve_css_icermez(self):
        path = os.path.join(MODULE_DIR, '__manifest__.py')
        with open(path, encoding='utf-8') as handle:
            manifest = ast.literal_eval(handle.read())
        listed = [entry for bundle in manifest.get('assets', {}).values() for entry in bundle]
        for entry in listed:
            self.assertNotIn('mail_order_card', str(entry))
            self.assertNotIn('mail_order.css', str(entry))
        self.assertIn('sanal_pos/static/src/js/scan_char_field.js', listed)      # olumlu çapa

    def test_pci_11_6_1_betik_sha256_sabiti_dosyayla_eslesir(self):
        self.source()
        normalized = _read_js().decode('utf-8').lstrip('﻿').replace('\r\n', '\n').replace('\r', '\n')
        actual = base64.b64encode(hashlib.sha256(normalized.encode('utf-8')).digest()).decode('ascii')
        self.assertIsNotNone(
            SCRIPT_SHA256, 'SCRIPT_SHA256 henüz yazılmadı. Betik tamamlanıp kod incelemesinden geçince '
                           'bu dosyadaki sabite şu değer yazılır: %s' % actual)
        self.assertEqual(
            SCRIPT_SHA256, actual,
            'Betik değişti. PCI 11.6.1: bu sabit YALNIZ kod incelemesinden sonra güncellenir '
            '(README script envanteri de). Yeni değer: %s' % actual)

    def test_pci_11_6_1_onay_hashi_tek_deger_test_tools_readme_d2(self):
        """D-2: çalışma anı onayı (tools), test sabiti ve README envanteri aynı değeri taşır."""
        from odoo.addons.sanal_pos import tools
        self.assertEqual(tools.MAIL_ORDER_SCRIPT_SHA256, SCRIPT_SHA256)
        with open(os.path.join(MODULE_DIR, 'README.md'), encoding='utf-8') as handle:
            self.assertIn('SCRIPT_SHA256 = %s' % SCRIPT_SHA256, handle.read())

    def test_nfr_1_4_readme_script_envanteri_ve_eski_cumle_kalkti(self):
        with open(os.path.join(MODULE_DIR, 'README.md'), encoding='utf-8') as handle:
            readme = handle.read()
        self.assertIn('mail_order_card.js', readme)
        self.assertRegex(readme.lower(), r'script envanteri')
        self.assertNotIn('kart sayfasında hiç `<script>` yok', readme)

    def test_nfr_1_2_tools_hash_dosyadan_turetilir(self):
        from odoo.addons.sanal_pos import tools
        text, digest = tools.mail_order_script()
        normalized = _read_js().decode('utf-8').lstrip('﻿').replace('\r\n', '\n').replace('\r', '\n')
        self.assertEqual(text, normalized)
        self.assertEqual(digest, base64.b64encode(hashlib.sha256(text.encode('utf-8')).digest()).decode('ascii'))


# ======================================================================================
# Aşama 1: CSS sözleşmesi (KK-1.1, KK-1.9, KK-1.13b) - tarayıcıda görünüm Playwright ile doğrulanır
# ======================================================================================
def _luminance(color):
    color = color.strip().lower()
    match = re.fullmatch(r'#([0-9a-f]{3}|[0-9a-f]{6})', color)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = ''.join(c * 2 for c in digits)
        rgb = [int(digits[i:i + 2], 16) for i in (0, 2, 4)]
    else:
        match = re.fullmatch(r'rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+).*\)', color)
        if not match:
            raise AssertionError('renk ayrıştırılamadı (hex ya da rgb() kullanın): %r' % color)
        rgb = [int(g) for g in match.groups()]

    def channel(value):
        value /= 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(first, second):
    a, b = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (a + 0.05) / (b + 0.05)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestCardCssContract(SanalPosCase):

    def css(self):
        with open(CSS_FILE, encoding='utf-8') as handle:
            return handle.read()

    def dark_block(self, css):
        start = re.search(r'@media\s*\(\s*prefers-color-scheme\s*:\s*dark\s*\)\s*\{', css)
        self.assertIsNotNone(start, 'koyu mod: @media (prefers-color-scheme: dark) yok')
        depth, index = 1, start.end()
        while depth and index < len(css):
            depth += {'{': 1, '}': -1}.get(css[index], 0)
            index += 1
        return css[start.end():index - 1]

    def test_script_acik_kapali_gorunum_siniflari(self):
        css = self.css()
        self.assertIn('.mo-js-only', css)
        self.assertIn('.mo-nojs-only', css)
        self.assertRegex(css, r'html\.mo-js')

    def test_script_siz_hata_gorunumu_user_invalid(self):
        self.assertIn(':user-invalid', self.css())

    def test_script_hata_gorunumu_aria_invalid(self):
        self.assertRegex(self.css(), r'\[aria-invalid\s*=\s*["\']?true["\']?\]')

    def test_koyu_modda_degiskenler_yeniden_tanimlanir_ve_kontrast_yeterli(self):
        css = self.css()
        dark = self.dark_block(css)
        values = dict(re.findall(r'(--mo-[a-z-]+)\s*:\s*([^;]+);', dark))
        for name in ('--mo-bg', '--mo-text', '--mo-muted'):
            self.assertIn(name, values, 'koyu modda %s yeniden tanımlanmalı' % name)
        self.assertLess(_luminance(values['--mo-bg']), 0.2, 'koyu modda arka plan koyu olmalı')
        self.assertGreaterEqual(_contrast(values['--mo-text'], values['--mo-bg']), 4.5)
        self.assertGreaterEqual(_contrast(values['--mo-muted'], values['--mo-bg']), 4.5)

    def test_dar_ekran_kurallari_var(self):
        css = self.css()
        self.assertRegex(css, r'@media\s*\(\s*max-width\s*:\s*(30rem|480px)\s*\)')
        self.assertIn('prefers-reduced-motion', css)            # mevcut davranış korunur (gerileme)
        self.assertNotRegex(css, r'url\(\s*["\']?https?:')      # dış kaynak yok (CSP img/style 'self')

    def rule(self, css, selector, prop):
        """``selector { ... prop: değer }`` içindeki değer (ilk eşleşen kural); yoksa test düşer."""
        match = re.search(r'(?:^|[}\s])' + re.escape(selector) + r'\s*\{([^}]*)\}', css, re.M)
        self.assertIsNotNone(match, 'kural yok: %s' % selector)
        value = re.search(r'(?:^|[;\s])' + re.escape(prop) + r'\s*:\s*([^;]+)', match.group(1))
        self.assertIsNotNone(value, '%s içinde %s yok' % (selector, prop))
        return value.group(1).strip()

    def test_kk_1_13b_hover_ve_placeholder_kontrasti_g1_g4(self):
        css = self.css()
        dark = self.dark_block(css)
        light_vars = dict(re.findall(r'(--mo-[a-z-]+)\s*:\s*([^;]+);', css[:css.index('@media')]))
        dark_vars = dict(re.findall(r'(--mo-[a-z-]+)\s*:\s*([^;]+);', dark))
        pairs = {
            'açık placeholder': (self.rule(css, '.mo-input::placeholder', 'color'), light_vars['--mo-surface']),
            'koyu placeholder': (self.rule(dark, '.mo-input::placeholder', 'color'), dark_vars['--mo-surface']),
            'koyu Öde': ('#ffffff', self.rule(dark, '.mo-btn-primary', 'background')),
            'koyu Öde hover': ('#ffffff', self.rule(dark, '.mo-btn-primary:hover', 'background')),
        }
        for name, (fore, back) in pairs.items():
            with self.subTest(durum=name):
                self.assertGreaterEqual(_contrast(fore, back), 4.5, (fore, back))

    def test_kk_1_13a_dokunma_hedefleri_44px_g2_g3(self):
        css = self.css()
        narrow = re.search(r'@media\s*\(\s*max-width\s*:\s*52rem\s*\)\s*\{(.*?)\n\}', css, re.S).group(1)
        self.assertGreaterEqual(int(self.rule(narrow, '.mo-nav-link', 'height').split('px')[0]), 44)
        self.assertGreaterEqual(int(self.rule(css, '.mo-breadcrumb a', 'min-height').split('px')[0]), 44)

    def test_taksit_tutarlari_satirda_bolunmez_r8(self):
        self.assertEqual(self.rule(self.css(), '.mo-inst-amount, .mo-inst-total, .mo-inst-fee', 'white-space'),
                         'nowrap')
