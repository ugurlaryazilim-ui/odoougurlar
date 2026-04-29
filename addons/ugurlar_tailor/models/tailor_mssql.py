import logging

from odoo import models, api

_logger = logging.getLogger(__name__)

try:
    import pymssql
except ImportError:
    pymssql = None
    _logger.warning("pymssql not installed — Terzi MSSQL connector will not work. Install with: pip install pymssql")


class UgurlarTailorMSSQLConnector(models.AbstractModel):
    """Nebim MSSQL veritabanına bağlanıp fatura verisi çeken connector."""
    _name = 'ugurlar.tailor.mssql.connector'
    _description = 'Terzi MSSQL Connector'

    def _get_config(self):
        """ir.config_parameter'dan MSSQL bağlantı ayarlarını oku."""
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'server': ICP.get_param('ugurlar_tailor.mssql_server', ''),
            'port': int(ICP.get_param('ugurlar_tailor.mssql_port', '1433') or '1433'),
            'database': ICP.get_param('ugurlar_tailor.mssql_database', ''),
            'user': ICP.get_param('ugurlar_tailor.mssql_user', ''),
            'password': ICP.get_param('ugurlar_tailor.mssql_password', ''),
            'view_name': ICP.get_param('ugurlar_tailor.mssql_view_name', 'vw_TerziFaturalar'),
        }

    def _get_connection(self):
        """MSSQL bağlantısı aç."""
        if not pymssql:
            raise Exception("pymssql kutuphanesi yuklu degil! pip install pymssql")

        cfg = self._get_config()
        if not cfg['server'] or not cfg['database']:
            raise Exception("MSSQL baglanti ayarlari eksik! Ayarlar > Terzi Takip'ten yapilandir.")

        return pymssql.connect(
            server=cfg['server'],
            port=cfg['port'],
            user=cfg['user'],
            password=cfg['password'],
            database=cfg['database'],
            charset='utf8',
            as_dict=True,
        )

    def _execute_query(self, query, params=None):
        """SQL sorgusu calistir ve sonuclari don."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            rows = cursor.fetchall()
            return rows
        except Exception as e:
            _logger.error("MSSQL Query Error: %s", e)
            raise
        finally:
            if conn:
                conn.close()

    @api.model
    def test_connection(self):
        """Bağlantı testi."""
        try:
            conn = self._get_connection()
            conn.close()
            return {'success': True, 'message': 'Baglanti basarili!'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @api.model
    def search_invoices(self, search_term=''):
        """Fatura no ile arama — Nebim view'dan."""
        if not search_term or len(search_term) < 3:
            return []

        cfg = self._get_config()
        view_name = cfg['view_name']

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

        rows = self._execute_query(query, (f'%{search_term}%',))

        # datetime -> string cevir
        result = []
        for row in rows:
            item = dict(row)
            if item.get('invoice_date'):
                item['invoice_date'] = str(item['invoice_date'])
            result.append(item)
        return result

    @api.model
    def get_invoice_detail(self, invoice_no=''):
        """Fatura detayı — header + satırlar."""
        if not invoice_no:
            return None

        cfg = self._get_config()
        view_name = cfg['view_name']

        # Header
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

        header = dict(headers[0])
        if header.get('invoice_date'):
            header['invoice_date'] = str(header['invoice_date'])

        # Items
        items_query = f"""
            SELECT
                Barkod as barcode,
                UrunKodu as product_code,
                Adet as quantity
            FROM {view_name}
            WHERE UGRFaturaNo = %s
        """
        items = self._execute_query(items_query, (invoice_no,))
        header['items'] = [dict(item) for item in items]

        return header

    @api.model
    def verify_product(self, invoice_no='', barcode=''):
        """Faturadaki ürünü barkod ile doğrula."""
        if not invoice_no or not barcode:
            return None

        cfg = self._get_config()
        view_name = cfg['view_name']

        query = f"""
            SELECT
                Barkod as barcode,
                UrunKodu as product_code,
                Adet as quantity
            FROM {view_name}
            WHERE UGRFaturaNo = %s AND Barkod = %s
        """
        rows = self._execute_query(query, (invoice_no, barcode))
        return dict(rows[0]) if rows else None
