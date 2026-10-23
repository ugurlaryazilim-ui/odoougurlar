# -*- coding: utf-8 -*-
"""Mail Order kart sayfası ve sonuç rotası (tasarım §5.2, KARARLAR K-13).

Kart sayfası Odoo'nun sunduğu, arka uç varlığı İÇERMEYEN bir HTML sayfasıdır (tek script istisnası
aşağıdaki DIKKAT'te); formun ``action``'ı Paratika Direct POST 3D (``sale3d``) adresidir. Kart alanları tarayıcıdan doğrudan
Paratika'ya gider; bu modülün hiçbir rotası kart alanı kabul etmez. Tek POST rotası BIN ucudur (Aşama 2,
K-19): yalnız kartın ilk 8 hanesini ve ödeme kimliğini JSON olarak alır, hiçbir yere yazmaz/loglamaz.

DIKKAT: Kart sayfasında yalnız ``tools.mail_order_script()``'in ürettiği tek hash'li script bulunur (bkz.
KARARLAR K-16); ikinci script, harici script, satır içi olay işleyicisi, ``'self'``/``unsafe-*``/nonce
eklemek yasaktır. Bu dosyaya ve ``views/mail_order_templates.xml``'e arka uç varlığı (web.layout,
/web/assets), kart alanına ``value`` ya da kart sayfasına Odoo'ya POST eden form eklemek kart verisini
Odoo koduna/sunucusuna açar ve PCI kapsamını değiştirir (bkz. KARARLAR K-13).
Tek istisna SONUÇ sayfasıdır (Aşama 3, KK-3.9): kart alanı ve script içermez, CSP ``form-action 'self'``;
yalnız CSRF'li Tekrar dene / Link gönder formları bulunur.
"""
import json
import logging
import re
from datetime import datetime
from urllib.parse import quote, urlsplit

from markupsafe import Markup

from odoo import http
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request

from ..models.provider_paratika import _ISTANBUL, DIRECT_POST_HOSTS
from ..tools import installment_table, mail_order_css_url, mail_order_script, valid_bin
from .main import MO_RESULT_PATH, MPID_RE, PAYMENT_LIST_PATH

_logger = logging.getLogger(__name__)

PAY_PATH = '/sanal_pos/mail_order/pay/<int:payment_id>'
BIN_PATH = '/sanal_pos/mail_order/bin'
# Aşama 3 POST rotaları (A3-G3); sonuç sayfası formlarının hedefi
RETRY_PATH = '/sanal_pos/mail_order/retry/%d'
LINK_PATH = '/sanal_pos/mail_order/link/%d'
LINK_WIZARD_PATH = '/odoo/action-sanal_pos.action_sanal_pos_payment_create_wizard/%d'
RECORD_PATH = PAYMENT_LIST_PATH + '/%d'
EXPIRY_YEAR_SPAN = 15
# Dağıtımsız kapatma anahtarı (tasarım §3.9, D-4): İZİN LİSTESİ. Parametre yoksa ya da değeri
# (strip().lower()) bu kümedeyse açık; başka her değer ('', boşluk, 'tru', 'kapalı'...) kapalı.
# NEDEN: kapatma anahtarı yanlış yazımda da kapalı kalmalı (fail-closed); get_bool_param boş değeri
# "yok" sayıp varsayılana (açık) düşürürdü.
SCRIPT_SWITCH_PARAM = 'sanal_pos.mail_order_script'
_SCRIPT_ON_VALUES = ('true', '1', 'yes', 'evet')
# BIN ucu gövde sınırı: {"payment_id": <int>, "bin": "<8 hane>"} birkaç on bayttır
BIN_MAX_BODY = 256
BIN_MAX_PAYMENT_ID = 2 ** 31     # PostgreSQL integer sınırı; üstü zaten kayıt değildir
BIN_ERRORS = {400: 'bad_request', 403: 'forbidden', 404: 'not_found', 409: 'closed', 429: 'rate_limited',
              502: 'provider', 500: 'server'}

