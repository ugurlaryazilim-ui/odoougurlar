import logging

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
            'port': int(ICP.get_param('ugurlar_tailor.mssql_port', '1433')),
            'database': ICP.get_param('ugurlar_tailor.mssql_database', ''),
            'user': ICP.get_param('ugurlar_tailor.mssql_user', ''),
            'password': ICP.get_param('ugurlar_tailor.mssql_password', ''),
            'view_name': ICP.get_param('ugurlar_tailor.mssql_view_name', 'vw_TerziFaturalar'),
        }
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
            _logger.error('MSSQL bağlantı hatası: %s', str(e))
            raise UserError(f'MSSQL bağlantı hatası: {str(e)}')

    @api.private
    def _execute_query(self, query, params=None):
        """SQL sorgusu çalıştırır ve sonuçları dict listesi olarak döner."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor(as_dict=True)
            cursor.execute(query, params or ())
            results = cursor.fetchall()
            return results
        except Exception as e:
            _logger.error('MSSQL sorgu hatası: %s', str(e))
            raise UserError(f'SQL sorgu hatası: {str(e)}')
        finally:
            conn.close()

    def search_invoices(self, search_term):
        """Fatura arama — Nebim view'ından UGRFaturaNo ile arar."""
        if not search_term or len(search_term) < 3:
            raise UserError('En az 3 karakter giriniz.')

        config = self._get_mssql_config()
        view_name = config['view_name']

        query = f"""
            SELECT DISTINCT TOP 20
                UGRFaturaNo as invoice_no,
                FaturaTarihi as invoice_date,
                MusteriKodu as customer_code,
                MusteriAdi as customer_name,
                SatisPersoneli as sales_person
            FROM {view_name}
            WHERE UGRFaturaNo LIKE %s
            ORDER BY FaturaTarihi DESC
        """
        results = self._execute_query(query, (f'%{search_term}%',))

        # Datetime nesnelerini string'e çevir
        for row in results:
            if row.get('invoice_date'):
                row['invoice_date'] = str(row['invoice_date'])
        return results

    def get_invoice_detail(self, invoice_no):
        """Belirli bir faturanın başlık + ürün detaylarını getirir."""
        config = self._get_mssql_config()
        view_name = config['view_name']

        # Başlık bilgisi
        header_query = f"""
            SELECT DISTINCT TOP 1
                UGRFaturaNo as invoice_no,
                FaturaTarihi as invoice_date,
                MusteriKodu as customer_code,
                MusteriAdi as customer_name,
                SatisPersoneli as sales_person
            FROM {view_name}
            WHERE UGRFaturaNo = %s
        """
        headers = self._execute_query(header_query, (invoice_no,))
        if not headers:
            return None

        header = headers[0]
        if header.get('invoice_date'):
            header['invoice_date'] = str(header['invoice_date'])

        # Ürün detayları
        detail_query = f"""
            SELECT
                Barkod as barcode,
                UrunKodu as product_code,
                Adet as quantity
            FROM {view_name}
            WHERE UGRFaturaNo = %s
        """
        items = self._execute_query(detail_query, (invoice_no,))

        header['items'] = items
        return header

    def verify_product(self, invoice_no, barcode):
        """Barkod ile ürün doğrulama — faturada bu barkod var mı?"""
        config = self._get_mssql_config()
        view_name = config['view_name']

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
