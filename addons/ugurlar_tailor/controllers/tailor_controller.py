import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class TailorController(http.Controller):
    """Terzi OWL frontend için JSON API endpoint'leri."""

    # ── Fatura Arama (Nebim MSSQL) ──
    @http.route('/ugurlar_tailor/search_invoice', type='json', auth='user')
    def search_invoice(self, search_term=''):
        connector = request.env['ugurlar.tailor.mssql.connector']
        return connector.search_invoices(search_term)

    @http.route('/ugurlar_tailor/invoice_detail', type='json', auth='user')
    def invoice_detail(self, invoice_no=''):
        connector = request.env['ugurlar.tailor.mssql.connector']
        return connector.get_invoice_detail(invoice_no)

    @http.route('/ugurlar_tailor/verify_product', type='json', auth='user')
    def verify_product(self, invoice_no='', barcode=''):
        connector = request.env['ugurlar.tailor.mssql.connector']
        return connector.verify_product(invoice_no, barcode)

    @http.route('/ugurlar_tailor/test_connection', type='json', auth='user')
    def test_connection(self):
        connector = request.env['ugurlar.tailor.mssql.connector']
        return connector.test_connection()

    # ── Hizmetler ──
    @http.route('/ugurlar_tailor/services', type='json', auth='user')
    def get_services(self):
        services = request.env['ugurlar.tailor.service'].search_read(
            [('active', '=', True)],
            ['id', 'name', 'price', 'sequence'],
            order='sequence, name',
        )
        return services

    # ── Terziler ──
    @http.route('/ugurlar_tailor/tailors', type='json', auth='user')
    def get_tailors(self):
        tailors = request.env['ugurlar.tailor'].search_read(
            [('active', '=', True)],
            ['id', 'name', 'phone'],
            order='name',
        )
        # Her terzi için özel fiyatları da ekle
        for tailor in tailors:
            prices = request.env['ugurlar.tailor.price'].search_read(
                [('tailor_id', '=', tailor['id'])],
                ['service_id', 'price'],
            )
            tailor['prices'] = [
                {'service_id': p['service_id'][0], 'price': p['price']}
                for p in prices
            ]
        return tailors

    # ── Sipariş Oluştur ──
    @http.route('/ugurlar_tailor/create_order', type='json', auth='user')
    def create_order(self, orders=None):
        """Toplu sipariş oluşturma — her ürün için ayrı sipariş."""
        if not orders:
            return {'success': False, 'error': 'Sipariş verisi boş!'}

        created = []
        Order = request.env['ugurlar.tailor.order']
        OrderLine = request.env['ugurlar.tailor.order.line']

        for order_data in orders:
            # Sipariş oluştur
            order = Order.create({
                'invoice_no': order_data.get('invoice_no', ''),
                'product_barcode': order_data.get('barcode', ''),
                'product_code': order_data.get('product_code', ''),
                'product_name': order_data.get('product_name', ''),
                'customer_name': order_data.get('customer_name', ''),
                'customer_phone': order_data.get('customer_phone', ''),
                'sales_person': order_data.get('sales_person', ''),
                'tailor_id': order_data.get('tailor_id') or False,
                'notes': order_data.get('notes', ''),
            })

            # Hizmet satırları oluştur
            for svc in order_data.get('services', []):
                OrderLine.create({
                    'order_id': order.id,
                    'service_id': svc['id'],
                    'price': svc['price'],
                })

            created.append({
                'id': order.id,
                'name': order.name,
                'total_price': order.total_price,
            })

        return {'success': True, 'orders': created}

    # ── Sipariş Listesi ──
    @http.route('/ugurlar_tailor/orders', type='json', auth='user')
    def get_orders(self, status=None, search='', page=1, limit=20):
        domain = []
        if status:
            domain.append(('state', '=', status))
        if search:
            domain.append('|')
            domain.append('|')
            domain.append(('invoice_no', 'ilike', search))
            domain.append(('customer_name', 'ilike', search))
            domain.append(('name', 'ilike', search))

        offset = (int(page) - 1) * int(limit)
        total = request.env['ugurlar.tailor.order'].search_count(domain)
        orders = request.env['ugurlar.tailor.order'].search_read(
            domain,
            ['id', 'name', 'invoice_no', 'product_name', 'product_barcode',
             'customer_name', 'customer_phone', 'sales_person',
             'tailor_id', 'total_price', 'state', 'notes',
             'create_date', 'completed_at', 'delivered_at'],
            order='create_date desc',
            limit=int(limit),
            offset=offset,
        )

        # Her sipariş için hizmet satırlarını ekle
        for order in orders:
            lines = request.env['ugurlar.tailor.order.line'].search_read(
                [('order_id', '=', order['id'])],
                ['service_name', 'price'],
            )
            order['services'] = lines

        return {
            'orders': orders,
            'total': total,
            'page': int(page),
            'limit': int(limit),
        }

    # ── Sipariş Durum Güncelle ──
    @http.route('/ugurlar_tailor/update_status', type='json', auth='user')
    def update_status(self, order_id=0, status=''):
        order = request.env['ugurlar.tailor.order'].browse(int(order_id))
        if not order.exists():
            return {'success': False, 'error': 'Sipariş bulunamadı!'}

        action_map = {
            'in_progress': 'action_send_to_tailor',
            'completed': 'action_mark_completed',
            'delivered': 'action_mark_delivered',
            'pending': 'action_reset_to_pending',
        }
        method = action_map.get(status)
        if method:
            getattr(order, method)()
            return {'success': True}
        return {'success': False, 'error': 'Geçersiz durum!'}