# G0-Q2: sale3d yanıtı Paratika dışı bir kökene (banka ACS) 302 ile yönlendiriyorsa tarayıcılar
# form-action'ı yönlendirmede de uygular; o durumda buraya ('https:',) yazılır (tek değişim yeri).
FORM_ACTION_EXTRA_SOURCES = ()

# Üst bar menüsü: (etiket, eylem xmlid'i, gereken grup). Adresler sabit eylem adresleridir
# (/odoo/action-<xmlid>); menüler.xml'deki grup kısıtlarıyla aynı: gizlemek yetki değil, yalnız
# kullanıcının tıklayıp "erişim yok" görmemesi içindir (asıl yetki eylem/model erişimidir).
NAV_ITEMS = (
    ('Ödeme Talepleri', 'sanal_pos.action_sanal_pos_payment', None),
    ('Yeni Ödeme Linki', 'sanal_pos.action_sanal_pos_payment_create_wizard', None),
    ('Mail Order', 'sanal_pos.action_sanal_pos_mail_order_wizard', None),
    ('İşlem Kayıtları', 'sanal_pos.action_sanal_pos_log', 'sanal_pos.group_sanal_pos_manager'),
)

_SHA256_B64_RE = re.compile(r'[A-Za-z0-9+/]{43}=')
# NEDEN: http yalnız loopback (geliştirme); başka http kaynağı düz metin trafiğe izin verirdi (B-1)
_CSP_SOURCE_RE = re.compile(
    r'(?:https://[A-Za-z0-9.\-]+|http://(?:(?i:localhost)|127\.0\.0\.1))(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~/\-]*)?')
_HOST_RE = re.compile(r'[A-Za-z0-9.\-]+(?::[0-9]{1,5})?')
_LOOPBACK_HOSTS = ('localhost', '127.0.0.1')

PAGE_HEADERS = [
    # G-3: arka uç sekmesi (aynı köken) window.open ile açıp kart alanlarının DOM'una erişemesin
    ('Cross-Origin-Opener-Policy', 'same-origin'),
    ('X-Frame-Options', 'DENY'),
    ('Cache-Control', 'no-store'),
    ('Referrer-Policy', 'no-referrer'),
    ('X-Content-Type-Options', 'nosniff'),
]


def card_page_csp(form_origin=None, script_hash=None, connect_src=None):
    """Kart/hata sayfası CSP'si. ``form_origin`` yoksa form gönderimi tamamen yasak.

    ``script_hash`` (``tools.mail_order_script()[1]``) verilirse ``script-src 'sha256-<hash>'``
    eklenir; ``connect_src`` (Aşama 2) verilirse ``connect-src <url>`` eklenir. İkisi de yoksa çıktı
    önceki script'siz sayfayla aynıdır.

    NEDEN: script-src yokken (default-src 'none') sayfada çalışan kod olmaz; varken yalnız içeriği
    hash ile sabitlenmiş tek satır içi script çalışır ('self'/nonce/unsafe-* kasten yok: bkz.
    KARARLAR K-16). form-action yalnız Paratika kökeni: değiştirilmiş bir form bile kartı başka
    adrese gönderemez (bkz. KARARLAR K-13).
    """
    sources = ' '.join((form_origin,) + FORM_ACTION_EXTRA_SOURCES) if form_origin else "'none'"
    directives = ["default-src 'none'"]
    if script_hash:
        # DIKKAT: değer CSP başlığına doğrudan girer; base64 dışı karakter (boşluk, ';') ek kaynak ya da
        # yönerge sokabilir, bu yüzden biçim zorunlu denetlenir.
        if not _SHA256_B64_RE.fullmatch(script_hash):
            raise ValueError('script_hash sha256 base64 biçiminde değil')
        directives.append("script-src 'sha256-%s'" % script_hash)
    if connect_src:
        if not _CSP_SOURCE_RE.fullmatch(connect_src):
            raise ValueError('connect_src geçersiz')
        directives.append('connect-src %s' % connect_src)
    directives += ["style-src 'self'", "img-src 'self'", 'form-action %s' % sources,
                   "frame-ancestors 'none'", "base-uri 'none'"]
    return '; '.join(directives)


