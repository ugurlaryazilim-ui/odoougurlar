import logging
import re

from odoo import models, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Lazy import — pymssql olmasa bile modül yüklenebilsin
pymssql = None


def _ensure_pymssql():
    """pymssql modülünü lazy olarak import eder."""
    global pymssql
    if pymssql is None:
        try:
            import pymssql as _pymssql
            pymssql = _pymssql
        except ImportError:
            raise UserError(
                'pymssql kütüphanesi yüklü değil!\n'
                'Lütfen: pip install pymssql komutunu çalıştırın.'
            )
    return pymssql


class TailorMssqlConnector(models.AbstractModel):
    """Nebim MSSQL bağlantı servisi — terzi fatura view'ını sorgular."""
    _name = 'ugurlar.tailor.mssql.connector'
    _description = 'Terzi MSSQL Bağlantı Servisi'

    @api.private
    def _get_mssql_config(self):
        """ir.config_parameter'dan MSSQL ayarlarını okur."""
        ICP = self.env['ir.config_parameter'].sudo()
        config = {
            'server': ICP.get_param('ugurlar_tailor.mssql_server', ''),
            'port': int(ICP.get_param('ugurlar_tailor.mssql_port', '1433') or 1433),
            'database': ICP.get_param('ugurlar_tailor.mssql_database', ''),
            'user': ICP.get_param('ugurlar_tailor.mssql_user', ''),
            'password': ICP.get_param('ugurlar_tailor.mssql_password', ''),
            'view_name': ICP.get_param('ugurlar_tailor.mssql_view_name', 'vw_TerziFaturalar'),
        }
        # View adı SQL'e doğrudan yazılır (parametre olamaz): yalnız tanımlayıcı karakterlerine izin ver
        if not re.fullmatch(r'[\w.\[\]]+', config['view_name'] or ''):
            raise UserError('Terzi MSSQL view adı geçersiz! Yalnız harf, rakam, alt çizgi, nokta ve köşeli parantez kullanılabilir.')
        if not config['server'] or not config['database']:
            raise UserError(
                'Terzi MSSQL bağlantı ayarları yapılandırılmamış!\n'
                'Ayarlar > Terzi Takip bölümünden SQL bağlantı bilgilerini girin.'
            )
        return config

    @api.private
    def _get_connection(self):
        """MSSQL bağlantısı oluşturur."""
        _ensure_pymssql()
        config = self._get_mssql_config()
        try:
            conn = pymssql.connect(
                server=config['server'],
                port=config['port'],
                user=config['user'],
                password=config['password'],
                database=config['database'],
                charset='utf8',
                login_timeout=10,
                timeout=30,
            )
            return conn
        except Exception as e:
            _logger.error('MSSQL bağlantı hatası: %s', e)
            raise UserError('Nebim veritabanına bağlanılamadı. Lütfen daha sonra tekrar deneyin veya sistem yöneticisine bildirin.')

    @api.private
    def _execute_query(self, query, params=None, conn=None):
        """SQL sorgusu çalıştırır ve sonuçları dict listesi olarak döner.

        conn verilirse o bağlantı kullanılır (kapatmak çağıranın işi).
        """
        own = conn is None
        if own:
            conn = self._get_connection()
        try:
            cursor = conn.cursor(as_dict=True)
            cursor.execute(query, params or ())
            return cursor.fetchall()
        except Exception as e:
            _logger.error('MSSQL sorgu hatası: %s', e)
            raise UserError('Nebim sorgusu başarısız oldu. Lütfen daha sonra tekrar deneyin veya sistem yöneticisine bildirin.')
        finally:
            if own:
                conn.close()

    _HEADER_COLUMNS = """
                UGRFaturaNo as invoice_no,
                FaturaTarihi as invoice_date,
                MusteriKodu as customer_code,
                MusteriAdi as customer_name,
                SatisPersoneli as sales_person"""

    def search_invoices(self, search_term):
        """Fatura arama — Nebim view'ından UGRFaturaNo ile arar.

        Barkod okutulunca tam numara gelir: önce tam eşleşme (indeks kullanılır), sonra
        "ile başlayan", en son "içeren" denenir; '%term%' tam tarama yalnız gerekirse çalışır.
        """
        search_term = (search_term or '').strip()
        if len(search_term) < 3:
            raise UserError('En az 3 karakter giriniz.')

        view_name = self._get_mssql_config()['view_name']
        conn = self._get_connection()
        try:
            results = []
            for op, value in (('=', search_term), ('LIKE', f'{search_term}%'), ('LIKE', f'%{search_term}%')):
                query = f"""
                    SELECT DISTINCT TOP 20 {self._HEADER_COLUMNS}
                    FROM {view_name}
                    WHERE UGRFaturaNo {op} %s
                    ORDER BY FaturaTarihi DESC
                """
                results = self._execute_query(query, (value,), conn=conn)
                if results:
                    break
        finally:
            conn.close()

        # Datetime nesnelerini string'e çevir
        for row in results:
            if row.get('invoice_date'):
                row['invoice_date'] = str(row['invoice_date'])
        return results

    # View'da müşteri cep telefonu sütunu (Nebim prCurrAccCommunication'dan); yoksa sorgu onsuz çalışır
    _MOBILE_COLUMN = 'MusteriCep'
    _column_cache = {}

    @api.private
    def _view_has_column(self, conn, view_name, column):
        # Yalnız 'var' sonucu saklanır: view sonradan güncellenince yeniden başlatmadan algılansın
        key = (self.env.cr.dbname, view_name, column)
        if not self._column_cache.get(key):
            rows = self._execute_query(
                "SELECT 1 AS ok FROM sys.columns WHERE object_id = OBJECT_ID(%s) AND name = %s",
                (view_name, column), conn=conn)
            self._column_cache[key] = bool(rows)
        return self._column_cache[key]

    def get_invoice_detail(self, invoice_no):
        """Belirli bir faturanın başlık + ürün detaylarını tek sorguda getirir."""
        view_name = self._get_mssql_config()['view_name']
        conn = self._get_connection()
        try:
            has_mobile = self._view_has_column(conn, view_name, self._MOBILE_COLUMN)
            mobile_col = f', {self._MOBILE_COLUMN} as customer_mobile' if has_mobile else ''
            query = f"""
                SELECT {self._HEADER_COLUMNS}{mobile_col},
                    Barkod as barcode,
                    UrunKodu as product_code,
                    Adet as quantity
                FROM {view_name}
                WHERE UGRFaturaNo = %s
            """
            rows = self._execute_query(query, (invoice_no,), conn=conn)
        finally:
            conn.close()
        if not rows:
            return None

        first = rows[0]
        header = {k: first.get(k) for k in ('invoice_no', 'invoice_date', 'customer_code',
                                              'customer_name', 'sales_person')}
        header['customer_mobile'] = (first.get('customer_mobile') or '').strip()
        if header.get('invoice_date'):
            header['invoice_date'] = str(header['invoice_date'])
        header['items'] = [{'barcode': r['barcode'], 'product_code': r['product_code'],
                            'quantity': r['quantity']} for r in rows]
        return header

    def verify_product(self, invoice_no, barcode):
        """Barkod ile ürün doğrulama — faturada bu barkod var mı?"""
        view_name = self._get_mssql_config()['view_name']
        query = f"""
            SELECT
                Barkod as barcode,
                UrunKodu as product_code,
                Adet as quantity
            FROM {view_name}
            WHERE UGRFaturaNo = %s AND Barkod = %s
        """
        results = self._execute_query(query, (invoice_no, barcode))
        return results[0] if results else None

    def test_connection(self):
        """MSSQL bağlantı testi."""
        try:
            conn = self._get_connection()
            conn.close()
            return {'success': True, 'message': 'Bağlantı başarılı!'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
