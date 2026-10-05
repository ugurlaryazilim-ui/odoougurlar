import json
from collections import defaultdict
import logging

from odoo import fields, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from odoo.addons.sms_system.services.turatel import normalize_number

_logger = logging.getLogger(__name__)


def _local_dt(record, value, fmt='%d.%m.%Y %H:%M'):
    """UTC datetime'ı kullanıcının saat dilimine çevirip biçimle."""
    if not value:
        return ''
    return fields.Datetime.context_timestamp(record, fields.Datetime.to_datetime(value)).strftime(fmt)


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
        detail = connector.get_invoice_detail(invoice_no)
        if detail:
            # Nebim'deki numara cep değilse (sabit hat vb.) kullanılmaz
            mobile = normalize_number(detail.get('customer_mobile'))
            detail['customer_mobile'] = '0' + mobile if mobile else ''
            detail['mobile_source'] = 'nebim' if mobile else ''
            if not mobile and detail.get('customer_code'):
                detail.update(self._mobile_from_history(detail['customer_code']))
        return detail

    @staticmethod
    def _mobile_from_history(customer_code):
        """Aynı müşteri kodunun önceki terzi siparişindeki cep numarası.

        Kasa / genel müşteri kodları birçok kişide ortaktır: kodun siparişlerinde birden fazla farklı
        numara varsa öneri yapılmaz (başka müşterinin numarası gelmesin).
        """
        orders = request.env['ugurlar.tailor.order'].search(
            [('customer_phone', '=', customer_code), ('customer_mobile', '!=', False)], order='id desc', limit=20)
        numbers = {normalize_number(o.customer_mobile) for o in orders} - {None}
        if len(numbers) == 1:
            return {'customer_mobile': '0' + numbers.pop(), 'mobile_source': 'history'}
        return {}

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
            ['id', 'name', 'price', 'customer_price', 'sequence'],
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

        # Nebim view'ında ürün adı yok: barkoddan Odoo ürün adını bul (tek sorgu)
        barcodes = [o.get('barcode') for o in orders if o.get('barcode')]
        product_names = {
            p.barcode: p.name
            for p in env['product.product'].search([('barcode', 'in', barcodes)])
        } if barcodes else {}

        order_vals = []
        for order_data in orders:
            tailor_id = int(order_data.get('tailor_id') or 0)
            if tailor_id not in tailors.ids:
                return {'success': False, 'error': 'Geçersiz veya pasif terzi seçildi!'}
            svc_ids = [int(svc['id']) for svc in (order_data.get('services') or []) if svc.get('id')]
            if not svc_ids:
                return {'success': False, 'error': 'Her ürün için en az bir hizmet seçiniz!'}
            measures = {int(svc['id']): (svc.get('measure') or '').strip()[:100]
                        for svc in (order_data.get('services') or []) if svc.get('id')}
            lines = []
            default_charge = 0.0
            for sid in dict.fromkeys(svc_ids):  # sırayı koruyarak tekrarları at
                service = services.filtered(lambda s, sid=sid: s.id == sid)
                if not service:
                    return {'success': False, 'error': 'Geçersiz veya pasif hizmet seçildi!'}
                price = special.get((tailor_id, sid), service.price)
                default_charge += service.customer_price
                lines.append((0, 0, {'service_id': sid, 'price': price, 'measure': measures.get(sid) or False}))
            try:
                charge = max(float(order_data['customer_charge']), 0.0) \
                    if order_data.get('customer_charge') not in (None, '') else default_charge
                deposit = max(float(order_data.get('deposit') or 0), 0.0)
            except (TypeError, ValueError):
                return {'success': False, 'error': 'Ücret / kapora sayı olmalı!'}
            # Faturasız sipariş = reyon siparişi (onaydan geçer; model create'te zorlanır)
            is_reyon = bool(order_data.get('is_reyon')) or not order_data.get('invoice_no')
            order_vals.append({
                'invoice_no': order_data.get('invoice_no', ''),
                'is_reyon': is_reyon,
                'state': 'waiting_approval' if is_reyon else 'pending',
                'product_barcode': order_data.get('barcode', ''),
                'product_code': order_data.get('product_code', ''),
                'product_name': product_names.get(order_data.get('barcode'))
                or order_data.get('product_name', ''),
                'customer_name': order_data.get('customer_name', ''),
                'customer_phone': order_data.get('customer_phone', ''),
                'sales_person': order_data.get('sales_person', ''),
                'tailor_id': tailor_id,
                'notes': order_data.get('notes', ''),
                'customer_mobile': (order_data.get('customer_mobile') or '').strip(),
                'customer_charge': charge,
                'deposit': min(deposit, charge) if charge else deposit,
                'line_ids': lines,
            })
            if order_data.get('promised_date'):
                order_vals[-1]['promised_date'] = order_data['promised_date']
            photo = order_data.get('photo') or ''
            if photo:
                # data:image/jpeg;base64,... -> yalnız base64 kısmı
                order_vals[-1]['photo'] = photo.split(',', 1)[1] if photo.startswith('data:') else photo

        created_orders = Order.create(order_vals)
        created = [{'id': o.id, 'name': o.name, 'total_price': o.total_price} for o in created_orders]

        # Etiket PDF URL'i olustur
        label_url = '/report/pdf/ugurlar_tailor.report_tailor_label/%s' % ','.join(
            str(i) for i in created_orders.ids)

        # Etiket verisi aynı cevapta döner (her sipariş için ayrı istek atılmasın)
        labels = [self._label_payload(o) for o in created_orders if o.state != 'waiting_approval']
        return {'success': True, 'orders': created, 'label_url': label_url, 'labels': labels}

    # ── Sipariş Listesi ──
    @http.route('/ugurlar_tailor/orders', type='jsonrpc', auth='user')
    def get_orders(self, status=None, search='', page=1, limit=20):
        domain = []
        if status and status != 'overdue':
            domain.append(('state', '=', status))
        if status == 'overdue':
            domain = [('is_overdue', '=', True)]
        if search:
            search = search.strip()
            domain += ['|', '|', '|', '|',
                       ('location', 'ilike', search),
                       ('invoice_no', 'ilike', search),
                       ('customer_name', 'ilike', search),
                       ('name', 'ilike', search),
                       ('product_barcode', '=', search)]

        offset = (int(page) - 1) * int(limit)
        total = request.env['ugurlar.tailor.order'].search_count(domain)
        orders = request.env['ugurlar.tailor.order'].search_read(
            domain,
            ['id', 'name', 'invoice_no', 'product_name', 'product_barcode',
             'customer_name', 'customer_phone', 'sales_person',
             'tailor_id', 'total_price', 'state', 'notes',
             'create_date', 'completed_at', 'delivered_at', 'cancelled_at',
             'promised_date', 'is_overdue', 'customer_mobile',
             'location', 'customer_charge', 'balance', 'is_paid'],
            order='create_date desc',
            limit=int(limit),
            offset=offset,
        )

        # Tarihler kullanıcının saat diliminde (UTC basılınca 3 saat geri görünüyordu)
        Order = request.env['ugurlar.tailor.order']
        for o in orders:
            o['create_date_local'] = _local_dt(Order, o['create_date'])

        # Tüm hizmet satırlarını tek sorguda getir ve order_id'ye göre grupla
        order_ids = [o['id'] for o in orders]
        all_lines = request.env['ugurlar.tailor.order.line'].search_read(
            [('order_id', 'in', order_ids)],
            ['order_id', 'service_name', 'price', 'measure'],
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

    # ── Ana menü sayaçları ──
    @http.route('/ugurlar_tailor/stats', type='jsonrpc', auth='user')
    def stats(self):
        Order = request.env['ugurlar.tailor.order']
        counts = dict(Order._read_group([('state', 'in', ('waiting_approval', 'pending', 'in_progress', 'completed'))],
                                        ['state'], ['__count']))
        counts['overdue'] = Order.search_count([('is_overdue', '=', True)])
        return counts

    # ── SMS (mobil liste) ──
    @http.route('/ugurlar_tailor/send_sms', type='jsonrpc', auth='user')
    def send_sms(self, order_id=0, number='', template_code=''):
        """Siparişe şablonlu SMS. Numara verilirse siparişe de kaydedilir."""
        order = request.env['ugurlar.tailor.order'].browse(int(order_id)).exists()
        if not order:
            return {'success': False, 'error': 'Sipariş bulunamadı!'}
        number = (number or '').strip()
        if number and number != order.customer_mobile:
            order.customer_mobile = number
        if not order.customer_mobile:
            return {'success': False, 'error': 'Müşteri cep telefonu yok.', 'need_number': True}
        code = template_code or ('tailor_ready' if order.state == 'completed' else 'tailor_reminder')
        try:
            msg = order._send_template_sms(code)
        except UserError as e:
            request.env.cr.rollback()
            return {'success': False, 'error': str(e)}
        if not msg:
            return {'success': False, 'error': 'SMS şablonu bulunamadı.'}
        if msg.state == 'error':
            return {'success': False, 'error': msg.error or 'SMS gönderilemedi.'}
        return {'success': True, 'state': msg.state}

    # ── Sipariş Durum Güncelle ──
    @http.route('/ugurlar_tailor/update_status', type='jsonrpc', auth='user')
    def update_status(self, order_id=0, status='', location=None):
        order = request.env['ugurlar.tailor.order'].browse(int(order_id))
        if not order.exists():
            return {'success': False, 'error': 'Sipariş bulunamadı!'}
        if location is not None and status == 'completed':
            order.location = (location or '').strip()[:50] or False

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
    @staticmethod
    def _label_payload(order):
        return {
            'id': order.id,
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
            'date': _local_dt(order, order.create_date),
            'promised_date': order.promised_date.strftime('%d.%m.%Y') if order.promised_date else '',
            'services': [{'name': line.service_name, 'price': line.price, 'measure': line.measure or ''}
                         for line in order.line_ids],
            'customer_charge': order.customer_charge,
            'deposit': order.deposit,
            'balance': order.balance,
            'is_paid': order.is_paid,
            'location': order.location or '',
            'promised': order.promised_date.strftime('%d.%m.%Y') if order.promised_date else '',
        }

    @http.route('/ugurlar_tailor/label_data', type='jsonrpc', auth='user')
    def label_data(self, order_id=0):
        """Etiket yazdırma için sipariş verisini döndür."""
        order = request.env['ugurlar.tailor.order'].browse(int(order_id))
        if not order.exists():
            return {'error': 'Sipariş bulunamadı!'}
        return self._label_payload(order)

    # ── Mağaza bilgisi (hediye fişi başlığı) ──
    @http.route('/ugurlar_tailor/company_info', type='jsonrpc', auth='user')
    def company_info(self):
        company = request.env.company
        partner = company.partner_id
        address = ', '.join(filter(None, [
            partner.street, partner.street2,
            ' '.join(filter(None, [partner.zip, partner.city])),
            partner.state_id.name,
        ]))
        return {'name': company.name or '', 'address': address, 'phone': partner.phone or company.phone or ''}

    # ── Toplu barkod işlemi ──
    @http.route('/ugurlar_tailor/find_order', type='jsonrpc', auth='user')
    def find_order(self, code=''):
        """Okutulan sipariş no (TRZ-xxxxx) ya da ürün barkoduyla açık siparişi bul."""
        code = (code or '').strip()
        if not code:
            return {'error': 'Barkod boş.'}
        Order = request.env['ugurlar.tailor.order']
        order = Order.search([('name', '=', code)], limit=1)
        if not order:
            order = Order.search([('product_barcode', '=', code),
                                  ('state', 'not in', ('delivered', 'cancelled'))], order='id desc', limit=1)
        if not order:
            return {'error': 'Sipariş bulunamadı: %s' % code}
        return {
            'id': order.id, 'name': order.name, 'state': order.state,
            'customer_name': order.customer_name or '', 'product_name': order.product_name or order.product_code or '',
            'tailor_id': order.tailor_id.id, 'tailor_name': order.tailor_id.name or '-',
            'location': order.location or '',
        }

    @http.route('/ugurlar_tailor/bulk_status', type='jsonrpc', auth='user')
    def bulk_status(self, order_ids=None, status='', location=None):
        """Okutulan siparişleri tek seferde ilerlet; her sipariş ayrı denenir (biri hata verse diğerleri geçer)."""
        action_map = {
            'in_progress': 'action_send_to_tailor',
            'completed': 'action_mark_completed',
            'delivered': 'action_mark_delivered',
        }
        method = action_map.get(status)
        if not method:
            return {'success': False, 'error': 'Geçersiz durum!'}
        results = []
        orders = request.env['ugurlar.tailor.order'].browse([int(i) for i in (order_ids or [])]).exists()
        for order in orders:
            try:
                with request.env.cr.savepoint():
                    if status == 'completed' and location:
                        order.location = location.strip()[:50]
                    getattr(order, method)()
                results.append({'id': order.id, 'name': order.name, 'ok': True})
            except (UserError, AccessError) as e:
                results.append({'id': order.id, 'name': order.name, 'ok': False, 'error': str(e)})
        done = orders.filtered(lambda o: any(r['ok'] and r['id'] == o.id for r in results))
        slips = []
        if status == 'in_progress':
            for tailor in done.mapped('tailor_id'):
                group = done.filtered(lambda o, t=tailor: o.tailor_id == t)
                slips.append({'tailor_name': tailor.name, 'orders': [self._label_payload(o) for o in group]})
        return {'success': True, 'results': results, 'slips': slips}

    # ── Müşteri geçmişi ──
    @http.route('/ugurlar_tailor/customer_history', type='jsonrpc', auth='user')
    def customer_history(self, customer_code='', mobile=''):
        keys = []
        if (mobile or '').strip():
            keys.append(('customer_mobile', '=', mobile.strip()))
        if (customer_code or '').strip():
            keys.append(('customer_phone', '=', customer_code.strip()))
        if not keys:
            return []
        domain = (['|'] * (len(keys) - 1)) + keys
        orders = request.env['ugurlar.tailor.order'].search(domain, order='create_date desc', limit=10)
        states = dict(request.env['ugurlar.tailor.order']._fields['state'].selection)
        return [{
            'name': o.name,
            'date': _local_dt(o, o.create_date, '%d.%m.%Y'),
            'product': o.product_name or o.product_code or '',
            'services': ', '.join(o.line_ids.mapped('service_name')),
            'state': states.get(o.state, o.state),
        } for o in orders]
