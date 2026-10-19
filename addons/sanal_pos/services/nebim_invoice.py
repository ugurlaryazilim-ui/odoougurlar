# -*- coding: utf-8 -*-
"""Nebim fatura kaynağı (tasarım §10).

``dbo.vw_TerziFaturalar`` v2 görünümünden TEK bir faturayı okur. Görünüm satır
bazlıdır (her fatura satırı bir satır); ``FaturaToplam`` her satırda aynıdır ve
tutar yalnız ondan alınır (satır tutarları toplanmaz). Satırlar arasında
tutar/para birimi farkı varsa fatura reddedilir.

Ekip testlerde MSSQL'e bağlanmaz: tek dar nokta ``_fetch_rows`` taklit edilir.
"""
import logging
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from odoo import api, models
from odoo.exceptions import UserError

from ..tools import clean_text, normalize_phone, scrub

_logger = logging.getLogger(__name__)

# pymssql lazy import: yüklü olmasa bile modül yüklenebilsin (terzi kalıbı)
pymssql = None

_VIEW_NAME_RE = re.compile(r'[\w.\[\]]+')
_DEFAULT_VIEW = 'dbo.vw_TerziFaturalar'
MIN_INVOICE_NO_LEN = 3

# SELECT edilen v2 sütunları (SELECT * yok; SatirTutari kasten okunmaz)
COLUMNS = (
    'InvoiceHeaderID', 'UGRFaturaNo', 'FaturaTarihi', 'MusteriKodu', 'MusteriAdi',
    'MusteriCep', 'FaturaGSMNo', 'MusteriEposta', 'FaturaAdresi', 'FaturaIlKodu',
    'FaturaIlceKodu', 'ParaBirimi', 'FaturaToplam',
)

MSG_UNREACHABLE = 'Fatura sistemine ulaşılamadı, daha sonra tekrar deneyin.'
MSG_NOT_V2 = ('Fatura görünümü Sanal POS için güncel değil (v2 gerekli). '
              'Sistem yöneticisine bildirin.')


def _ensure_pymssql():
    """pymssql modülünü lazy olarak import eder."""
    global pymssql
    if pymssql is None:
        try:
            import pymssql as _pymssql
        except ImportError:
            raise UserError('pymssql kütüphanesi yüklü değil. Sistem yöneticisine bildirin.')
        pymssql = _pymssql
    return pymssql


