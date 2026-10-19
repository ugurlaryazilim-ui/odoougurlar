"""Turatel SMS (processor.smsorigin.com) XML istemcisi — Odoo'dan bağımsız, test edilebilir.

Komutlar:
    0 = SMS gönder (<MainmsgBody>)
    3 = Gönderim raporu (<MainReportRoot> + MsgID)
    6 = Kalan kredi (<MainReportRoot>)

Başarılı gönderimde cevap "ID:<mesaj id>" biçimindedir; hatada sayısal kod döner.
"""
import http.client
import logging
import re
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

import pytz
import requests
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError, ProtocolError, ReadTimeoutError

_logger = logging.getLogger(__name__)

DEFAULT_URL = 'https://processor.smsorigin.com/xml/process.aspx'
TIMEOUT = (5, 15)   # (bağlanma, okuma) saniye: bağlanamama çabuk anlaşılır, yanıt bekleme sınırlı

# Türkçe'ye özgü (GSM 7-bit tabloda olmayan) karakterler: varsa Type=2 gerekir
TURKISH_CHARS = set('İıĞğŞş')
ASCII_MAP = str.maketrans({'İ': 'I', 'ı': 'i', 'Ğ': 'G', 'ğ': 'g', 'Ş': 'S', 'ş': 's'})

# Olası hata kodları — Turatel'in güncel listesiyle ilk canlı testte doğrulanacak; ham cevap her zaman saklanır
ERROR_HINTS = {
    '20': 'Gönderilen XML hatalı veya eksik — metinde desteklenmeyen karakter olabilir',
    '30': 'Kanal kodu / kullanıcı adı / şifre hatalı ya da hesap aktif değil — Ayarlar > SMS bilgilerini kontrol edin',
    '40': 'Mesaj başlığı (Originator) hesapta tanımlı değil — Ayarlar > SMS > Mesaj Başlığı Turatel hesabındaki ile aynı olmalı',
    '50': 'Hesapta yeterli kredi yok — Turatel üzerinden kredi yükleyin',
    '51': 'Numara hatalı veya gönderime kapalı',
    '70': 'Eksik veya hatalı parametre',
    '85': 'Mükerrer gönderim — aynı metin aynı numaraya kısa sürede tekrar gönderilmiş',
}

MAX_SEGMENTS = 7  # bundan uzun metinler gönderilmez (operatör reddedebilir, kredi israfı)


class TuratelError(Exception):
    """Turatel'den hata kodu ya da bağlantı hatası.

    retryable: isteğin Turatel'e HİÇ gitmediği kesin olan geçici hatalar (bağlantı kurulamadı, DNS); yeniden
    denenebilir. uncertain: isteğin gidip gitmediği/işlenip işlenmediği belli olmayan hatalar (okuma zaman aşımı,
    kopan bağlantı, HTTP 200 dışı); mükerrer SMS olmasın diye asla otomatik yeniden gönderilmez.
    Hesap, başlık, kredi, numara gibi kalıcı hatalarda ikisi de False. İkisi aynı anda True olamaz.
    """

    def __init__(self, message, retryable=False, uncertain=False):
        if retryable and uncertain:
            raise ValueError('retryable ve uncertain aynı anda True olamaz')
        super().__init__(message)
        self.retryable = retryable
        self.uncertain = uncertain


# İstek gövdesi gönderildikten sonra (ya da gönderilirken) kopan bağlantı belirtileri: işlenip işlenmediği bilinmez
_SENT_MAYBE = (ProtocolError, ReadTimeoutError, http.client.RemoteDisconnected, ConnectionResetError,
               ConnectionAbortedError, BrokenPipeError)
# Bağlantı hiç kurulamadı: istek kesinlikle gitmedi (DNS çözülemedi, bağlantı reddedildi, bağlanma zaman aşımı)
_NOT_SENT = (NewConnectionError, ConnectTimeoutError)
# İstek oluşturulamadı (adres/başlık hatası): ağa çıkılmadı, yeniden denemek işe yaramaz
_BAD_REQUEST = (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema,
                requests.exceptions.InvalidSchema, requests.exceptions.InvalidHeader,
                requests.exceptions.URLRequired)


def _exception_chain(exc, limit=12):
    """İstisnayı ve nedenlerini (``__cause__``, ``__context__``, urllib3 ``reason``, ``args``) düz liste yap."""
    seen, stack = [], [exc]
    while stack and len(seen) < limit:
        item = stack.pop()
        if not isinstance(item, BaseException) or any(item is known for known in seen):
            continue
        seen.append(item)
        stack.extend([item.__cause__, item.__context__, getattr(item, 'reason', None)] + list(item.args))
    return seen


def classify_request_exception(exc):
    """requests istisnasını ``TuratelError``'a çevir: istek gitmediyse geçici, gidip gitmediği belirsizse uncertain.

    Emin olunamayan her durum belirsizdir (yanlışlıkla yeniden göndermek yanlışlıkla beklemekten pahalı).
    """
    name = exc.__class__.__name__
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return TuratelError('Turatel sunucusuna ulaşılamadı: %s' % name, retryable=True)
    if isinstance(exc, _BAD_REQUEST):
        return TuratelError('Turatel adresi geçersiz: %s' % name)
    chain = _exception_chain(exc)
    if (not isinstance(exc, requests.exceptions.Timeout)
            and not any(isinstance(item, _SENT_MAYBE) for item in chain)
            and any(isinstance(item, _NOT_SENT) for item in chain)):
        return TuratelError('Turatel sunucusuna ulaşılamadı: %s' % name, retryable=True)
    return TuratelError('Turatel yanıtı alınamadı (%s); iletilip iletilmediği belirsiz.' % name, uncertain=True)


