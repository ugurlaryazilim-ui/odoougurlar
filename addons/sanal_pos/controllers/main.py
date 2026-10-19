# -*- coding: utf-8 -*-
"""Paratika bildirim (webhook) ve dönüş uç noktaları (tasarım §7; KK-22, KK-23, KK-29, KK-38).

İki uç nokta da YALNIZ TETİKTİR:

* Paratika'ya çağrı yapmaz (5 sn bütçesi, oturumsuz uç nokta dış çağrı yükselticisi olamaz).
* Gövdedeki tutar/durum alanları okunmaz; yalnız ödeme numarası (MERCHANTPAYMENTID) alınır.
  Karar, ``sync_requested`` bayrağıyla tetiklenen cron'daki QUERYTRANSACTION sorgusuyla verilir.
* Yanıt her durumda sabittir (bilinen/bilinmeyen/eksik/bozuk numara aynı): bilgi sızmaz.
* Public kullanıcı sudo ile yalnız şunları yapar (``sanal.pos.payment._mark_sync_requested``
  ve ``sanal.pos.provider._log_call`` içinde): tam eşleşmeyle tek kayıt arama + bayrak yazımı +
  olay kaydı oluşturma. Kullanıcı girdisi domain'e yalnız eşitlik değeri olarak girer.
* Gelen veride sır/kişisel veri loglanmaz: olay kaydına yalnız alan ADLARI ve küçük bir izin
  listesindeki alanların kırpılmış değerleri yazılır (kart, telefon, e-posta, şifre asla).
"""
import json
import logging
import re

from odoo import http
from odoo.http import request

from .. import tools
from ..models.sanal_pos_payment import SYNC_DEFERRED_CODE

_logger = logging.getLogger(__name__)

NOTIFY_PATH = '/sanal_pos/paratika/notify'
RETURN_PATH = '/sanal_pos/paratika/return'
PROVIDER_MODEL = 'sanal.pos.provider.paratika'

MAX_BODY_BYTES = 10 * 1024          # KK-38
# MERCHANTPAYMENTID biçimi: "<fatura no>-<deneme no>", ASCII, en çok 128 karakter
MPID_RE = re.compile(r'^[A-Za-z0-9._\-/]{1,128}$')

OK_BODY = 'OK'
TOO_LARGE_BODY = 'Payload Too Large'
RETURN_TEXT = 'İşleminiz alındı. Sonuç mağazamız tarafından size iletilecektir.'
RETURN_HTML = (
    '<!DOCTYPE html>\n'
    '<html lang="tr"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<title>İşleminiz alındı</title>'
    '<style>body{font-family:sans-serif;display:flex;min-height:80vh;align-items:center;'
    'justify-content:center;margin:0;padding:1rem;text-align:center;color:#222}'
    'p{font-size:1.15rem;max-width:30rem;line-height:1.5}</style></head>'
    '<body><p>' + RETURN_TEXT + '</p></body></html>'
)

# Olay kaydına değeriyle yazılabilen alanlar (küçük harfli ad). Başka hiçbir değer yazılmaz.
LOGGED_VALUE_FIELDS = frozenset({
    'notificationtype', 'merchantpaymentid', 'responsecode', 'errorcode', 'transactionstatus',
    'transactiontype', 'status',
})
LOG_MAX_FIELD_NAMES = 40
LOG_MAX_VALUE_LEN = 128

SECURITY_HEADERS = [
    ('Cache-Control', 'no-store'),
    ('X-Content-Type-Options', 'nosniff'),
    ('Referrer-Policy', 'no-referrer'),
]


