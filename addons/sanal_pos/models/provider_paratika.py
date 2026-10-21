# -*- coding: utf-8 -*-
"""Paratika API v2 istemcisi (tasarım §5.1, 00-paratika-api.md).

* HTTPS POST, gövde ``urlencode(..., encoding='utf-8')`` ile BAYT olarak üretilir,
  ``Content-Type: application/x-www-form-urlencoded; charset=UTF-8`` (KK-15).
* Zaman aşımı ``(10, 30)`` sn. Zaman aşımı, ağ/TLS hatası ve çözülemeyen yanıt
  "belirsiz" (``timeout=True``) sayılır: isteğin gidip gitmediği bilinemez (KK-16/47).
* Çağrıdan sonra istisna fırlatılmaz; sonuç normalize sözlükle döner.
* Sırlar (API şifresi, secretKey) log gövdelerinde ve mesajlarda ``***`` olur (KK-37);
  telefon son 4 hane, e-posta alan adı görünür (NFR-4). Python logger'a gövde yazılmaz.
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

import requests

from odoo import api, models

from .. import tools
from .res_config_settings import get_bool_param

_logger = logging.getLogger(__name__)

DEFAULT_TEST_URL = 'https://test.paratika.com.tr/paratika/api/v2'
DEFAULT_LIVE_URL = 'https://vpos.paratika.com.tr/paratika/api/v2'
TIMEOUT = (10, 30)                    # (bağlanma, okuma) sn - NFR-2
CONTENT_TYPE = 'application/x-www-form-urlencoded; charset=UTF-8'
RETURN_PATH = '/sanal_pos/paratika/return'
NOTE_MAX = 50                         # MERCHANTNOTE en çok 50 karakter
CHANNEL_NAMES = {'sms': 'SMS', 'email': 'EMAIL'}
# 5xx / çözülemeyen yanıtta işlemin gerçekleşmiş olabileceği action'lar
STATE_CHANGING_ACTIONS = ('PAYBYLINKPAYMENT', 'VOID', 'REFUND')
FINANCIAL_ACTIONS = ('VOID', 'REFUND')

_ISTANBUL = ZoneInfo('Europe/Istanbul')
_UTC = timezone.utc

TIMEOUT_MESSAGE = ('Paratika yanıt vermedi veya bağlantı kurulamadı; işlem gerçekleşmiş '
                   'olabilir. Durum kontrol edilecek.')

# Paratika hata kodu -> Türkçe açıklama (KK-14, KK-41, KK-46). Bilinmeyen kod: errorMsg + kod.
ERROR_MESSAGES = {
    'ERR10199': 'Telefon numarası Paratika tarafından geçersiz bulundu. Numarayı kontrol edin.',
    'ERR10233': 'E-posta adresi Paratika tarafından geçersiz bulundu. Adresi kontrol edin.',
    'ERR10244': 'Paratika telefon ve e-posta bilgilerini birlikte istiyor.',
    'ERR10012': 'Bir alan izin verilen uzunluk sınırını aşıyor.',
    'ERR10010': 'Paratika zorunlu bir alanın boş olduğunu bildirdi.',
    'ERR10020': 'Paratika API kullanıcısı doğrulanamadı; yöneticinize başvurun.',
    'ERR10047': 'API yetkisi eksik; yöneticinize başvurun.',
    'ERR10053': 'Bu işyeri için API yetkisi yok; yöneticinize başvurun.',
    'ERR10266': 'Bu API işlemi işyeri için kapalı; yöneticinize başvurun.',
    'ERR10048': 'Bu sipariş numarasıyla zaten başarılı bir ödeme var.',
    'ERR10107': 'Bu sipariş numarası için ödeme zaten yapılmış.',
    'ERR10117': 'Bu sipariş numarası daha önce kullanılmış ve oturumu sona ermiş.',
    'ERR10118': 'Bu sipariş numarası kullanımda ancak tutar veya ayarlar değişmiş.',
    'ERR10143': 'Link zaten ödenmiş veya iptal edilmiş.',
    'ERR10221': 'Linkin geçerlilik süresi dolmuş.',
    'ERR10054': 'Link geçerlilik süresi izin verilen azami sürenin üstünde.',
    'ERR10055': 'Link geçerlilik süresi izin verilen asgari sürenin altında.',
    'ERR10033': 'Gün sonu geçtiği için iptal edilemedi; iade (REFUND) yapın.',
    'ERR20040': 'Gün sonu geçmeden iade yapılamaz; ödemeyi iptal edin.',
    'ERR10031': 'Bu işlem iade edilemez.',
    'ERR10032': 'Geçersiz iade tutarı ya da işlem zaten iade edilmiş.',
    'ERR10262': 'Bu işlem için kısmi iade yapılamıyor.',
    'ERR10030': 'İşlem Paratika\'da bulunamadı.',
}
# Bağlantı testi: kimlik reddi ve yetki eksikliği kodları
AUTH_ERROR_CODES = ('ERR10020',)
PERMISSION_ERROR_CODES = ('ERR10047', 'ERR10053', 'ERR10266')

# Paratika transactionType -> normalize tür
_KIND_BY_TYPE = {
    'SALE': 'sale',
    'REFUND': 'refund',
    'PTREFUND': 'refund',
    'CREDIT': 'refund',
    'VOID': 'void',
}
# Paratika transactionStatus -> normalize durum
_STATUS_BY_CODE = {
    'AP': 'approved',
    'FA': 'failed',
    'CA': 'cancelled',
    'IP': 'pending',
    'MR': 'review',
    'VD': 'voided',
}


def _amount_text(value):
    """``'%.2f'``: nokta ayıraçlı, 2 hane, binliksiz (KK-12)."""
    amount = Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return format(amount, 'f')


def _to_decimal(value):
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return Decimal('0')


def _parse_time(value):
    """Paratika zaman metni -> naive UTC datetime ya da ``None``.

    Biçim belgesiz (P-10): ISO-8601, ``dd-MM-yyyy HH:mm[:ss]``, ``yyyy-MM-dd HH:mm:ss`` ve
    epoch (ms) denenir. Saat dilimi yoksa Europe/Istanbul varsayılır.
    """
    if value in (None, '', False):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).strip().isdigit():
            number = float(value)
            if number > 1e11:
                number /= 1000.0
            return datetime.fromtimestamp(number, _UTC).replace(tzinfo=None)
        text = str(value).strip()
        parsed = None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            for fmt in ('%d-%m-%Y %H:%M:%S', '%d-%m-%Y %H:%M', '%Y-%m-%d %H:%M:%S'):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_ISTANBUL)
        return parsed.astimezone(_UTC).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None


class SanalPosProviderParatika(models.AbstractModel):
    _name = 'sanal.pos.provider.paratika'
    _inherit = 'sanal.pos.provider'
    _description = 'Sanal POS Sağlayıcısı: Paratika'

    # ---------------------------------------------------------------- ayarlar
    def _param(self, key):
        return self.env['ir.config_parameter'].sudo().get_param(key) or ''

    def _credentials(self):
        # Kopyala-yapıştırla gelen baş/son boşluk Paratika'da ERR10020 verir
        return {
            'MERCHANT': self._param('sanal_pos.paratika_merchant').strip(),
            'MERCHANTUSER': self._param('sanal_pos.paratika_merchant_user').strip(),
            'MERCHANTPASSWORD': self._param('sanal_pos.paratika_merchant_password').strip(),
        }

    def _secrets(self):
        """Log/mesajlardan süzülecek sır değerleri."""
        raw = [self._param('sanal_pos.paratika_merchant_password'),
               self._param('sanal_pos.paratika_secret_key')]
        # Bağlantı testinde ekrandaki (henüz kaydedilmemiş) şifre de süzülür
        raw += list(self.env.context.get('sanal_pos_extra_secrets') or [])
        # İstekte boşluksuz gönderildiği için hem ham hem boşluksuz hali süzülür
        return [s for s in dict.fromkeys(raw + [(v or '').strip() for v in raw]) if s]

    def _api_url(self, payment, environment=None):
        """Kayıt ortamına göre kök adres (KK-52: ayar değil, kaydın ortamı geçerli)."""
        if (environment or payment.environment) == 'live':
            url = self._param('sanal_pos.paratika_live_url') or DEFAULT_LIVE_URL
        else:
            url = self._param('sanal_pos.paratika_test_url') or DEFAULT_TEST_URL
        return url.strip().rstrip('/')

    def _link_url(self, payment, token):
        """Ödeme sayfası adresi (gösterim ayarla açılır, KK-17).

        Biçim canlıda Paratika'nın kendi SMS'inden teyit edildi (2026-10-21):
        ``https://vpos.paratika.com.tr/payment/<sessionToken>?lang=tr``. Dokümandaki
        ``/merchant/payment/<token>`` örneği bu linkte "beklenmedik hata" veriyor.
        """
        parts = urlsplit(self._api_url(payment))
        if not (parts.scheme and parts.netloc and token):
            return None
        return '%s://%s/payment/%s?lang=tr' % (parts.scheme, parts.netloc, token)

    def _return_url(self):
        base = (self._param('web.base.url') or '').strip().rstrip('/')
        return base + RETURN_PATH if base else ''

    # ---------------------------------------------------------------- maskeleme
    def _clean_value(self, value, secrets, key=''):
        """Log için: sırları süz, e-posta/telefon alanlarını maskele (özyinelemeli)."""
        if isinstance(value, dict):
            return {k: self._clean_value(v, secrets, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self._clean_value(v, secrets, key) for v in value]
        if isinstance(value, str):
            lowered = key.lower()
            if value and 'email' in lowered:
                return tools.scrub(tools.mask_email(value), secrets)
            if value and 'phone' in lowered:
                return tools.scrub(tools.mask_phone(value), secrets)
            return tools.scrub(value, secrets)
        return value

    def _mask_request(self, params):
        secrets = self._secrets()
        masked = tools.mask_params(params, ['MERCHANTPASSWORD'])
        text = json.dumps(self._clean_value(masked, secrets), ensure_ascii=False)
        return tools.scrub(text, secrets)

    def _mask_response(self, data, raw_text=''):
        secrets = self._secrets()
        if data is not None:
            text = json.dumps(self._clean_value(data, secrets), ensure_ascii=False)
        else:
            text = raw_text or ''
        return tools.scrub(text, secrets)

    # ---------------------------------------------------------------- HTTP
    def _post(self, url, body):
        """Tek HTTP noktası (testte ``requests.Session.send`` seviyesinde yakalanır)."""
        return requests.post(
            url, data=body, headers={'Content-Type': CONTENT_TYPE},
            timeout=TIMEOUT, allow_redirects=False)

    def _error_message(self, code, message):
        text = ERROR_MESSAGES.get(code)
        if not text:
            detail = message or 'Bilinmeyen hata'
            text = '%s (%s)' % (detail, code) if code else detail
        return tools.scrub(text, self._secrets())

    def _call(self, payment, action, params, environment=None, credentials=None, api_url=None):
        """Paratika'ya tek istek. Asla istisna fırlatmaz; ham sonuç sözlüğü döner.

        Dönüş: ``ok, timeout, error_code, error_message, raw_code, data``
        (``data`` ayrıştırılmış JSON ya da ``None``).

        ``environment`` / ``credentials`` / ``api_url`` yalnız bağlantı testinde verilir
        (``payment`` boş kayıt kümesidir; ayar ekranındaki kaydedilmemiş değerler denenir).
        """
        environment = environment or payment.environment
        credentials = credentials or self._credentials()
        if not all(credentials.values()):
            return self._result(
                error_code='CONFIG', data=None,
                error_message='Paratika ayarları eksik; yöneticinize başvurun.')
        request_params = {'ACTION': action}
        request_params.update(credentials)
        request_params.update(params)
        # Boş opsiyonel alanlar gönderilmez
        request_params = {k: v for k, v in request_params.items()
                          if v not in (None, False, '')}
        body = urlencode(request_params, encoding='utf-8').encode('ascii')
        url = api_url or self._api_url(payment, environment)
        request_log = self._mask_request(request_params)
        financial = action in FINANCIAL_ACTIONS
        uncertain_on_failure = action in STATE_CHANGING_ACTIONS

        started = time.monotonic()
        http_status = 0
        data = None
        raw_text = ''
        try:
            response = self._post(url, body)
        except requests.exceptions.RequestException as exc:
            # Zaman aşımı, ağ ve TLS hataları: isteğin ulaşıp ulaşmadığı bilinemez
            result = self._result(
                timeout=True, error_code='TIMEOUT', error_message=TIMEOUT_MESSAGE)
            raw_text = tools.scrub('%s: %s' % (type(exc).__name__, exc), self._secrets())
        else:
            http_status = response.status_code
            raw_text = response.content.decode('utf-8', errors='replace')
            try:
                parsed = json.loads(raw_text)
                data = parsed if isinstance(parsed, dict) else None
            except ValueError:
                data = None
            result = self._interpret(action, http_status, data, uncertain_on_failure)
        duration_ms = int((time.monotonic() - started) * 1000)

        raw_code = result.get('raw_code')
        self._log_call(
            payment, action, 'paratika', environment, duration_ms=duration_ms,
            http_status=http_status, response_code=raw_code,
            error_code=result['error_code'], success=result['ok'],
            request_body=request_log, response_body=self._mask_response(data, raw_text),
            is_financial=financial)
        # Python log'una gövde/kişisel veri yazılmaz (yalnız tanılama alanları)
        _logger.info('Paratika %s mpid=%s responseCode=%s errorCode=%s süre=%dms',
                     action, payment.merchant_payment_id, raw_code,
                     result['error_code'] or '-', duration_ms)
        result['data'] = data
        return result

    def _interpret(self, action, http_status, data, uncertain_on_failure):
        """HTTP durumu + gövdeden normalize sonuç."""
        if http_status >= 500:
            return self._result(
                timeout=uncertain_on_failure, error_code='HTTP%d' % http_status,
                error_message=(TIMEOUT_MESSAGE if uncertain_on_failure else
                               'Paratika geçici olarak hizmet vermiyor (HTTP %d).' % http_status))
        if http_status != 200:
            return self._result(
                error_code='HTTP%d' % http_status,
                error_message='Paratika beklenmeyen bir yanıt verdi (HTTP %d).' % http_status)
        if data is None or 'responseCode' not in data:
            # 200 ama çözülemeyen yanıt: durumu değiştiren çağrılarda sonuç belirsizdir
            return self._result(
                timeout=uncertain_on_failure, error_code='INVALID_RESPONSE',
                error_message='Paratika yanıtı anlaşılamadı.')
        response_code = str(data.get('responseCode') or '')
        if response_code == '00':
            return self._result(ok=True, raw_code=response_code)
        code = str(data.get('errorCode') or '') or 'RC%s' % response_code
        message = str(data.get('errorMsg') or data.get('responseMsg') or '')
        return self._result(
            error_code=code, raw_code=response_code,
            error_message=self._error_message(code, message))

    # ---------------------------------------------------------------- arayüz: bağlantı testi
    @api.private
    def test_connection(self, environment, credentials, api_url):
        """Kimlik bilgisini salt-okuma bir sorguyla dener (link/para hareketi yok).

        Var olmayan bir ödeme numarası için QUERYTRANSACTION gönderilir. Paratika önce
        kullanıcıyı doğrular; "kayıt yok" gibi bir yanıt da kimliğin geçerli olduğunu gösterir.
        Ek anahtarlar: ``reached`` (sunucu anlamlı yanıt verdi), ``authenticated``,
        ``problem`` (``config|network|address|auth|permission|None``).
        """
        provider = self.with_context(
            sanal_pos_extra_secrets=[credentials.get('MERCHANTPASSWORD') or ''])
        res = provider._call(
            self.env['sanal.pos.payment'], 'QUERYTRANSACTION',
            {'MERCHANTPAYMENTID': 'BAGLANTI-TESTI-%d' % int(time.time())},
            environment=environment, credentials=credentials, api_url=api_url)
        res.pop('data', None)
        code = res['error_code']
        if res['ok']:
            problem = None
        elif code == 'CONFIG':
            problem = 'config'
        elif res['timeout']:
            problem = 'network'
        elif code and (code.startswith('HTTP') or code == 'INVALID_RESPONSE'):
            problem = 'address'
        elif code in AUTH_ERROR_CODES:
            problem = 'auth'
        elif code in PERMISSION_ERROR_CODES:
            problem = 'permission'
        else:
            # Kullanıcı doğrulandı; sorgu başka bir nedenle reddedildi (ör. kayıt yok)
            problem = None
        res.update(
            reached=problem not in ('config', 'network', 'address'),
            authenticated=problem is None,
            problem=problem)
        return res

    # ---------------------------------------------------------------- arayüz: link
    @api.private
    def create_link(self, payment):
        payment.ensure_one()
        payment = payment.sudo()
        return_url = self._return_url()
        if not return_url or not return_url.isascii():
            return self._result(
                error_code='RETURNURL',
                error_message="Sistem adresi (web.base.url) yalnızca ASCII karakter içermelidir; "
                              "yöneticinize başvurun.")
        ascii_mode = get_bool_param(self.env, 'sanal_pos.ascii_mode', default=False)

        def text(value):
            value = value or ''
            return tools.to_ascii(value) if ascii_mode else value

        phone_format = self._param('sanal_pos.paratika_phone_format')
        if phone_format not in tools.PHONE_FORMATS:
            phone_format = '10'
        phone = payment.customer_phone
        if phone:
            phone = tools.format_phone_for_provider(phone, phone_format)
        channels = [name for key, name in (('email', 'EMAIL'), ('sms', 'SMS'))
                    if payment['channel_%s' % key]]
        address = text(payment.customer_address)
        city = text(payment.customer_city)
        zip_code = payment.customer_zip
        params = {
            'MERCHANTPAYMENTID': payment.merchant_payment_id,
            'AMOUNT': _amount_text(payment.amount),
            'CURRENCY': payment.currency_id.name or 'TRY',
            'CUSTOMER': payment.customer_code or 'INV-%s' % payment.invoice_no,
            'CUSTOMERNAME': text(payment.customer_name),
            'CUSTOMERPHONE': phone,
            'CUSTOMEREMAIL': payment.customer_email,
            'NOTIFICATIONCHANNELS': ','.join(channels),
            'SESSIONEXPIRY': '%dh' % payment.expiry_hours,
            'RETURNURL': return_url,
            # U-2: not = ödeme numarası (deneme sırası dahil); find_link bununla arar
            'MERCHANTNOTE': self._note(payment),
            'BILLTOADDRESSLINE': address,
            'BILLTOCITY': city,
            'BILLTOPOSTALCODE': zip_code,
            'BILLTOCOUNTRY': 'TUR' if (address or city or zip_code) else '',
        }
        res = self._call(payment, 'PAYBYLINKPAYMENT', params)
        data = res.pop('data')
        if res['ok']:
            token = (data or {}).get('sessionToken')
            if not token:
                # 00 döndü ama token yok: link oluşmuş olabilir -> belirsiz
                return self._result(
                    timeout=True, error_code='NO_TOKEN', raw_code=res['raw_code'],
                    error_message='Paratika link bilgisini döndürmedi; durum kontrol edilecek.')
            res['token'] = str(token)
            res['url'] = self._link_url(payment, res['token'])
        return res

    @api.private
    def resend(self, payment, channels):
        payment.ensure_one()
        payment = payment.sudo()
        names = [CHANNEL_NAMES[c] for c in ('email', 'sms') if c in (channels or [])]
        if not names:
            return self._result(error_code='NO_CHANNEL',
                                error_message='Gönderim kanalı seçilmedi.')
        res = self._call(payment, 'PAYBYLINKPAYMENTRESEND', {
            'PAYBYLINKTOKEN': payment.provider_token,
            'NOTIFICATIONCHANNELS': ','.join(names),
        })
        res.pop('data')
        return res

    @api.private
    def cancel_link(self, payment):
        payment.ensure_one()
        payment = payment.sudo()
        res = self._call(payment, 'PAYBYLINKPAYMENTCANCEL', {
            'PAYBYLINKTOKEN': payment.provider_token})
        res.pop('data')
        # ERR10143: link zaten PAID veya CANCELED (KK-32: gerçek durum sorguyla yazılır)
        res['already_closed'] = res['error_code'] == 'ERR10143'
        return res

    @api.private
    def find_link(self, payment):
        """Belirsiz linki uzlaştırır (KK-16): MERCHANTNOTE + tarih aralığı ile arar.

        Eşleşme: tutar eşit, ``createdTs`` gönderimden 2 dk öncesinden yeni, token başka
        kayıtta kullanılmamış. Birden fazla aday ya da liste dolu ama aday yok (Ö-B) ->
        ``ambiguous=True``, ``ok=False``, ``timeout=True`` (kayıt Belirsiz kalır; yönetici
        Paratika panelinden bakar). Yalnız boş liste "bulunamadı"dır.
        """
        payment.ensure_one()
        payment = payment.sudo()
        base = payment.sent_at or payment.create_date or datetime.utcnow()
        start = base - timedelta(hours=1)
        end = base + timedelta(days=1)

        def to_param(value):
            return value.replace(tzinfo=_UTC).astimezone(_ISTANBUL).strftime('%d-%m-%Y %H:%M')

        res = self._call(payment, 'QUERYPAYBYLINKPAYMENT', {
            'MERCHANTNOTE': self._note(payment),
            'STARTDATE': to_param(start),
            'ENDDATE': to_param(end),
        })
        data = res.pop('data')
        res.update(found=False, token=None, status=None, ambiguous=False)
        if not res['ok']:
            return res
        sending_at = (payment.create_date or base) - timedelta(minutes=2)
        used = self.env['sanal.pos.payment'].sudo()
        candidates = []
        items = (data or {}).get('payByLinkPaymentList') or []
        for item in items:
            token = item.get('token')
            if not token:
                continue
            if _to_decimal(item.get('amount')) != _to_decimal(_amount_text(payment.amount)):
                continue
            created = _parse_time(item.get('createdTs'))
            if created and created < sending_at:
                continue
            if used.search_count([('provider_token', '=', token), ('id', '!=', payment.id)]):
                continue
            candidates.append(item)
        if len(candidates) > 1:
            res.update(
                ok=False, timeout=True, ambiguous=True, error_code='AMBIGUOUS',
                error_message='Birden fazla aday link bulundu; Paratika panelinden kontrol edin.')
        elif items and not candidates:
            # Ö-B: MPID notuyla kalem döndü ama hiçbiri eşleşmedi (tutar/zaman/token). Bu
            # "bulunamadı" değildir; sayılırsa kayıt Hata olur ve geç ödeme çift tahsilata döner.
            res.update(
                ok=False, timeout=True, ambiguous=True, error_code='AMBIGUOUS',
                error_message='Ödeme numarasıyla eşleşmeyen link kaydı bulundu; Paratika panelinden kontrol edin.')
        elif candidates:
            res.update(found=True, token=str(candidates[0]['token']),
                       status=candidates[0].get('status'))
        return res

    # ---------------------------------------------------------------- arayüz: durum
    @api.private
    def query_status(self, payment):
        payment.ensure_one()
        payment = payment.sudo()
        res = self._call(payment, 'QUERYTRANSACTION', {
            'MERCHANTPAYMENTID': payment.merchant_payment_id})
        data = res.pop('data')
        res['transactions'] = []
        if res['ok']:
            res['transactions'] = [
                self._normalize_transaction(item)
                for item in (data or {}).get('transactionList') or []
                if isinstance(item, dict)]
        return res

    def _normalize_transaction(self, item):
        ttype = str(item.get('transactionType') or '').upper()
        code = str(item.get('transactionStatus') or '').upper()
        kind = _KIND_BY_TYPE.get(ttype, ttype.lower())
        status = _STATUS_BY_CODE.get(code, code.lower())
        if kind == 'sale' and status == 'voided':
            # Satışın iptali (VD): iptal işlemi olarak da okunur (P-10, iki biçim desteklenir)
            kind, status = 'void', 'approved'
        try:
            installments = max(int(item.get('installmentCount') or 0), 1)
        except (TypeError, ValueError):
            installments = 1
        currency = str(item.get('currency') or '').upper() or None
        return {
            'ref': item.get('pgTranId'),
            'kind': kind,
            'status': status,
            'amount': _to_decimal(item.get('amount')),
            'currency': currency,
            'time': _parse_time(item.get('timeCreated')),
            'installment_count': installments,
            'card_last4': item.get('panLast4') or None,
            'raw_type': ttype,
            'raw_status': code,
        }

    # ---------------------------------------------------------------- arayüz: iptal / iade
    @api.private
    def void(self, payment, refund_line):
        payment.ensure_one()
        payment = payment.sudo()
        if not payment.provider_tran_ref:
            return self._result(error_code='NO_TRAN_REF',
                                error_message='Ödemenin işlem numarası yok; iptal yapılamaz.')
        res = self._call(payment, 'VOID', {
            'PGTRANID': payment.provider_tran_ref,
            'MERCHANTPAYMENTID': payment.merchant_payment_id,
        })
        return self._financial_result(res)

    @api.private
    def refund(self, payment, refund_line):
        payment.ensure_one()
        payment = payment.sudo()
        if not payment.provider_tran_ref:
            return self._result(error_code='NO_TRAN_REF',
                                error_message='Ödemenin işlem numarası yok; iade yapılamaz.')
        res = self._call(payment, 'REFUND', {
            'PGTRANID': payment.provider_tran_ref,
            'MERCHANTPAYMENTID': payment.merchant_payment_id,
            'AMOUNT': _amount_text(refund_line.amount),
            'CURRENCY': payment.currency_id.name or 'TRY',
        })
        return self._financial_result(res)

    def _financial_result(self, res):
        data = res.pop('data')
        res['ref'] = None
        if res['ok']:
            data = data or {}
            res['ref'] = data.get('pgTranId') or data.get('pgTranRefId') or None
        return res

    # ---------------------------------------------------------------- arayüz: bildirim
    @api.model
    @api.private
    def parse_notification(self, params):
        """Bildirim/dönüş POST'undan yalnız ödeme numarasını okur (tetik; AMOUNT/STATUS okunmaz)."""
        for key, value in (params or {}).items():
            if str(key).lower() == 'merchantpaymentid':
                value = (str(value) if value is not None else '').strip()
                if value and len(value) <= 128:
                    return value
        return None

    # ---------------------------------------------------------------- yardımcı
    @staticmethod
    def _note(payment):
        return (payment.merchant_payment_id or '')[:NOTE_MAX]
