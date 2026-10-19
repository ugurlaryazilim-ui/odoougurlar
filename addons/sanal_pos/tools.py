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


def scrub(text, secrets):
    """Metindeki sır değerlerini her geçtiği yerde ``'***'`` yapar. Boş sırlar yok sayılır."""
    if not text:
        return text
    out = str(text)
    values = sorted({str(s) for s in (secrets or []) if s}, key=len, reverse=True)
    for value in values:
        out = out.replace(value, MASK)
    return out