def _normalize_https_host(netloc):
    """Küçük harf; https varsayılan portu (:443) atılır. ``user@`` içeren netloc eşleşmez (``''`` döner)."""
    netloc = (netloc or '').lower()
    if not _HOST_RE.fullmatch(netloc):
        return ''
    return netloc[:-4] if netloc.endswith(':443') else netloc


def mail_order_script_enabled(env):
    """Kapatma anahtarı (D-4): kart sayfası betiği ve BIN ucu aynı yardımcıyı kullanır (tek karar).

    NEDEN doğrudan arama: ``ICP.get_param`` boş değeri ``False`` yapar ("yok" ile karışır, açık sayılırdı).
    """
    param = env['ir.config_parameter'].sudo().search([('key', '=', SCRIPT_SWITCH_PARAM)], limit=1)
    return not param or (param.value or '').strip().lower() in _SCRIPT_ON_VALUES


class SanalPosMailOrderController(http.Controller):

    @http.route(PAY_PATH, type='http', auth='user', methods=['GET'])
    def mail_order_card_page(self, payment_id, **_kwargs):
        """Kart giriş sayfası. Sorgu parametreleri (``_kwargs``) okunmaz ve sayfaya yansımaz."""
        payment = request.env['sanal.pos.payment'].browse(payment_id)
        try:
            values = payment._mail_order_card_values()
        except AccessError:
            return self._error_page('Bu sayfa için Sanal POS kullanıcı yetkisi gerekir.', status=403)
        except MissingError:
            return self._error_page('Ödeme kaydı bulunamadı.', status=404)
        except UserError as exc:
            return self._error_page(str(exc), status=409, payment_id=payment_id)
        origin = self._https_origin(values.get('form_action'))
        if not origin:
            # DIKKAT: adres https değilse form gösterilmez (fail-closed): kart düz metinle ya da
            # bilinmeyen bir adrese gönderilmesin.
            _logger.error('sanal_pos: kart sayfası adresi geçersiz, ödeme id=%s', payment_id)
            return self._error_page('Ödeme adresi yapılandırması geçersiz; yöneticinize başvurun.',
                                    status=500, payment_id=payment_id)
        # NEDEN: script SKT'nin "bu ay" sınırını istemci saatinden değil buradan alır (data-now-ym);
        # yıl listesi de aynı (İstanbul) andan türer, ikisi ay/yıl geçişinde çelişmesin.
        now = datetime.now(_ISTANBUL)
        this_year = now.year
        # NEDEN: biçimleme/hesap burada (tools); şablon ifadesindeki '%%' kaçışı görünüm kaydında korunmadı
        values['installment_table'] = installment_table(
            values.get('amount'), values.get('installments'))
        values.update({
            'record_url': RECORD_PATH % payment.id,
            'nav': self._nav_values(),
            'expiry_months': ['%02d' % m for m in range(1, 13)],
            'expiry_years': [str(y) for y in range(this_year, this_year + EXPIRY_YEAR_SPAN + 1)],
            'now_ym': '%04d-%02d' % (now.year, now.month),
        })
        try:
            with request.env.cr.savepoint():
                payment.sudo()._post_note('Kart giriş sayfası açıldı: %s' % (request.env.user.name or '-'))
        except Exception as exc:  # noqa: BLE001 - not yazılamasa da sayfa açılır
            _logger.warning('sanal_pos: kart sayfası notu yazılamadı (%s), ödeme id=%s',
                            type(exc).__name__, payment_id)
        card_script, script_hash = self._card_script()
        # NEDEN: Markup değilse QWeb '<' -> '&lt;' yapar; basılan metin hash'lenenden farklı olur
        # (script hiç çalışmaz). card_script ve CSP aynı çağrıdan türer (tek kaynak, K-16).
        values['card_script'] = Markup(card_script) if card_script else None
        # NEDEN: connect-src ve data-bin yalnız betik gerçekten sunuluyorsa (anahtar açık, dosya sağlam)
        # ve ana makine güvenliyse; biri yoksa betik BIN ucunu çağıramaz, taksit tablosu sabit kalır.
        connect_src = self._bin_connect_src() if script_hash else None
        values['bin_enabled'] = bool(connect_src)
        return self._render('sanal_pos.mail_order_card_page', values,
                            card_page_csp(origin, script_hash=script_hash, connect_src=connect_src))

    @http.route(BIN_PATH, type='http', auth='user', methods=['POST'], csrf=False)
    def mail_order_bin(self, **_kwargs):
        """BIN sorgusu (A2, tasarım §4): kartın ilk 8 hanesinden kart türü ve taksit satırları.

        Yalnız JSON ``{"payment_id": int, "bin": "8 hane"}``. Denetim sırası: 400 doğrulama, 403 grup,
        404/403 kayıt, 409 kapalı (anahtar/kayıt), 429 hız sınırı, Paratika. Yanıtlar girdiyi yankılamaz;
        BIN hiçbir log/istisna/yanıt metnine girmez (istisnadan yalnız sınıf adı loglanır).
        DIKKAT: csrf=False kasıtlı; uç yalnız ``application/json`` kabul eder (çapraz site formu bu türle
        gönderilemez, fetch ise CORS ön kontrolüne takılır) ve ödeme/kayıt durumu değiştirmez.
        """
        parsed = self._bin_request_values()
        if not parsed:
            return self._bin_response(400)
        payment_id, bin_digits = parsed
        env = request.env
        if not env.user.has_group('sanal_pos.group_sanal_pos_user'):
            return self._bin_response(403)
        payment = env['sanal.pos.payment'].browse(payment_id)
        try:
            if not payment.exists():
                return self._bin_response(404)
            payment.check_access('read')
            if not mail_order_script_enabled(env):
                return self._bin_response(409)
            with env.cr.savepoint():
                result = payment._mail_order_bin_lookup(bin_digits)
        except ValueError:
            return self._bin_response(400)
        except AccessError:
            return self._bin_response(403)
        except MissingError:
            return self._bin_response(404)
        except UserError:
            return self._bin_response(409)
        except Exception as exc:  # noqa: BLE001 - uç her durumda JSON döner
            # DIKKAT: istisna metni loglanmaz; sağlayıcı/BIN içeren bir metin sunucu loguna düşmesin
            _logger.error('sanal_pos: BIN ucu hata verdi, istisna sınıfı %s', type(exc).__name__)
            return self._bin_response(500)
        status = result.pop('status', 500)
        return self._bin_response(status, result if status == 200 else None)

    @http.route(MO_RESULT_PATH, type='http', auth='user', methods=['GET'])
    def mail_order_result(self, mpid=None, n=None, **_kwargs):
        """3D dönüşünden sonra: durumu sorgular ve standalone sonuç sayfasını gösterir (Aşama 3).

        ``n``: meta refresh sayacı (yalnız 0..24 rakam, aksi 0). MPID bulunamazsa listeye 303.
        """
        if not request.env.user.has_group('sanal_pos.group_sanal_pos_user'):
            return self._error_page('Bu sayfa için Sanal POS kullanıcı yetkisi gerekir.', status=403)
        payment = request.env['sanal.pos.payment']
        if mpid and MPID_RE.match(mpid):
            payment = payment.search([('merchant_payment_id', '=', mpid),
                                      ('payment_method', '=', 'mail_order')], limit=1)
        if not payment:
            return request.redirect(PAYMENT_LIST_PATH, code=303)
        payment._mail_order_after_return()
        # NEDEN: yalnız en çok 3 rakam kabul edilir; sınır dışı/bozuk değer 0'a düşer ve sayaç 24'te durur,
        # yani yenileme istemci girdisiyle sonsuza uzatılamaz (KK-3.4)
        refresh_count = int(n) if n and re.fullmatch(r'[0-9]{1,3}', n) else 0
        return self._result_page(payment, refresh_count)

    # DIKKAT: csrf varsayılan (açık) kalmalı; bu rotalar Kapat/K-15/SESSIONTOKEN tetikler (KK-3.9)
    @http.route('/sanal_pos/mail_order/retry/<int:payment_id>', type='http', auth='user', methods=['POST'])
    def mail_order_retry(self, payment_id, **_kwargs):
        """Sonuç sayfasındaki 'Tekrar dene' / 'Yeni deneme aç' (tasarım §5.5)."""
        return self._mail_order_post(payment_id, 'action_mail_order_retry')

    @http.route('/sanal_pos/mail_order/link/<int:payment_id>', type='http', auth='user', methods=['POST'])
    def mail_order_to_link(self, payment_id, **_kwargs):
        """Sonuç sayfasındaki 'Bunun yerine link gönder' (tasarım §5.5)."""
        return self._mail_order_post(payment_id, 'action_mail_order_to_link')

    def _mail_order_post(self, payment_id, method):
        """Model eylemini çalıştırır: kart sayfası/sihirbaz -> 303, bildirim ya da UserError -> sonuç sayfası."""
        payment = request.env['sanal.pos.payment'].browse(payment_id)
        try:
            if not payment.exists():
                raise MissingError('Ödeme kaydı bulunamadı.')
            action = getattr(payment, method)()
        except AccessError:
            return self._error_page('Bu sayfa için Sanal POS kullanıcı yetkisi gerekir.', status=403)
        except MissingError:
            return self._error_page('Ödeme kaydı bulunamadı.', status=404)
        except UserError as exc:
            # NEDEN: yanıt döndürülünce Odoo isteği commit eder; yarım kalan yazım (ör. sihirbaz kaydı)
            # istisnadaki gibi geri alınır. Kapat'ın sonucu eylem içinde zaten commit edilmiştir.
            request.env.cr.rollback()
            if payment.sudo().payment_method != 'mail_order':
                return self._error_page(str(exc), status=409, payment_id=payment_id)
            return self._result_page(payment, notice=str(exc), status=409)
        action = action or {}
        if action.get('type') == 'ir.actions.act_url':
            return request.redirect(action['url'], code=303, local=True)
        if action.get('type') == 'ir.actions.act_window' and action.get('res_id'):
            # NEDEN: geçici sihirbaz kaydı web istemcisinde kendi adresiyle ön dolu açılır (tasarım §5.5)
            return request.redirect(LINK_WIZARD_PATH % action['res_id'], code=303, local=True)
        return self._result_page(payment, notice=(action.get('params') or {}).get('message'))

    # ------------------------------------------------------------------ yardımcılar
    @classmethod
    def _result_page(cls, payment, refresh_count=0, notice=None, status=200):
        """Sonuç sayfası (script'siz). ``notice``: üstte kırmızı uyarı (POST rotalarının UserError'u, A3-G3).

        DIKKAT: CSP'de ``form-action 'self'`` yalnız burada açıktır (Tekrar dene / Link POST'ları, CSRF'li);
        formlarda kart alanı yoktur ve script-src hiç yoktur.
        """
        values = payment._mail_order_result_values(refresh_count)
        rec = payment.sudo()
        result_url = '%s?mpid=%s' % (MO_RESULT_PATH, quote(rec.merchant_payment_id, safe='/'))
        values.update({
            'payment_id': rec.id,
            'payment_name': '' if rec.name == '/' else rec.name,
            'record_url': RECORD_PATH % rec.id,
            'is_test': rec.environment == 'test',
            'nav': cls._nav_values(),
            'csrf_token': request.csrf_token(),
            'retry_action': RETRY_PATH % rec.id,
            'link_action': LINK_PATH % rec.id,
            'result_url': result_url,
            'refresh_url': '%s&n=%d' % (result_url, values['refresh_next']) if values['refresh_next'] else None,
            'notice': notice,
        })
        return cls._render('sanal_pos.mail_order_result_page', values,
                           card_page_csp("'self'"), status=status)

    @staticmethod
    def _card_script():
        """``(metin, sha256_b64)``; anahtar kapalı, dosya sorunlu ya da hash onaysızsa ``(None, None)``.

        DIKKAT: fail-closed: script okunamaz/geçersizse sayfa script'siz (CSP'de script-src yok)
        sunulur; ödeme yolu bozulmaz. İstisna metni loglanmaz (yalnız sınıf adı).
        """
        if not mail_order_script_enabled(request.env):
            return None, None
        try:
            return mail_order_script()
        except (OSError, ValueError) as exc:
            _logger.error("sanal_pos: kart sayfası betiği yüklenemedi, betiksiz sunuluyor (%s)",
                          type(exc).__name__)
            return None, None

    @staticmethod
    def _bin_connect_src():
        """CSP ``connect-src`` değeri (B-1): isteğin kendi kökeni + sabit BIN yolu; güvenli değilse ``None``.

        DIKKAT: ana makine istemci başlığından gelir (proxy modunda X-Forwarded-Host); CSP başlığına
        girmeden önce kısıtlı bir biçime (harf/rakam/nokta/tire + isteğe bağlı port) zorlanır. Ham
        değer geçersizse loglanmaz (log enjeksiyonu); http yalnız loopback'te (geliştirme) kabul edilir.
        """
        httprequest = request.httprequest
        host = httprequest.host or ''
        # NEDEN ham başlık da denetlenir: ProxyFix X-Forwarded-Host'u virgülle ayrılmış liste sayıp tek bir
        # değer seçer; "evil.com," gibi bozuk başlıktan geçerli görünen bir host çıkmasın.
        forwarded = httprequest.headers.get('X-Forwarded-Host')
        if not _HOST_RE.fullmatch(host) or (forwarded is not None and not _HOST_RE.fullmatch(forwarded)):
            return None
        scheme = httprequest.scheme
        if scheme == 'https' or (scheme == 'http' and host.partition(':')[0].lower() in _LOOPBACK_HOSTS):
            return '%s://%s%s' % (scheme, host, BIN_PATH)
        if scheme == 'http':
            # NEDEN: Odoo 19 (http.py) proxy_mode açıkken ProxyFix'i yalnız X-Forwarded-Host varsa uygular;
            # Cloudflare Tunnel bu başlığı göndermez, bu yüzden https sayfa bile scheme 'http' görünür.
            # X-Forwarded-Proto'ya GÜVENİLMEZ (istemci taklit edebilir). Yönetici ayarı web.base.url https
            # ise ve host'u isteğin Host'uyla birebir aynıysa sayfa bu siteden, https'ten sunuluyor sayılır.
            base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
            base = urlsplit(base_url)
            if base.scheme.lower() != 'https':
                # NEDEN freeze önerisi: Odoo 19 (res_users.py) yönetici girişinde web.base.url.freeze yoksa
                # web.base.url'i istek adresine (tünel arkasında http://) yazar; ayar sessizce http'ye döner.
                reason = ('web.base.url https değil (https olmalı ve web.base.url.freeze=True ayarlanmalı, '
                          'yoksa yönetici girişi onu http olarak yeniden yazar)')
            elif _normalize_https_host(base.netloc) != _normalize_https_host(host):
                reason = 'web.base.url ana makinesi istek ana makinesiyle eşleşmiyor'
            else:
                return 'https://%s%s' % (host, BIN_PATH)
            _logger.warning('sanal_pos: BIN taksit sorgusu kapalı, kart sayfası https değil, %s (host=%s)',
                            reason, host)
        return None

    @staticmethod
    def _bin_request_values():
        """``(payment_id, bin)`` ya da geçersizse ``None``; gövde ≤ 256 bayt, tam iki anahtar, katı tipler."""
        httprequest = request.httprequest
        if httprequest.mimetype != 'application/json':
            return None
        # DIKKAT: gövde okunmadan ÖNCE boyut denetlenir (Odoo'nun HTTPRequest sarmalayıcısı ``stream`` vermez,
        # ``get_data`` tamamını belleğe alır); Content-Length'i olmayan gövde WSGI'de boş okunur.
        length = httprequest.content_length
        if length is None or length > BIN_MAX_BODY:
            return None
        raw = httprequest.get_data()
        if len(raw) > BIN_MAX_BODY:
            return None
        try:
            data = json.loads(raw.decode('utf-8'))
        except ValueError:      # UnicodeDecodeError dahil
            return None
        if not isinstance(data, dict) or set(data) != {'payment_id', 'bin'}:
            return None
        payment_id, bin_digits = data['payment_id'], data['bin']
        # NEDEN type(...) is int: bool int alt sınıfıdır, True kayıt 1 sayılmasın
        if type(payment_id) is not int or not 0 < payment_id < BIN_MAX_PAYMENT_ID or not valid_bin(bin_digits):
            return None
        return payment_id, bin_digits

    @staticmethod
    def _bin_response(status, body=None):
        # NEDEN ensure_ascii (varsayılan): make_json_response Content-Length'i karakter sayısından alır,
        # Türkçe karakterli gövdede bayt sayısıyla uyuşmazdı.
        if status != 200 and status not in BIN_ERRORS:
            status = 500
        payload = body if status == 200 else {'ok': False, 'error': BIN_ERRORS[status]}
        return request.make_response(
            json.dumps(payload), status=status,
            headers=[('Content-Type', 'application/json'), ('Cache-Control', 'no-store')])

    @staticmethod
    def _https_origin(url):
        """Form/CSP kökeni; yalnız https + kodda sabit Paratika host'u (G-1), aksi ``None``."""
        parts = urlsplit(url or '')
        if parts.scheme != 'https' or (parts.hostname or '') not in DIRECT_POST_HOSTS or parts.port:
            return None
        return 'https://%s' % parts.hostname

    @staticmethod
    def _nav_values():
        """Üst bar değerleri (yalnız sunucu tarafı, şablonda kaçışlanır). Oturumlu rotalar içindir."""
        user = request.env.user
        is_sp_user = user.has_group('sanal_pos.group_sanal_pos_user')
        items = [{'label': label, 'url': '/odoo/action-%s' % xmlid, 'active': xmlid == NAV_ITEMS[0][1]}
                 for label, xmlid, group in NAV_ITEMS
                 if is_sp_user and (not group or user.has_group(group))]
        return {
            'brand_url': PAYMENT_LIST_PATH,
            'list_url': PAYMENT_LIST_PATH,
            'items': items,
            'user_name': user.name or '',
            'company_name': user.company_id.sudo().name or '',
            # NEDEN: /web/image (aynı köken, CSP img-src 'self'); id sunucudan gelir, girdi değildir.
            'avatar_url': '/web/image/res.users/%d/avatar_128' % user.id,
        }

    @staticmethod
    def _render(template, values, csp, status=200):
        # NEDEN: ir.qweb doğrudan; request.render/web.layout arka uç varlıklarını eklerdi.
        body = request.env['ir.qweb']._render(template, dict(values, css_url=mail_order_css_url()))
        # DIKKAT: body Markup'tır; düz str ile birleştirmek ('<!DOCTYPE…' + body) soldaki metni
        # kaçışlar (&lt;!DOCTYPE) ve tarayıcı sayfayı quirks kipinde gösterir (Ö-1).
        return request.make_response(
            Markup('<!DOCTYPE html>\n') + body, status=status,
            headers=[('Content-Type', 'text/html; charset=utf-8'),
                     ('Content-Security-Policy', csp)] + PAGE_HEADERS)

    def _error_page(self, message, status, payment_id=None):
        back = RECORD_PATH % payment_id if payment_id else PAYMENT_LIST_PATH
        return self._render('sanal_pos.mail_order_error_page',
                            {'message': message, 'back_url': back, 'nav': self._nav_values(),
                             'payment_url': RECORD_PATH % payment_id if payment_id else None},
                            card_page_csp(), status=status)