class SanalPosParatikaController(http.Controller):

    # ------------------------------------------------------------------ uç noktalar
    @http.route(NOTIFY_PATH, type='http', auth='public', methods=['POST'], csrf=False,
                save_session=False)
    def paratika_notify(self, **_kwargs):
        """Paratika bildirimi: bayrak + cron tetiği; yanıt her zaman 200 ``OK``."""
        if self._body_too_large():
            return self._too_large_response()
        self._trigger('NOTIFY')
        return self._response(OK_BODY, 'text/plain; charset=utf-8')

    @http.route(RETURN_PATH, type='http', auth='public', methods=['POST'], csrf=False,
                save_session=False)
    def paratika_return(self, **_kwargs):
        """Müşterinin ödeme sonrası dönüşü: aynı tetik, sabit sade metin. Karar vermez."""
        if self._body_too_large():
            return self._too_large_response()
        self._trigger('RETURN')
        return self._response(RETURN_HTML, 'text/html; charset=utf-8')

    # ------------------------------------------------------------------ yardımcılar
    @staticmethod
    def _response(body, content_type, status=200):
        return request.make_response(
            body, headers=[('Content-Type', content_type)] + SECURITY_HEADERS, status=status)

    def _too_large_response(self):
        return self._response(TOO_LARGE_BODY, 'text/plain; charset=utf-8', status=413)

    @staticmethod
    def _form_params():
        """Yalnız gövde (POST) alanları; alan sayısı sınırlı, ilk değerler."""
        form = request.httprequest.form
        params = {}
        for key in form.keys():
            if len(params) >= 100:
                break
            params[key] = form.get(key)
        return params

    @staticmethod
    def _body_too_large():
        """KK-38: gövde 10 KB'ı aşarsa işlem yapılmaz (413).

        Content-Length varsa ona bakılır; yoksa (chunked) ayrıştırılmış alanların toplamına.
        """
        httprequest = request.httprequest
        length = httprequest.content_length
        if length is not None:
            return length > MAX_BODY_BYTES
        total = sum(len(key) + len(value) for key, value in httprequest.form.items(multi=True))
        return total > MAX_BODY_BYTES

    def _trigger(self, action):
        """Ödeme numarasını okur, bayrak + cron tetiğini kurar ve olayı maskeli kaydeder.

        Hiçbir hata dışarı sızmaz: yanıt sabit kalır. Dış çağrı ve durum kararı yoktur.
        """
        env = request.env
        provider = env[PROVIDER_MODEL]
        params = self._form_params()
        mpid = None
        try:
            mpid = provider.parse_notification(params)
        except Exception as exc:  # noqa: BLE001 - bozuk girdi yanıtı değiştirmez
            _logger.warning('sanal_pos: %s numarası okunamadı (%s)', action, type(exc).__name__)
        if mpid is not None and not MPID_RE.match(mpid):
            mpid = None
        payment = env['sanal.pos.payment'].browse()
        if mpid:
            try:
                with env.cr.savepoint():
                    payment = env['sanal.pos.payment']._mark_sync_requested(mpid)
            except Exception as exc:  # noqa: BLE001 - tetik kurulamazsa periyodik cron toplar
                _logger.warning('sanal_pos: %s tetiği kurulamadı (%s)', action, type(exc).__name__)
                payment = env['sanal.pos.payment'].browse()
        try:
            self._log_event(provider, action, params, mpid, payment,
                            deferred=bool(payment.env.context.get('sanal_pos_sync_deferred')))
        except Exception as exc:  # noqa: BLE001 - olay kaydı yanıtı bozmaz
            _logger.warning('sanal_pos: %s olayı kaydedilemedi (%s)', action, type(exc).__name__)

    @staticmethod
    def _log_event(provider, action, params, mpid, payment, deferred=False):
        """``sanal.pos.log`` satırı: alan adları + izin listesindeki alanların kırpılmış değerleri."""
        values = {}
        for key, value in params.items():
            if str(key).lower() not in LOGGED_VALUE_FIELDS:
                continue
            text = str(value if value is not None else '')[:LOG_MAX_VALUE_LEN]
            if str(key).lower() == 'merchantpaymentid' and text != mpid:
                text = '[geçersiz biçim]'
            values[key] = text
        names = sorted(str(key)[:64] for key in params)[:LOG_MAX_FIELD_NAMES]
        body = json.dumps({'fields': names, 'values': values}, ensure_ascii=False)
        # Sırlar (ayardaki şifre/secretKey) değerlerde geçse bile süzülür
        body = tools.scrub(body, provider._secrets())
        environment = payment.environment if payment else provider._param('sanal_pos.environment')
        provider._log_call(
            payment, action, 'paratika', environment, http_status=200,
            success=bool(payment), request_body=body,
            # Y-1: kilit yüzünden bayrak yazılamadı; bayrak cron'u bu satırdan yeniden dener
            error_code=SYNC_DEFERRED_CODE if deferred else None)
