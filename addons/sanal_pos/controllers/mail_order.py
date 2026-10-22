# -*- coding: utf-8 -*-
"""Mail Order kart sayfası ve sonuç rotası (tasarım §5.2, KARARLAR K-13).

Kart sayfası Odoo'nun sunduğu, arka uç varlığı ve script İÇERMEYEN bir HTML sayfasıdır; formun
``action``'ı Paratika Direct POST 3D (``sale3d``) adresidir. Kart alanları tarayıcıdan doğrudan
Paratika'ya gider; bu modülün hiçbir rotası kart alanı kabul etmez (yalnız GET).

DIKKAT: Bu dosyaya ve ``views/mail_order_templates.xml``'e script, satır içi olay işleyicisi,
arka uç varlığı (web.layout, /web/assets), kart alanına ``value`` ya da Odoo'ya POST eden form
eklemek kart verisini Odoo koduna/sunucusuna açar ve PCI kapsamını değiştirir (bkz. KARARLAR K-13).
"""
import logging
from datetime import datetime
from urllib.parse import urlsplit

from markupsafe import Markup

from odoo import http
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request

from ..models.provider_paratika import DIRECT_POST_HOSTS
from ..tools import installment_table
from .main import MO_RESULT_PATH, MPID_RE, PAYMENT_LIST_PATH

_logger = logging.getLogger(__name__)

PAY_PATH = '/sanal_pos/mail_order/pay/<int:payment_id>'
RECORD_PATH = PAYMENT_LIST_PATH + '/%d'
EXPIRY_YEAR_SPAN = 15

# G0-Q2: sale3d yanıtı Paratika dışı bir kökene (banka ACS) 302 ile yönlendiriyorsa tarayıcılar
# form-action'ı yönlendirmede de uygular; o durumda buraya ('https:',) yazılır (tek değişim yeri).
FORM_ACTION_EXTRA_SOURCES = ()

PAGE_HEADERS = [
    # G-3: arka uç sekmesi (aynı köken) window.open ile açıp kart alanlarının DOM'una erişemesin
    ('Cross-Origin-Opener-Policy', 'same-origin'),
    ('X-Frame-Options', 'DENY'),
    ('Cache-Control', 'no-store'),
    ('Referrer-Policy', 'no-referrer'),
    ('X-Content-Type-Options', 'nosniff'),
]


def card_page_csp(form_origin=None):
    """Kart/hata sayfası CSP'si. ``form_origin`` yoksa form gönderimi tamamen yasak.

    NEDEN: script-src yok (default-src 'none'): sayfada çalışan kod olmadığından kart alanları
    tarayıcıda bile okunamaz; form-action yalnız Paratika kökeni: değiştirilmiş bir form bile
    kartı başka adrese gönderemez (bkz. KARARLAR K-13).
    """
    sources = ' '.join((form_origin,) + FORM_ACTION_EXTRA_SOURCES) if form_origin else "'none'"
    return ("default-src 'none'; style-src 'self'; img-src 'self'; form-action %s; "
            "frame-ancestors 'none'; base-uri 'none'" % sources)


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
        this_year = datetime.now().year
        # NEDEN: biçimleme/hesap burada (tools); şablon ifadesindeki '%%' kaçışı görünüm kaydında korunmadı
        values['installment_table'] = installment_table(
            values.get('amount'), values.get('installments'))
        values.update({
            'record_url': RECORD_PATH % payment.id,
            'expiry_months': ['%02d' % m for m in range(1, 13)],
            'expiry_years': [str(y) for y in range(this_year, this_year + EXPIRY_YEAR_SPAN + 1)],
        })
        try:
            with request.env.cr.savepoint():
                payment.sudo()._post_note('Kart giriş sayfası açıldı: %s' % (request.env.user.name or '-'))
        except Exception as exc:  # noqa: BLE001 - not yazılamasa da sayfa açılır
            _logger.warning('sanal_pos: kart sayfası notu yazılamadı (%s), ödeme id=%s',
                            type(exc).__name__, payment_id)
        return self._render('sanal_pos.mail_order_card_page', values, card_page_csp(origin))

    @http.route(MO_RESULT_PATH, type='http', auth='user', methods=['GET'])
    def mail_order_result(self, mpid=None, **_kwargs):
        """3D dönüşünden sonra: durumu sorgular ve ödeme kaydının formuna yönlendirir (303)."""
        if not request.env.user.has_group('sanal_pos.group_sanal_pos_user'):
            return self._error_page('Bu sayfa için Sanal POS kullanıcı yetkisi gerekir.', status=403)
        payment = request.env['sanal.pos.payment']
        if mpid and MPID_RE.match(mpid):
            payment = payment.search([('merchant_payment_id', '=', mpid),
                                      ('payment_method', '=', 'mail_order')], limit=1)
        if not payment:
            return request.redirect(PAYMENT_LIST_PATH, code=303)
        payment._mail_order_after_return()
        return request.redirect(RECORD_PATH % payment.id, code=303)

    # ------------------------------------------------------------------ yardımcılar
    @staticmethod
    def _https_origin(url):
        """Form/CSP kökeni; yalnız https + kodda sabit Paratika host'u (G-1), aksi ``None``."""
        parts = urlsplit(url or '')
        if parts.scheme != 'https' or (parts.hostname or '') not in DIRECT_POST_HOSTS or parts.port:
            return None
        return 'https://%s' % parts.hostname

    @staticmethod
    def _render(template, values, csp, status=200):
        # NEDEN: ir.qweb doğrudan; request.render/web.layout arka uç varlıklarını eklerdi.
        body = request.env['ir.qweb']._render(template, values)
        # DIKKAT: body Markup'tır; düz str ile birleştirmek ('<!DOCTYPE…' + body) soldaki metni
        # kaçışlar (&lt;!DOCTYPE) ve tarayıcı sayfayı quirks kipinde gösterir (Ö-1).
        return request.make_response(
            Markup('<!DOCTYPE html>\n') + body, status=status,
            headers=[('Content-Type', 'text/html; charset=utf-8'),
                     ('Content-Security-Policy', csp)] + PAGE_HEADERS)

    def _error_page(self, message, status, payment_id=None):
        back = RECORD_PATH % payment_id if payment_id else PAYMENT_LIST_PATH
        return self._render('sanal_pos.mail_order_error_page',
                            {'message': message, 'back_url': back}, card_page_csp(), status=status)