def normalize_number(raw):
    """TR cep numarasını Turatel biçimine çevir: 5XXXXXXXXX. Geçersizse None."""
    digits = re.sub(r'\D', '', raw or '')
    if digits.startswith('90') and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith('0') and len(digits) == 11:
        digits = digits[1:]
    if len(digits) == 10 and digits.startswith('5'):
        return digits
    return None


def mask_number(raw):
    """Telefonu log/istisna metni için maskele: 5321234567 → 532*****67 (ilk 3 + son 2 hane).

    Geçerli TR cep numarası değilse (biçimi bilinmeyen girdi) yalnız son 2 hane gösterilir; boş girdi sabit
    '-' döner. Ham numara loga ve hata metnine yazılmaz (KVKK).
    """
    number = normalize_number(raw)
    if number:
        return '%s*****%s' % (number[:3], number[-2:])
    digits = re.sub(r'\D', '', str(raw or ''))
    if not digits:
        return '-'
    return '*' * max(len(digits) - 2, 0) + digits[-2:]


def prepare_text(text, ascii_mode=False):
    """Metni hazırla ve Turatel Type değerini döndür: (metin, type)."""
    text = (text or '').strip()
    if ascii_mode:
        text = text.translate(ASCII_MAP)
    return text, ('2' if TURKISH_CHARS & set(text) else '1')


def segment_count(text, sms_type='1'):
    """Tahmini SMS parça sayısı (Type 1: 160/153, Type 2 Türkçe: 155/149)."""
    length = len(text or '')
    single, multi = (160, 153) if sms_type == '1' else (155, 149)
    if length <= single:
        return 1
    return -(-length // multi)


def _cdata(text):
    # "]]>" CDATA'yı erken kapatmasın
    return '<![CDATA[%s]]>' % (text or '').replace(']]>', ']]]]><![CDATA[>')


class TuratelClient:
    def __init__(self, channel_code, username, password, url=None, timeout=TIMEOUT):
        self.channel_code = (channel_code or '').strip()
        self.username = (username or '').strip()
        self.password = password or ''
        self.url = (url or DEFAULT_URL).strip()
        self.timeout = timeout

    def _auth(self):
        return ('<ChannelCode>%s</ChannelCode><UserName>%s</UserName><PassWord>%s</PassWord>'
                % (escape(self.channel_code), escape(self.username), escape(self.password)))

    def build_send_xml(self, numbers, text, originator, sms_type='1', now=None):
        now = now or datetime.now(pytz.timezone('Europe/Istanbul'))
        fmt = '%d%m%Y%H%M'
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<MainmsgBody><Command>0</Command><PlatformID>1</PlatformID>'
            '%s<Mesgbody>%s</Mesgbody><Numbers>%s</Numbers><Type>%s</Type><Concat>1</Concat>'
            '<Originator>%s</Originator><SDate>%s</SDate><EDate>%s</EDate></MainmsgBody>'
        ) % (self._auth(), _cdata(text), escape(','.join(numbers)), sms_type, escape(originator or ''),
             now.strftime(fmt), (now + timedelta(hours=21)).strftime(fmt))

    def build_report_xml(self, msg_id):
        return ('<?xml version="1.0" encoding="utf-8"?><MainReportRoot><Command>3</Command>'
                '<PlatformID>1</PlatformID>%s<MsgID>%s</MsgID></MainReportRoot>') % (self._auth(), escape(str(msg_id)))

    def build_credit_xml(self):
        return ('<?xml version="1.0" encoding="utf-8"?><MainReportRoot><Command>6</Command>'
                '%s</MainReportRoot>') % self._auth()

    def _post(self, xml):
        if not (self.channel_code and self.username and self.password):
            raise TuratelError('Turatel kanal kodu, kullanıcı adı ve şifre ayarlardan girilmelidir.')
        try:
            resp = requests.post(self.url, data=xml.encode('utf-8'), timeout=self.timeout,
                                 headers={'Content-Type': 'text/xml; charset=utf-8'})
        except requests.RequestException as e:
            raise classify_request_exception(e) from e
        if resp.status_code != 200:
            # İstek sunucuya ulaştı; işlenip işlenmediği bilinmez (5xx dahil): mükerrer riski → belirsiz
            raise TuratelError('Turatel HTTP %s döndü; iletilip iletilmediği belirsiz.' % resp.status_code,
                               uncertain=True)
        return (resp.text or '').strip()

    @staticmethod
    def error_text(code):
        return ERROR_HINTS.get(code.strip(), 'Turatel hata kodu')

    def send(self, numbers, text, originator, sms_type='1'):
        """Gönder; başarıda Turatel mesaj id'sini döndür, hatada TuratelError."""
        answer = self._post(self.build_send_xml(numbers, text, originator, sms_type))
        if answer.upper().startswith('ID:'):
            return answer[3:].strip(), answer
        raise TuratelError('%s (%s)' % (self.error_text(answer), answer[:50]))

    def report(self, msg_id):
        return self._post(self.build_report_xml(msg_id))

    def credit(self):
        """Kalan kredi sorgusu — ham cevabı döndürür (kredi miktarı ya da hata kodu).

        İki haneli bir sayı hem kredi hem hata kodu olabileceği için yorum çağırana bırakılır.
        """
        return self._post(self.build_credit_xml())
