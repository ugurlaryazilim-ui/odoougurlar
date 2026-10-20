"""SmartADM (Turatel İYS / KVKK izin yönetimi) JSON istemcisi — Odoo'dan bağımsız, test edilebilir.

Doküman: https://doc.smartadm.net/
    POST /session          CustomerCode/Username/Password → SessionId (15 dk)
    POST /query            Msisdn ile kişinin izinleri (Authorization.Etk.Msisdn.Sms: "1" onay, "0" ret)
    POST /Contact          kişi kartı oluştur (kaydı olmayan kişide trigger/contactapiload'dan ÖNCE şart)
    POST /report2          tarih aralığındaki izin hareketleri (en fazla 7 gün, sayfalı)
    POST /contactapiload   izni doğrudan yükle (ONAY/RET + tarih + kaynak)
    POST /trigger, /approve  SMS ile onay kodu göndererek izin alma

Akış: Session → Contact (kişi yoksa) → Trigger → Approve  ya da  Session → Contact → ContactApiLoad.
Kaydı olmayan kişide Contact çağrılmadan trigger/contactapiload -6/-601 "Kişi kayıtlarda yok" döner.

Tüm cevaplar: {Status, StatusCode, SubStatusCode, Value, MaxPage}; 0/0 başarılı.
SmartADM SMS göndermez — gönderim Turatel'den yapılır.
"""
import json
import logging
import re

import requests

from .turatel import mask_number

# 10+ haneli rakam dizisi (araya boşluk, tire, nokta, parantez girebilir): sunucu metnindeki telefon numarası
_PHONE_RUN = re.compile(r'\+?\d(?:[\s\-().]*\d){9,}')

_logger = logging.getLogger(__name__)

DEFAULT_URL = 'https://adm.smartadm.net/webservice/api'
# RemoteStoreId (HTTP başlığı) boş bırakılması önerilmez; ayar boşsa bu sabit değer tüm çağrılarda gönderilir
DEFAULT_STORE = 'MERKEZ'
TIMEOUT = 20

ERROR_TEXTS = {
    (-1, -1): 'Kullanıcı geçersiz — SmartADM müşteri kodu / kullanıcı adı / şifreyi kontrol edin',
    (-1, -2): 'SmartADM kullanıcısının süresi dolmuş',
    (-1, -3): 'SmartADM kullanıcısı aktif değil',
    (-1, -4): 'SmartADM kullanıcı tanımı hatalı',
    (-1, -6): 'Oturum geçersiz',
    (-1, -7): 'Oturum süresi doldu',
    (-3, -114): 'Telefon numarası biçimi geçersiz',
    (-5, -512): 'Tarih aralığı 7 günü geçemez',
    (-6, -601): 'Kişi İYS/SmartADM kayıtlarında yok',
    (-6, -602): 'Onay kodu bulunamadı',
    (-6, -604): 'Onay SMS\'i gönderilemedi',
    (-6, -607): 'İstenen izinler İYS\'de zaten mevcut',
    (-6, -609): 'KVKK onayı gerekli',
    (-6, -611): 'ETK (ticari ileti) onayı gerekli',
    (-6, -613): 'Kişi kartı yakın zamanda zaten oluşturulmuş',
    (-6, -614): 'Marka kodu (BrandCode) gerekli — Ayarlar > SMS > İYS Marka Kodu',
    (-6, -615): 'Marka kodu bulunamadı — Ayarlar > SMS > İYS Marka Kodu',
    (-6, -9999): 'Bu özellik SmartADM hesabınızda kapalı',
    (-7, -700): 'İYS kurallarına aykırı işlem',
    (-99, -99): 'SmartADM sunucu hatası',
}
SESSION_ERRORS = {(-1, -6), (-1, -7)}
NOT_FOUND = (-6, -601)
# Hata değil, bilgi: kişi kartı yakın zamanda zaten oluşturulmuş (kart var sayılır) / istenen izin zaten kayıtlı
CONTACT_EXISTS = (-6, -613)
ALREADY_CONSENTED = (-6, -607)
# Numaraya özgü kalıcı hatalar: hesabı değil yalnız o numarayı ilgilendirir (D-8)
INVALID_NUMBER_CODES = {(-3, -114)}