def _to_decimal(value):
    """MSSQL tutarını Decimal'e çevirir; çevrilemezse ``None``."""
    if value is None or value is False:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class NebimInvoiceSource(models.AbstractModel):
    _name = 'sanal.pos.invoice.source.nebim'
    _description = 'Sanal POS Fatura Kaynağı: Nebim (MSSQL)'

    # ------------------------------------------------------------------ ayarlar
    @api.model
    def _get_mssql_config(self):
        """``sanal_pos.mssql_*`` ayarlarını okur. Yapılandırma eksikse UserError."""
        ICP = self.env['ir.config_parameter'].sudo()
        view_name = (ICP.get_param('sanal_pos.mssql_view_name') or '').strip() or _DEFAULT_VIEW
        # View adı SQL'e doğrudan yazılır (parametre olamaz): yalnız tanımlayıcı karakterleri
        if not _VIEW_NAME_RE.fullmatch(view_name):
            raise UserError('Fatura görünümü adı geçersiz. Sistem yöneticisine bildirin.')
        server = (ICP.get_param('sanal_pos.mssql_server') or '').strip()
        database = (ICP.get_param('sanal_pos.mssql_database') or '').strip()
        if not server or not database:
            raise UserError('Fatura sistemi bağlantı ayarları yapılmamış. Sistem yöneticisine bildirin.')
        try:
            port = int(ICP.get_param('sanal_pos.mssql_port') or 1433)
        except ValueError:
            port = 1433
        return {
            'server': server,
            'port': port,
            'database': database,
            'user': ICP.get_param('sanal_pos.mssql_user') or '',
            'password': ICP.get_param('sanal_pos.mssql_password') or '',
            'view_name': view_name,
        }

    @api.model
    def _secrets(self):
        """Loglardan ve mesajlardan süzülecek sır değerleri."""
        ICP = self.env['ir.config_parameter'].sudo()
        return [ICP.get_param('sanal_pos.mssql_password'), ICP.get_param('sanal_pos.mssql_user')]

    # ------------------------------------------------------------------ MSSQL (tek dar nokta)
    @api.model
    def _fetch_rows(self, invoice_no):
        """Faturanın görünüm satırlarını ``dict`` listesi olarak döndürür.

        Parametreli tam eşleşme sorgusu; ``invoice_no`` SQL metnine girmez.
        Testlerde taklit edilen yöntem budur.
        """
        _ensure_pymssql()
        config = self._get_mssql_config()
        # nosec: view_name _get_mssql_config'te regex ile doğrulandı, sütunlar sabittir.
        query = 'SELECT %s FROM %s WHERE UGRFaturaNo = %%s' % (
            ', '.join(COLUMNS), config['view_name'])
        conn = pymssql.connect(
            server=config['server'], port=config['port'], user=config['user'],
            password=config['password'], database=config['database'],
            charset='utf8', login_timeout=10, timeout=15)
        try:
            cursor = conn.cursor(as_dict=True)
            cursor.execute(query, (invoice_no,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ------------------------------------------------------------------ iş kuralları
    @api.model
    def find_invoice(self, invoice_no):
        """Faturayı okur, kurallardan geçirir ve normalize sözlük döndürür.

        Anahtarlar: invoice_no, invoice_ref, invoice_date, customer_code, name,
        phone, email, address, city, amount (Decimal), currency.
        """
        invoice_no = invoice_no.strip() if isinstance(invoice_no, str) else ''
        if len(invoice_no) < MIN_INVOICE_NO_LEN:
            raise UserError('En az 3 karakter giriniz.')

        try:
            rows = self._fetch_rows(invoice_no)
        except UserError:
            raise
        except Exception as exc:
            text = scrub(str(exc), self._secrets())
            # Sır süzülmüş metin loga; kullanıcıya yalnız sabit Türkçe mesaj gider
            _logger.warning('Nebim fatura sorgusu başarısız (%s): %s', type(exc).__name__, text)
            if 'invalid column name' in text.lower():
                raise UserError(MSG_NOT_V2)
            raise UserError(MSG_UNREACHABLE)

        if not rows:
            raise UserError('Fatura bulunamadı: %s' % invoice_no)

        amount, currency = self._check_amount(rows)
        return {
            'invoice_no': clean_text(self._first(rows, 'UGRFaturaNo')) or invoice_no,
            'invoice_ref': clean_text(self._first(rows, 'InvoiceHeaderID')),
            'invoice_date': self._first(rows, 'FaturaTarihi') or False,
            'customer_code': clean_text(self._first(rows, 'MusteriKodu')),
            'name': clean_text(self._first(rows, 'MusteriAdi')),
            'phone': self._pick_phone(rows),
            'email': (self._first(rows, 'MusteriEposta') or '').strip(),
            'address': clean_text(self._first(rows, 'FaturaAdresi')),
            'city': self._city_name(self._first(rows, 'FaturaIlKodu')),
            'amount': amount,
            'currency': currency,
        }

    @staticmethod
    def _first(rows, key):
        """Satırlardaki ilk dolu değer (görünüm satır bazlıdır; başlık alanları tekrarlar)."""
        for row in rows:
            value = row.get(key)
            if value not in (None, False, ''):
                return value
        return None

    @staticmethod
    def _check_amount(rows):
        """Satırlar arası tutarlılık (KK-1b), tutar (KK-4) ve para birimi (KK-4) denetimi."""
        totals = {_to_decimal(row.get('FaturaToplam')) for row in rows}
        currencies = {(row.get('ParaBirimi') or '').strip().upper() for row in rows}
        if len(totals) > 1 or len(currencies) > 1:
            raise UserError('Fatura tutarı tutarsız; link oluşturulamaz.')
        total = totals.pop()
        currency = currencies.pop()
        if total is not None:
            total = total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if total is None or total <= 0:
            shown = 'boş' if total is None else str(total)
            raise UserError('Faturanın tutarı geçersiz (%s); link oluşturulamaz.' % shown)
        if currency != 'TRY':
            raise UserError(
                'Yalnız TL faturalar için link oluşturulabilir (%s).' % (currency or 'boş'))
        return total, currency

    @staticmethod
    def _pick_phone(rows):
        """FaturaGSMNo geçerli cep ise o; değilse MusteriCep; ikisi de değilse boş (KK-1a)."""
        for key in ('FaturaGSMNo', 'MusteriCep'):
            for row in rows:
                phone = normalize_phone(row.get(key))
                if phone:
                    return phone
        return ''

    @api.model
    def _city_name(self, city_code):
        """İl kodunu `odoougurlar` eşlemesiyle ada çevirir (yumuşak bağ); yoksa boş (KK-1a).

        Ham kod asla il adı olarak döndürülmez; Paratika'ya kod gitmez.
        """
        code = (city_code or '').strip() if isinstance(city_code, str) else ''
        if not code or 'odoougurlar.nebim.district' not in self.env:
            return ''
        district = self.env['odoougurlar.nebim.district'].sudo().search(
            [('city_code', '=', code), ('city_name', '!=', False)], limit=1)
        return clean_text(district.city_name) if district else ''
