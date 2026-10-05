import json
from collections import defaultdict
import logging

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


class TailorController(http.Controller):
    """Terzi OWL frontend için JSON API endpoint'leri."""

    # ── Fatura Arama (Nebim MSSQL) ──
    @http.route('/ugurlar_tailor/search_invoice', type='jsonrpc', auth='user')
    def search_invoice(self, search_term=''):
        connector = request.env['ugurlar.tailor.mssql.connector']
        return connector.search_invoices(search_term)

    @http.route('/ugurlar_tailor/invoice_detail', type='jsonrpc', auth='user')
    def invoice_detail(self, invoice_no=''):
        connector = request.env['ugurlar.tailor.mssql.connector']
        return connector.get_invoice_detail(invoice_no)

    @http.route('/ugurlar_tailor/verify_product', type='jsonrpc', auth='user')
    def verify_product(self, invoice_no='', barcode=''):
        connector = request.env['ugurlar.tailor.mssql.connector']
        return connector.verify_product(invoice_no, barcode)

    @http.route('/ugurlar_tailor/search_product', type='jsonrpc', auth='user')
    def search_product(self, barcode=''):
        product = request.env['product.product'].search([('barcode', '=', barcode)], limit=1)
        if product:
            return {
                'barcode': product.barcode,
                'product_code': product.default_code or '',
                'product_name': product.name or ''
            }
        return None

    @http.route('/ugurlar_tailor/test_connection', type='jsonrpc', auth='user')
    def test_connection(self):
        connector = request.env['ugurlar.tailor.mssql.connector']
        return connector.test_connection()

    # ── Hizmetler ──
    @http.route('/ugurlar_tailor/services', type='jsonrpc', auth='user')
    def get_services(self):
        services = request.env['ugurlar.tailor.service'].search_read(
            [('active', '=', True)],
            ['id', 'name', 'price', 'sequence'],
            order='sequence, name',
        )
        return services

    # ── Terziler ──
    @http.route('/ugurlar_tailor/tailors', type='jsonrpc', auth='user')
    def get_tailors(self):
        tailors = request.env['ugurlar.tailor'].search_read(
            [('active', '=', True)],
            ['id', 'name', 'phone'],
            order='name',
        )
        # Tüm fiyatları tek sorguda getir ve tailor_id'ye göre grupla
        tailor_ids = [t['id'] for t in tailors]
        all_prices = request.env['ugurlar.tailor.price'].search_read(
            [('tailor_id', 'in', tailor_ids)],
            ['tailor_id', 'service_id', 'price'],
        )
        prices_by_tailor = defaultdict(list)
        for p in all_prices:
            prices_by_tailor[p['tailor_id'][0]].append(
                {'service_id': p['service_id'][0], 'price': p['price']}
            )
        for tailor in tailors:
            tailor['prices'] = prices_by_tailor.get(tailor['id'], [])
        return tailors

    # ── Sipariş Oluştur ──
    @http.route('/ugurlar_tailor/create_order', type='jsonrpc', auth='user')
    def create_order(self, orders=None):
        """Toplu sipariş oluşturma — her ürün için ayrı sipariş.

        Fiyatlar istemciden alınmaz: terziye özel fiyat, yoksa hizmetin varsayılan
        fiyatı sunucuda hesaplanır. Terzi ve hizmetlerin aktif olduğu doğrulanır.
        """
        if not orders:
            return {'success': False, 'error': 'Sipariş verisi boş!'}

        env = request.env
        Order = env['ugurlar.tailor.order']
        tailor_ids = {int(o['tailor_id']) for o in orders if o.get('tailor_id')}
        tailors = env['ugurlar.tailor'].browse(list(tailor_ids)).exists().filtered('active')
        service_ids = {int(svc['id']) for o in orders for svc in (o.get('services') or []) if svc.get('id')}
        services = env['ugurlar.tailor.service'].browse(list(service_ids)).exists().filtered('active')
        special = {
            (p.tailor_id.id, p.service_id.id): p.price
            for p in env['ugurlar.tailor.price'].search([('tailor_id', 'in', tailors.ids)])
        }

        order_vals = []
        for order_data in orders:
            tailor_id = int(order_data.get('tailor_id') or 0)
            if tailor_id not in tailors.ids:
                return {'success': False, 'error': 'Geçersiz veya pasif terzi seçildi!'}
            svc_ids = [int(svc['id']) for svc in (order_data.get('services') or []) if svc.get('id')]
            if not svc_ids:
                return {'success': False, 'error': 'Her ürün için en az bir hizmet seçiniz!'}
            lines = []
            for sid in dict.fromkeys(svc_ids):  # sırayı koruyarak tekrarları at
                service = services.filtered(lambda s, sid=sid: s.id == sid)
                if not service:
                    return {'success': False, 'error': 'Geçersiz veya pasif hizmet seçildi!'}
                price = special.get((tailor_id, sid), service.price)
                lines.append((0, 0, {'service_id': sid, 'price': price}))
            # Faturasız sipariş = reyon siparişi (onaydan geçer; model create'te zorlanır)
            is_reyon = bool(order_data.get('is_reyon')) or not order_data.get('invoice_no')
            order_vals.append({
                'invoice_no': order_data.get('invoice_no', ''),
                'is_reyon': is_reyon,
                'state': 'waiting_approval' if is_reyon else 'pending',
                'product_barcode': order_data.get('barcode', ''),
                'product_code': order_data.get('product_code', ''),
                'product_name': order_data.get('product_name', ''),
                'customer_name': order_data.get('customer_name', ''),
                'customer_phone': order_data.get('customer_phone', ''),
                'sales_person': order_data.get('sales_person', ''),
                'tailor_id': tailor_id,
                'notes': order_data.get('notes', ''),
                'line_ids': lines,
            })

        created_orders = Order.create(order_vals)
        created = [{'id': o.id, 'name': o.name, 'total_price': o.total_price} for o in created_orders]

        # Etiket PDF URL'i olustur
        label_url = '/report/pdf/ugurlar_tailor.report_tailor_label/%s' % ','.join(
            str(i) for i in created_orders.ids)

        return {'success': True, 'orders': created, 'label_url': label_url}

    # ── Sipariş Listesi ──
    @http.route('/ugurlar_tailor/orders', type='jsonrpc', auth='user')
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
             'create_date', 'completed_at', 'delivered_at', 'cancelled_at'],
            order='create_date desc',
            limit=int(limit),
            offset=offset,
        )

        # Tüm hizmet satırlarını tek sorguda getir ve order_id'ye göre grupla
        order_ids = [o['id'] for o in orders]
        all_lines = request.env['ugurlar.tailor.order.line'].search_read(
            [('order_id', 'in', order_ids)],
            ['order_id', 'service_name', 'price'],
        )
        lines_by_order = defaultdict(list)
        for line in all_lines:
            lines_by_order[line['order_id'][0]].append(line)
        for order in orders:
            order['services'] = lines_by_order.get(order['id'], [])

        return {
            'orders': orders,
            'total': total,
            'page': int(page),
            'limit': int(limit),
        }

    # ── Sipariş Durum Güncelle ──
    @http.route('/ugurlar_tailor/update_status', type='jsonrpc', auth='user')
    def update_status(self, order_id=0, status=''):
        order = request.env['ugurlar.tailor.order'].browse(int(order_id))
        if not order.exists():
            return {'success': False, 'error': 'Sipariş bulunamadı!'}

        action_map = {
            'in_progress': 'action_send_to_tailor',
            'completed': 'action_mark_completed',
            'delivered': 'action_mark_delivered',
            'pending': 'action_reset_to_pending',
            'cancelled': 'action_cancel',
        }
        method = action_map.get(status)
        if not method:
            return {'success': False, 'error': 'Geçersiz durum!'}
        try:
            getattr(order, method)()
        except (UserError, AccessError) as e:
            request.env.cr.rollback()
            return {'success': False, 'error': str(e)}
        return {'success': True}

    # ── Etiket Verisi ──
    @http.route('/ugurlar_tailor/label_data', type='jsonrpc', auth='user')
    def label_data(self, order_id=0):
        """Etiket yazdırma için sipariş verisini döndür."""
        order = request.env['ugurlar.tailor.order'].browse(int(order_id))
        if not order.exists():
            return {'error': 'Sipariş bulunamadı!'}

        lines = request.env['ugurlar.tailor.order.line'].search_read(
            [('order_id', '=', order.id)],
            ['service_name', 'price'],
        )

        return {
            'name': order.name,
            'invoice_no': order.invoice_no or '',
            'customer_name': order.customer_name or '',
            'customer_phone': order.customer_phone or '',
            'sales_person': order.sales_person or '',
            'product_code': order.product_code or '',
            'product_name': order.product_name or '',
            'product_barcode': order.product_barcode or '',
            'tailor_name': order.tailor_id.name if order.tailor_id else '-',
            'total_price': order.total_price,
            'notes': order.notes or '',
            'date': order.create_date.strftime('%d.%m.%Y %H:%M') if order.create_date else '',
            'services': [{'name': l['service_name'], 'price': l['price']} for l in lines],
        }
