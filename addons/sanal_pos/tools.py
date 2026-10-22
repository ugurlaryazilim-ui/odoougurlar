# -*- coding: utf-8 -*-
"""Sanal POS saf yardımcıları (tasarım §9). Odoo'ya bağımlı değildir.

Telefon, metin, ASCII, e-posta, TL biçimi ve maskeleme. Sır maskeleme
(KK-37 / NFR-4): loglara ve kullanıcı mesajlarına sır değeri yazılmaz.
"""
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MASK = '***'

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_EMAIL_MAX = 64
_WS_RE = re.compile(r'\s+')

# `odoougurlar` _normalize_turkish ile aynı tablo (kopya; modül bağımlılığı yok)
_ASCII_TABLE = str.maketrans({
    'İ': 'I', 'ı': 'i', 'Ğ': 'G', 'ğ': 'g', 'Ü': 'U', 'ü': 'u',
    'Ş': 'S', 'ş': 's', 'Ö': 'O', 'ö': 'o', 'Ç': 'C', 'ç': 'c',
})

PHONE_FORMATS = ('10', '0', '90', '+90')


# ---------------------------------------------------------------- telefon
def normalize_phone(raw):
    """Cep telefonunu ``5XXXXXXXXX`` (10 hane) yapar; geçersizse ``False``."""
    if not raw or not isinstance(raw, str):
        return False
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 12 and digits.startswith('90'):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]
    if len(digits) == 10 and digits.startswith('5'):
        return digits
    return False


def format_phone_for_provider(phone10, fmt='10'):
    """10 haneli telefonu sağlayıcının istediği biçime çevirir."""
    if fmt == '0':
        return '0' + phone10
    if fmt == '90':
        return '90' + phone10
    if fmt == '+90':
        return '+90' + phone10
    return phone10


# ---------------------------------------------------------------- metin
def clean_text(s):
    """Baş/son boşluğu siler, ardışık boşlukları teke indirir; Türkçe karakter korunur."""
    if not s:
        return ''
    return _WS_RE.sub(' ', str(s)).strip()


def to_ascii(s):
    """Türkçe karakterleri ASCII karşılığına çevirir (KK-15)."""
    if not s:
        return ''
    return str(s).translate(_ASCII_TABLE)


def validate_email(s):
    """Basit biçim denetimi, en çok 64 karakter (KK-8)."""
    if not s or not isinstance(s, str):
        return False
    return len(s) <= _EMAIL_MAX and bool(_EMAIL_RE.match(s))


# ---------------------------------------------------------------- tutar
def format_try(amount):
    """``Decimal('9000')`` -> ``'9.000,00 TL'`` (kullanıcı dilinden bağımsız)."""
    try:
        value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    except (InvalidOperation, ValueError):
        value = Decimal('0')
    value = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    sign = '-' if value < 0 else ''
    text = '{:,.2f}'.format(abs(value))  # 1,234,567.80
    text = text.replace(',', '_').replace('.', ',').replace('_', '.')
    return '%s%s TL' % (sign, text)


# ---------------------------------------------------------------- maskeleme
def mask_phone(raw):
    """Yalnız son 4 hane görünür: ``******2233``. Boş girdi -> ``''``."""
    if not raw:
        return ''
    text = str(raw)
    if len(text) <= 4:
        return '*' * len(text)
    return '*' * (len(text) - 4) + text[-4:]


def mask_email(raw):
    """Yerel kısım gizlenir, alan adı kalır: ``***@alan.com``."""
    if not raw:
        return ''
    text = str(raw)
    if '@' not in text:
        return MASK
    return MASK + text[text.rindex('@'):]


def mask_params(params, secret_keys):
    """Sözlüğün kopyasını döndürür; ``secret_keys`` değerleri ``'***'`` olur (büyük/küçük harf duyarsız)."""
    secrets = {str(k).lower() for k in (secret_keys or []) if k}
    return {k: (MASK if str(k).lower() in secrets else v) for k, v in (params or {}).items()}