class SmartAdmError(Exception):
    """SmartADM hatası. retryable: geçici (sonra tekrar denenebilir). invalid_number: yalnız bu numaraya özgü
    kalıcı hata (biçim geçersiz); hesap/oturum sorunu değildir, toplu sorgu diğer numaralarla sürebilir."""

    def __init__(self, message, code=None, retryable=False, invalid_number=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.invalid_number = invalid_number


def to_msisdn(number):
    """5XXXXXXXXX → 905XXXXXXXXX (SmartADM biçimi)."""
    digits = re.sub(r'\D', '', number or '')
    if len(digits) == 10 and digits.startswith('5'):
        return '90' + digits
    if len(digits) == 12 and digits.startswith('905'):
        return digits
    return None


def from_msisdn(value):
    """905XXXXXXXXX → 5XXXXXXXXX; maskeli (9053******22) ya da geçersizse None."""
    digits = value or ''
    if re.fullmatch(r'905\d{9}', digits):
        return digits[2:]
    return None


def split_name(full_name):
    """'Ad Soyad' → ('Ad', 'Soyad'): son boşluktan bölünür ('Ayşe Nur Yılmaz' → 'Ayşe Nur', 'Yılmaz').
    Tek kelimede soyad None; boş girdide ikisi de None (boş alan SmartADM'ye gönderilmez)."""
    parts = (full_name or '').split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return ' '.join(parts[:-1]), parts[-1]


def etk_sms_status(value):
    """'1' → approved, '0' → rejected, diğer → unknown."""
    return {'1': 'approved', '0': 'rejected'}.get(str(value) if value is not None else '', 'unknown')


class SmartAdmClient:
    def __init__(self, customer_code, username, password, url=None, store=None, session_id=None,
                 timeout=TIMEOUT, on_session=None):
        self.customer_code = (customer_code or '').strip()
        self.username = (username or '').strip()
        self.password = password or ''
        self.url = (url or DEFAULT_URL).strip().rstrip('/')
        self.store = (store or '').strip() or DEFAULT_STORE
        self.session_id = session_id
        self.timeout = timeout
        self.on_session = on_session  # yeni oturum alınınca çağrılır (önbelleğe yazmak için)

    # ── düşük seviye ──

    def _http(self, path, payload):
        headers = {'Content-Type': 'application/json', 'RemoteStoreId': self.store}
        try:
            resp = requests.post('%s/%s' % (self.url, path.lstrip('/')), data=json.dumps(payload),
                                 headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise SmartAdmError('SmartADM sunucusuna ulaşılamadı: %s' % e.__class__.__name__, retryable=True) from e
        if resp.status_code == 429:
            raise SmartAdmError('SmartADM istek sınırı aşıldı (429) — bir süre sonra tekrar denenecek', retryable=True)
        if resp.status_code >= 500:
            raise SmartAdmError('SmartADM HTTP %s döndü' % resp.status_code, retryable=True)
        try:
            data = resp.json()
        except ValueError as e:
            raise SmartAdmError('SmartADM cevabı okunamadı (HTTP %s)' % resp.status_code) from e
        return data

    @staticmethod
    def _code(data):
        try:
            return int(data.get('StatusCode', -99)), int(data.get('SubStatusCode', -99))
        except (TypeError, ValueError):
            return -99, -99

    @classmethod
    def error_text(cls, code, value=None):
        text = ERROR_TEXTS.get(code)
        if not text:
            text = 'SmartADM hatası'
            if value and isinstance(value, str):
                # Sunucu metni numara içerebilir: önce maskele, sonra kırp (kırpılan numaranın açık kısmı kalmasın; G-5)
                text += ': %s' % _PHONE_RUN.sub(lambda m: mask_number(m.group()), value)[:120]
        return '%s (%s/%s)' % (text, code[0], code[1])

    def login(self):
        if not (self.customer_code and self.username and self.password):
            raise SmartAdmError('SmartADM müşteri kodu, kullanıcı adı ve şifre ayarlardan girilmelidir.')
        data = self._http('session', {'CustomerCode': self.customer_code, 'Username': self.username,
                                      'Password': self.password})
        code = self._code(data)
        if code != (0, 0) or not data.get('Value'):
            raise SmartAdmError(self.error_text(code, data.get('Value')), code=code)
        self.session_id = str(data['Value'])
        if self.on_session:
            self.on_session(self.session_id)
        return self.session_id

    def call(self, path, payload, allow=()):
        """Oturumlu çağrı; oturum düşmüşse bir kez yenileyip tekrar dener.

        allow: hata sayılmayıp çağırana dönülecek kodlar (ör. NOT_FOUND).
        Dönen: (code, data)
        """
        for attempt in range(2):
            if not self.session_id:
                self.login()
            data = self._http(path, dict(payload, SessionId=self.session_id))
            code = self._code(data)
            if code in SESSION_ERRORS and attempt == 0:
                self.session_id = None
                continue
            if code == (0, 0) or code in allow:
                return code, data
            raise SmartAdmError(self.error_text(code, data.get('Value')), code=code,
                                retryable=code == (-99, -99), invalid_number=code in INVALID_NUMBER_CODES)
        raise SmartAdmError('SmartADM oturumu açılamadı')

    # ── uçlar ──

    def query(self, number):
        """Numaranın SMS ticari ileti izni: {'status': approved|rejected|unknown, 'found': bool}."""
        msisdn = to_msisdn(number)
        if not msisdn:
            raise SmartAdmError('Geçersiz cep telefonu: %s' % mask_number(number), invalid_number=True)
        code, data = self.call('query', {'CommunicationToolType': 'Msisdn', 'Value': msisdn, 'ResponseType': '1'},
                               allow=(NOT_FOUND,))
        if code == NOT_FOUND:
            return {'status': 'unknown', 'found': False}
        value = data.get('Value')
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                value = None
        rows = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
        status = 'unknown'
        for row in rows:
            sms = (((row or {}).get('Authorization') or {}).get('Etk') or {}).get('Msisdn', {}).get('Sms')
            st = etk_sms_status(sms)
            if st == 'rejected':
                return {'status': 'rejected', 'found': True}  # tek bir ret yeterli
            if st == 'approved':
                status = 'approved'
        return {'status': status, 'found': bool(rows)}

    def report2(self, start, finish, page=0, page_size=100):
        """İzin hareketleri (ReportType 2). start/finish datetime; aralık ≤ 7 gün.

        Dönen: (satırlar, max_page). Satır: {'mobile': 5XXXXXXXXX|None (maskeliyse), 'status', 'date', 'source', 'brand'}
        """
        fmt = '%Y%m%d%H%M%S'
        code, data = self.call('report2', {'StartDate': start.strftime(fmt), 'FinishDate': finish.strftime(fmt),
                                           'ReportType': 2, 'Page': page, 'PageSize': page_size})
        value = data.get('Value') or []
        if isinstance(value, str):
            try:
                value = json.loads(value) if value.strip() else []
            except ValueError:
                value = []
        rows = []
        for item in value if isinstance(value, list) else []:
            tools = item.get('CommunicationTools') or {}
            sms = (item.get('AuthorizationDetails') or {}).get('EtkMsisdnSms')
            if not sms:
                continue
            rows.append({
                'raw_msisdn': tools.get('Msisdn'),
                'mobile': from_msisdn(tools.get('Msisdn')),
                'status': etk_sms_status(sms.get('Value')),
                'date': sms.get('AuthorizationDate'),
                'source': (sms.get('AuthorizationSpecificData') or {}).get('IysRecordSource'),
                'brand': sms.get('BrandCode'),
            })
        try:
            max_page = int(data.get('MaxPage') or 0)
        except (TypeError, ValueError):
            max_page = 0
        return rows, max_page

    def create_contact(self, number, name=None, surname=None, remote_ref=None):
        """Kişi kartı oluştur (POST /Contact). Dönen: True oluşturuldu, False "yakın zamanda zaten oluşturulmuş"
        (-6/-613: kart var, hata değil). Ad/soyad/RemoteReferenceId opsiyonel; boş olanlar gönderilmez.

        Yanıt Value alanı belgesiz: kullanılmaz, yalnız durum kodu yorumlanır (0/0 oluştu, -613 var).
        """
        msisdn = to_msisdn(number)
        if not msisdn:
            raise SmartAdmError('Geçersiz cep telefonu: %s' % mask_number(number), invalid_number=True)
        details = {key: value for key, value in (('Name', name), ('Surname', surname),
                                                 ('RemoteReferenceId', remote_ref)) if value}
        payload = {'CommunicationTools': {'Msisdn': msisdn}}
        if details:
            payload['ContactDetails'] = details
        code, _data = self.call('Contact', payload, allow=(CONTACT_EXISTS,))
        return code != CONTACT_EXISTS

    def ensure_contact(self, number, full_name=None, remote_ref=None):
        """Kişi İYS/SmartADM'de yoksa kartını oluştur (önce Query, yoksa Contact). Dönen: Contact çağrıldı mı.

        Kaydı olmayan kişide trigger/contactapiload -6/-601 verdiği için bu, onlardan önce çağrılır.
        -613 (kart az önce oluşturulmuş) başarı sayılır, akış sürer.
        """
        if self.query(number)['found']:
            return False
        name, surname = split_name(full_name)
        self.create_contact(number, name, surname, remote_ref)
        return True

    def contact_api_load(self, number, approved, when, source, kvkk=True):
        """Mağazada / formla alınan SMS iznini İYS'ye yükle. when: datetime (≤ 3 iş günü önce).

        Dönen: True yüklendi, False izin zaten İYS'de kayıtlı (-6/-607, bilgi; hata değil)."""
        msisdn = to_msisdn(number)
        if not msisdn:
            raise SmartAdmError('Geçersiz cep telefonu: %s' % mask_number(number), invalid_number=True)
        date = when.strftime('%Y%m%d%H%M%S')
        details = {'EtkMsisdnSms': {'Value': '1' if approved else '0', 'AuthorizationDate': date,
                                    'AuthorizationSpecificData': {'IysRecordSource': source}}}
        if kvkk and approved:
            details['KvkkStore'] = {'Value': '1', 'AuthorizationDate': date}
        code, _data = self.call('contactapiload', {'CommunicationTools': {'Msisdn': msisdn},
                                                    'AuthorizationDetails': details}, allow=(ALREADY_CONSENTED,))
        return code != ALREADY_CONSENTED

    def trigger(self, number):
        """Müşteriye onay kodu SMS'i gönder; TriggerId döndürür. İzin zaten İYS'de kayıtlıysa (-6/-607, bilgi)
        None döner: kod gönderilmez, onay adımı gerekmez."""
        msisdn = to_msisdn(number)
        if not msisdn:
            raise SmartAdmError('Geçersiz cep telefonu: %s' % mask_number(number), invalid_number=True)
        code, data = self.call('trigger', {'CommunicationToolType': 'Msisdn', 'Value': msisdn,
                                           'CommunicationType': 'Sms'}, allow=(ALREADY_CONSENTED,))
        if code == ALREADY_CONSENTED:
            return None
        return str(data.get('Value') or '')

    def approve(self, trigger_id, activation_key):
        self.call('approve', {'TriggerId': trigger_id, 'ActivationKey': (activation_key or '').strip()})
        return True