# NEDEN: Mail Order'da kart verisi Odoo'ya hiç girmemelidir (bkz. KARARLAR K-13); bu, mimari
# savunmanın yanındaki son katmandır: bir yanıt/istisna metnine yanlışlıkla PAN sızsa bile
# günlüğe yazılmaz. Luhn doğrulaması rastgele uzun sayıları (ödeme numarası, işlem no) korur.
# pgTranRefId Paratika'nın işlem referansıdır (16 hane olabilir, Luhn tesadüfen tutabilir) ve
# merchantPaymentId bizim ödeme numaramızdır (harfe bitişik hane içerir): anahtarlıyken muaf.
# G-5: sınır yalnız rakamdır ('x4355…', 'card_4355…', '4355…TL' de aday); ayraç boşluk, tire,
# nokta, artı, NBSP ve URL kodlu karşılıkları (%20 %2B %2D %2E %C2%A0), arka arkaya en çok iki.
# DIKKAT: ayraç kümesi gevşetilirse tutar/tarih metinleri bozulur; daraltılırsa ayraçlı PAN kaçar.
# tests/test_mail_order.py::TestCardMasking.
_CARD_SEP = r'(?:[ \-.+ ]|%(?:20|2[BbDdEe]|[Cc]2%[Aa]0))'
_CARD_CANDIDATE_RE = re.compile(
    r'(?i:pgTranRefId|merchantPaymentId)["\']?\s*[:=]\s*["\']?[\w-]+'
    r'|(?<![0-9])[0-9](?:' + _CARD_SEP + r'{0,2}[0-9])+')
# URL kodlu ayraçtaki rakamlar ('%20' içindeki 2 ve 0) hane grubu sayılmaz
_DIGIT_GROUP_RE = re.compile(r'(?<!%)(?<!%[0-9A-Fa-f])[0-9]+')
PAN_MIN, PAN_MAX = 13, 19


def _luhn_ok(digits):
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _mask_candidate(match):
    text = match.group(0)
    if not text[0].isdigit():
        return text                     # pgTranRefId / merchantPaymentId muafiyeti
    groups = [(m.start(), m.end()) for m in _DIGIT_GROUP_RE.finditer(text)]
    out, last, i = [], 0, 0
    while i < len(groups):
        # En uzun, soldan başlayan grup penceresi: "9000.00 4355 0843 5508 4358" gibi
        # bitişik sayılar PAN'ı gizlemesin (aday bütününde Luhn tutmayabilir).
        # Gerçek PAN '0' ile başlamaz: baştaki sıfırlar (ör. "00" kuruş) Luhn'u bozmaz ama
        # PAN'ın parçası da değildir.
        # NEDEN: aday uzunluğu sınırsız (uzun ayraçlı sayı dizileri); pencere PAN_MAX haneyle
        # sınırlı olduğundan iş grup sayısıyla doğrusal kalır.
        ends, total = [], 0
        for j in range(i, len(groups)) if text[groups[i][0]] != '0' else ():
            total += groups[j][1] - groups[j][0]
            if total > PAN_MAX:
                break
            if total >= PAN_MIN:
                ends.append(j + 1)
        for j in reversed(ends):
            digits = ''.join(text[a:b] for a, b in groups[i:j])
            if _luhn_ok(digits):
                out.append(text[last:groups[i][0]] + '****' + digits[-4:])
                last = groups[j - 1][1]
                i = j
                break
        else:
            i += 1
    return ''.join(out) + text[last:]


def mask_card_data(text):
    """Luhn-geçerli 13-19 haneli rakam dizilerini (ayraçlı ve URL kodlu dahil) ``****<son4>``
    yapar (ayraç kümesi ``_CARD_SEP``). Başka hiçbir şeye dokunmaz; tekrar uygulamak sonucu
    değiştirmez."""
    if not text or not isinstance(text, str):
        return text
    return _CARD_CANDIDATE_RE.sub(_mask_candidate, text)


def scrub(text, secrets):
    """Metindeki sır değerlerini her geçtiği yerde ``'***'`` yapar. Boş sırlar yok sayılır."""
    if not text:
        return text
    out = str(text)
    values = sorted({str(s) for s in (secrets or []) if s}, key=len, reverse=True)
    for value in values:
        out = out.replace(value, MASK)
    return out
