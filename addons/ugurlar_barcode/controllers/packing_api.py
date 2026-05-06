"""Paketleme & Faturalama API — batch bazlı ürün eşleştirme, fatura, etiket."""
import logging
from markupsafe import Markup

from odoo import http
from odoo.http import request

from .base_api import BarcodeApiBase

_logger = logging.getLogger(__name__)


# Marketplace order field registry — yeni pazaryeri eklendiğinde sadece buraya ekle
_MARKETPLACE_REGISTRY = [
    ('trendyol_order_id', 'trendyol_order_number', 'Trendyol'),
    ('hb_order_id', 'hb_order_number', 'Hepsiburada'),
    ('amazon_order_id', 'amazon_order_number', 'Amazon'),
    ('pazarama_order_id', 'order_number', 'Pazarama'),
    ('n11_order_id', 'order_number', 'N11'),
    ('flo_order_id', 'order_number', 'Flo'),
    ('idefix_order_id', 'order_number', 'Idefix'),
    ('pttavm_order_id', 'order_number', 'PttAvm'),
]


def _extract_marketplace_info(sale_order):
    """Sale order'dan marketplace sipariş bilgilerini çek.

    Returns:
        dict: cargo_tracking, cargo_provider, customer_name, order_number, marketplace_name
    """
    for field, num_field, name in _MARKETPLACE_REGISTRY:
        if hasattr(sale_order, field) and getattr(sale_order, field):
            order = getattr(sale_order, field)
            # Kargo takip no: birden fazla field dene
            cargo_tracking = (
                getattr(order, 'cargo_tracking_number', '') or
                getattr(order, 'cargo_tracking', '') or
                getattr(order, 'cargo_code', '') or
                getattr(order, 'shipment_code', '') or  # Pazarama PZ kodu
                ''
            )
            # Kargo firması
            cargo_provider = (
                getattr(order, 'cargo_provider', '') or
                getattr(order, 'cargo_company', '') or
                ''
            )
            # Kargo satır seviyesinde de olabilir (Pazarama line_ids)
            if not cargo_tracking or not cargo_provider:
                line_ids = getattr(order, 'line_ids', None)
                if line_ids:
                    for line in line_ids:
                        if not cargo_tracking:
                            cargo_tracking = getattr(line, 'cargo_tracking', '') or ''
                        if not cargo_provider:
                            cargo_provider = getattr(line, 'cargo_company', '') or ''
                        if cargo_tracking and cargo_provider:
                            break
            return {
                'marketplace_name': name,
                'cargo_tracking': cargo_tracking,
                'cargo_provider': cargo_provider,
                'customer_name': getattr(order, 'customer_name', '') or '',
                'order_number': getattr(order, num_field, '') or '',
            }
    return {
        'marketplace_name': '',
        'cargo_tracking': '', 'cargo_provider': '',
        'customer_name': '', 'order_number': '',
    }


class PackingApiController(BarcodeApiBase):
    """Paketleme & Faturalama API'leri."""

    @http.route('/ugurlar_barcode/api/packing_batch_detail', type='json', auth='user')
    def packing_batch_detail(self, batch_name='', batch_id=0, **kw):
        """Rota numarası veya ID ile batch detayı getir."""
        Batch = request.env['stock.picking.batch'].sudo()

        if batch_id:
            batch = Batch.browse(int(batch_id))
        elif batch_name:
            batch = Batch.search([
                '|',
                ('name', '=', batch_name.strip()),
                ('name', 'ilike', batch_name.strip()),
            ], limit=1)
        else:
            return {'error': 'Rota numarası gerekli'}

        if not batch or not batch.exists():
            return {'error': f'Rota bulunamadı: {batch_name or batch_id}'}

        # OPTIMIZASYON: Tüm siparişleri (sale order) toplu çek
        picking_origins = [p.origin for p in batch.picking_ids if p.origin]
        sales_dict = {}
        if picking_origins:
            sales = request.env['sale.order'].sudo().search([('name', 'in', picking_origins)])
            for s in sales:
                sales_dict[s.name] = s

        # Tüm picking'lerdeki ürünleri topla
        items = []
        for picking in batch.picking_ids:
            # Kargo bilgileri (sale order üzerinden - prefetch edilmiş veriden al)
            cargo_tracking = ''
            cargo_provider = ''
            customer_name = ''
            order_number = ''

            if picking.origin and picking.origin in sales_dict:
                sale = sales_dict[picking.origin]
                mp_info = _extract_marketplace_info(sale)
                cargo_tracking = mp_info['cargo_tracking']
                cargo_provider = mp_info['cargo_provider']
                customer_name = mp_info['customer_name']
                order_number = mp_info['order_number']

            for move in picking.move_ids:
                product = move.product_id

                items.append({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'picking_name': picking.name,
                    'product_id': product.id,
                    'product_name': product.display_name,
                    'barcode': product.barcode or '',
                    'demand_qty': move.product_uom_qty,
                    'done_qty': move.quantity,
                    'matched': move.quantity >= move.product_uom_qty,
                    'origin': picking.origin or '',
                    'customer_name': customer_name,
                    'cargo_tracking': cargo_tracking,
                    'cargo_provider': cargo_provider,
                    'order_number': order_number,
                    'image_url': f'/web/image/product.product/{product.id}/image_128',
                })

        total = len(items)
        matched = sum(1 for i in items if i['matched'])

        return {
            'batch': {
                'id': batch.id,
                'name': batch.name,
                'state': batch.state,
                'time_window': batch.time_window or '',
            },
            'items': items,
            'total': total,
            'matched': matched,
            'all_matched': matched == total,
        }

    @http.route('/ugurlar_barcode/api/packing_scan', type='json', auth='user')
    def packing_scan(self, batch_id=0, barcode='', **kw):
        """Paketleme sırasında ürün barkodu tara → eşleştir."""
        # Duplicate guard: aynı barkod 500ms içinde tekrar taranırsa atla
        if self._check_duplicate_request('packing_scan', batch_id, barcode):
            return {'warning': True, 'message': 'Çift okutma algılandı, lütfen tekrar deneyin'}
        batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
        if not batch.exists():
            return {'error': 'Rota bulunamadı'}

        barcode = barcode.strip()
        product = self._find_product(barcode)
        if not product:
            return {'error': f'Ürün bulunamadı: {barcode}'}

        # Batch'teki picking'lerde bu ürünü bul (henüz tamamlanmamış)
        target_move = None
        target_picking = None
        for picking in batch.picking_ids:
            for move in picking.move_ids:
                if (move.product_id.id == product.id and
                        move.quantity < move.product_uom_qty):
                    target_move = move
                    target_picking = picking
                    break
            if target_move:
                break

        if not target_move:
            # Belki tamamlanmış — bilgi ver
            for picking in batch.picking_ids:
                for move in picking.move_ids:
                    if move.product_id.id == product.id:
                        return {
                            'warning': True,
                            'message': f'{product.display_name} zaten tamamlandı',
                            'product_name': product.display_name,
                            'picking_completed': all(m.quantity >= m.product_uom_qty for m in picking.move_ids),
                            'picking_id': picking.id,
                            'picking_name': picking.name,
                        }
            return {'error': f'Bu ürün rotada yok: {product.display_name}'}

        # Barkod eşleşti → qty artır
        new_qty = target_move.quantity + 1
        target_move.write({'quantity': new_qty})

        # Log
        try:
            user = request.env.user
            request.env['ugurlar.barcode.operation'].sudo().create({
                'operation_type': 'picking',
                'barcode': barcode,
                'product_id': product.id,
                'quantity': 1,
                'state': 'done',
            })

            # Chatter log for scan
            msg = Markup(
                '<b>&#128230; Paketleme Eslestirme:</b> <em>%s</em> tarafindan '
                '<b>%s</b> siparisinde <b>%s</b> 1 adet eslestirildi.'
            ) % (user.name, target_picking.name, product.display_name)
            product.sudo().message_post(
                body=msg, message_type='notification', subtype_xmlid='mail.mt_note')
        except Exception:
            pass

        # Check if individual picking is complete
        picking_total = sum(m.product_uom_qty for m in target_picking.move_ids)
        picking_matched = sum(m.quantity for m in target_picking.move_ids)
        picking_completed = all(m.quantity >= m.product_uom_qty for m in target_picking.move_ids)

        remaining_items = []
        for m in target_picking.move_ids:
            if m.quantity < m.product_uom_qty:
                remaining_items.append(f"{m.product_id.display_name} ({m.product_uom_qty - m.quantity} adet)")

        if picking_completed and target_picking.state != 'done':
            try:
                target_picking.packing_done = True
                
                # 1. Odoo Teslimatını (Picking) Doğrula
                target_picking.button_validate()
                
                # SADECE ŞİMDİ PAKETLENENLER İÇİN 3 AŞAMALI SİNK TETİKLENİYOR
                self._trigger_nebim_sync(target_picking)

            except Exception as e:
                _logger.error("Auto-validate/sync error for %s: %s", target_picking.name, e)

        # Tüm batch kontrolü
        all_matched = all(
            m.quantity >= m.product_uom_qty
            for p in batch.picking_ids
            for m in p.move_ids
        )

        return {
            'success': True,
            'product_name': product.display_name,
            'done_qty': new_qty,
            'demand_qty': target_move.product_uom_qty,
            'picking_name': target_picking.name,
            'picking_id': target_picking.id,
            'picking_completed': picking_completed,
            'picking_total': picking_total,
            'picking_matched': picking_matched,
            'remaining_items': remaining_items,
            'complete': new_qty >= target_move.product_uom_qty,
            'all_matched': all_matched,
        }

    @http.route('/ugurlar_barcode/api/packing_undo', type='json', auth='user')
    def packing_undo(self, picking_id=0, barcode='', **kw):
        """Paketlemede yanlış okutulan ürünü geri alır (Miktar -1)."""
        picking = request.env['stock.picking'].sudo().browse(int(picking_id))
        if not picking.exists() or picking.state == 'done':
            return {'error': 'Sipariş tamamlanmış veya bulunamadı'}

        product = self._find_product(barcode.strip())
        if not product:
            return {'error': 'Ürün bulunamadı'}

        target_move = None
        for move in picking.move_ids:
            if move.product_id.id == product.id:
                target_move = move
                break

        if not target_move or target_move.quantity <= 0:
            return {'error': 'Bu üründen silinecek okutulmuş miktar yok'}

        new_qty = target_move.quantity - 1
        target_move.write({'quantity': new_qty})

        # Log kaydı
        try:
            user = request.env.user
            msg = Markup(
                '<b>&#10060; Hatalı Okutmayi Geri Alma:</b> <em>%s</em> tarafindan '
                '<b>%s</b> siparisinden 1 adet <b>%s</b> cikarildi (Eksi islemi).'
            ) % (user.name, picking.name, product.display_name)
            picking.message_post(body=msg, message_type='notification')
        except Exception:
            pass

        return {'success': True, 'message': f'{product.name} siparişten 1 adet eksiltildi.'}

    @http.route('/ugurlar_barcode/api/packing_backorder', type='json', auth='user')
    def packing_backorder(self, picking_id=0, **kw):
        """Kısmi olarak tamamlanmış siparişi kapatır ve geriye kalanları backorder (eksik) yapar."""
        picking = request.env['stock.picking'].sudo().browse(int(picking_id))
        if not picking.exists() or picking.state == 'done':
            return {'error': 'Geçerli bir sipariş bulunamadı veya zaten tamamlanmış'}

        try:
            picking.packing_done = True
            # Button validate dönerse backorder wizard açılmasını ister. Odoo bunu dict olarak döner.
            res = picking.button_validate()
            if isinstance(res, dict) and res.get('res_model') == 'stock.backorder.confirmation':
                wiz = request.env['stock.backorder.confirmation'].sudo().with_context(res.get('context')).create(
                    {'pick_ids': [(4, p.id) for p in picking]}
                )
                wiz.process()
            
            # Log kaydı
            user = request.env.user
            msg = Markup(
                '<b>&#9888; Eksik Urunle Kapatma (Backorder):</b> <em>%s</em> tarafindan '
                'bu siparis eksik urun ile zorla onaylandi. Degisiklikler uygulandi.'
            ) % user.name
            picking.message_post(body=msg, message_type='notification')
            
            return {'success': True, 'message': '%s eksik ürünlerle onaylandı (Backorder oluşturuldu).' % picking.name}
        except Exception:
            _logger.exception("Backorder error for %s", picking.name)
            return {'error': 'Eksik onaylama hatası'}

    @http.route('/ugurlar_barcode/api/packing_complete', type='json', auth='user')
    def packing_complete(self, batch_id=0, **kw):
        """Paketleme tamamla — picking'leri doğrula."""
        batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
        if not batch.exists():
            return {'error': 'Rota bulunamadı'}

        validated = 0
        errors = []

        for picking in batch.picking_ids:
            try:
                if picking.state == 'done':
                    # Eğer daha önce onaylanmış ama Nebim'de takılı kalmışsa tekrar dene
                    self._trigger_nebim_sync(picking)
                    validated += 1
                    continue

                picking.packing_done = True
                # API'den tekrar gelirse button_validate çağır
                res = picking.button_validate()
                
                # Eğer res bir Dict dönerse (örneğin Backorder Wizard) hata değildir ama bitmemiştir
                if isinstance(res, dict):
                    # Backorder popup API tarafında çalıştırılamaz, skip.
                    _logger.warning("Picking was partially validated via Backorder Wizard return: %s", picking.name)
                
                # Sadece DONE olanları senkronize et
                if picking.state == 'done':
                    self._trigger_nebim_sync(picking)
                    validated += 1
                
            except Exception as e:
                _logger.exception("Sipariş Onay/Senkronizasyon Hatası %s:", picking.name)
                errors.append(f"{picking.name}: {str(e)}")

        return {
            'success': len(errors) == 0,
            'validated': validated,
            'total': len(batch.picking_ids),
            'errors': errors,
            'message': f'{validated} sipariş paketlendi ve doğrulandı',
        }

    @http.route('/ugurlar_barcode/api/packing_label_data', type='json', auth='user')
    def packing_label_data(self, picking_id=0, **kw):
        """Kargo etiketi için sipariş verilerini döndür."""
        picking = request.env['stock.picking'].sudo().browse(int(picking_id))
        if not picking.exists():
            return {'error': 'Sipariş bulunamadı'}

        # Sipariş bilgilerini topla
        data = {
            'picking_name': picking.name,
            'origin': picking.origin or '',
            'partner_name': picking.partner_id.name or '',
            'partner_phone': picking.partner_id.phone or picking.partner_id.mobile or '',
            'partner_address': '',
            'cargo_tracking': '',
            'cargo_provider': '',
            'order_number': '',
            'customer_name': '',
            'marketplace_name': '',
            'shipping_address': '',
            'shipping_city': '',
            'shipping_district': '',
        }

        if picking.partner_id:
            addr_parts = [
                picking.partner_id.street or '',
                picking.partner_id.street2 or '',
                picking.partner_id.city or '',
                picking.partner_id.state_id.name if picking.partner_id.state_id else '',
            ]
            data['partner_address'] = ', '.join(p for p in addr_parts if p)

        if picking.origin:
            sale = request.env['sale.order'].sudo().search([
                ('name', '=', picking.origin)
            ], limit=1)
            if sale:
                mp_info = _extract_marketplace_info(sale)
                data['cargo_tracking'] = mp_info['cargo_tracking']
                data['cargo_provider'] = mp_info['cargo_provider']
                data['order_number'] = mp_info['order_number']
                data['customer_name'] = mp_info['customer_name']
                data['marketplace_name'] = mp_info['marketplace_name']

                # Shipping fields — her marketplace modülünden çek
                for field, num_field, name in _MARKETPLACE_REGISTRY:
                    if hasattr(sale, field) and getattr(sale, field):
                        morder = getattr(sale, field)
                        # shipping_address — bazı modellerde 'shipping_address', bazılarında 'shipment_address' (JSON)
                        addr = getattr(morder, 'shipping_address', '') or ''
                        if not addr:
                            # Pazarama: shipment_address JSON field'ından parse et
                            import json as _json
                            raw_addr = getattr(morder, 'shipment_address', '') or ''
                            if raw_addr:
                                try:
                                    addr_data = _json.loads(raw_addr)
                                    addr_parts = [
                                        addr_data.get('neighborhoodName', ''),
                                        addr_data.get('addressDetail', ''),
                                    ]
                                    addr = ' '.join(p for p in addr_parts if p)
                                except (ValueError, TypeError):
                                    addr = raw_addr[:200]
                        data['shipping_address'] = addr or data['partner_address']
                        data['shipping_city'] = getattr(morder, 'shipping_city', '') or ''
                        data['shipping_district'] = getattr(morder, 'shipping_district', '') or ''
                        break

        # Fallback: Odoo picking kargo ref'i
        if not data['cargo_tracking'] and picking.carrier_tracking_ref:
            data['cargo_tracking'] = picking.carrier_tracking_ref

        # Fallback: Partner bilgileri (eğer marketplace verisi yoksa)
        if not data['shipping_address']:
            data['shipping_address'] = data['partner_address']
        if not data['shipping_city'] and picking.partner_id:
            data['shipping_city'] = picking.partner_id.state_id.name if picking.partner_id.state_id else ''
        if not data['shipping_district'] and picking.partner_id:
            data['shipping_district'] = picking.partner_id.city or ''
        if not data['customer_name']:
            data['customer_name'] = data['partner_name']

        # Ürün listesi
        items = []
        for move in picking.move_ids:
            items.append({
                'product_name': move.product_id.display_name,
                'barcode': move.product_id.barcode or '',
                'default_code': move.product_id.default_code or '',
                'qty': move.product_uom_qty,
            })
        data['items'] = items
        data['total_items'] = len(items)
        data['total_qty'] = sum(i['qty'] for i in items)

        # Log
        try:
            user = request.env.user
            msg = Markup(
                '<b>&#128424; Kargo Etiketi Yazdirildi:</b> <em>%s</em> tarafindan '
                '<b>%s</b> siparisi icin etiket olusturuldu (Kargo Takip: %s).'
            ) % (user.name, picking.name, data['cargo_tracking'] or 'Yok')
            for move in picking.move_ids:
                move.product_id.sudo().message_post(
                    body=msg, message_type='notification', subtype_xmlid='mail.mt_note')
        except Exception:
            pass

        return data

    def _trigger_nebim_sync(self, picking):
        """
        Nebim senkronizasyonunu başlatır (Müşteri -> Sipariş -> Fatura).
        
        Her aşama kendi savepoint'inde çalışır — Nebim hatası DB cursor'ı bozmaz.
        Hata olsa bile picking validation'ı ve UI çalışmaya devam eder.
        """
        from odoo import fields
        
        sale_order = picking.sale_id
        if not sale_order and picking.origin:
            sale_order = picking.env['sale.order'].sudo().search([('name', '=', picking.origin)], limit=1)

        if not sale_order:
            _logger.warning("Nebim Sync Atlandı: %s için sipariş bulunamadı.", picking.name)
            return

        _logger.info("Nebim Senkronizasyonu başlıyor: %s", sale_order.name)
        
        # Toggle ayarlarını oku
        # Toggle ayarları
        ICP = picking.env['ir.config_parameter'].sudo()
        customer_enabled = ICP.get_param('odoougurlar.nebim_sync_customer_enabled', 'False') == 'True'
        order_enabled = ICP.get_param('odoougurlar.nebim_sync_order_enabled', 'False') == 'True'
        invoice_enabled = ICP.get_param('odoougurlar.nebim_sync_invoice_enabled', 'False') == 'True'
        
        # Pazaryeri tespiti (registry tabanlı)
        mp_info = _extract_marketplace_info(sale_order)
        marketplace_name = mp_info['marketplace_name']
        
        # Mapping Bul
        mapping = picking.env['odoougurlar.marketplace.mapping'].sudo().find_mapping(
            marketplace_name, sale_order.partner_id.country_id.id
        )
        
        nebim_errors = []
        
        # ═══ Aşama A: Cari Aktarımı (savepoint korumalı) ═══
        if customer_enabled and not sale_order.nebim_customer_sent:
            try:
                with picking.env.cr.savepoint():
                    customer_proc = picking.env['odoougurlar.customer.processor'].sudo()
                    cust_code, addr_id = customer_proc.sync_customer(
                        sale_order.partner_id, mapping, sale_order=sale_order
                    )
                    sale_order.write({
                        'nebim_customer_sent': True,
                        'nebim_customer_code': cust_code or '',
                        'nebim_address_id': addr_id or ''
                    })
                    _logger.info("Nebim Cari başarılı: %s → %s", sale_order.name, cust_code)
            except Exception as e:
                nebim_errors.append(f"[Cari] {str(e)}")
                _logger.error("Nebim Cari hatası (%s): %s", sale_order.name, e)
        elif not customer_enabled:
            _logger.info("Nebim Cari toggle kapalı: %s", sale_order.name)
            
        # ═══ Aşama B: Sipariş Aktarımı (savepoint korumalı) ═══
        if order_enabled and not sale_order.nebim_order_sent:
            try:
                with picking.env.cr.savepoint():
                    order_proc = picking.env['odoougurlar.order.processor'].sudo()
                    order_proc.sync_order(sale_order, mapping)
                    _logger.info("Nebim Sipariş başarılı: %s", sale_order.name)
            except Exception as e:
                nebim_errors.append(f"[Sipariş] {str(e)}")
                _logger.error("Nebim Sipariş hatası (%s): %s", sale_order.name, e)
        elif not order_enabled:
            _logger.info("Nebim Sipariş toggle kapalı: %s", sale_order.name)
            
        # ═══ Aşama C: Fatura Oluşturma ve Aktarımı ═══
        if invoice_enabled:
            try:
                # Fatura oluştur
                invoices_to_post = sale_order.invoice_ids.filtered(lambda i: i.state == 'draft')
                if not sale_order.invoice_ids and sale_order.invoice_status in ['to invoice', 'invoiced']:
                    invoices_to_post = sale_order._create_invoices()
                    
                for invoice in invoices_to_post:
                    invoice.action_post()
                
                # Nebim'e gönder
                unposted_nebim = sale_order.invoice_ids.filtered(
                    lambda i: i.state == 'posted' and not getattr(i, 'nebim_sent', False)
                )
                for check_invoice in unposted_nebim:
                    invoice_proc = picking.env['odoougurlar.invoice.processor'].sudo()
                    connector = picking.env['odoougurlar.nebim.connector'].sudo()
                    payload = invoice_proc._build_invoice_payload(check_invoice)
                    result = connector.post_data('Post', payload)
                    
                    if isinstance(result, dict) and 'ExceptionMessage' in result:
                        raise Exception(f"Nebim Fatura Hatası: {result['ExceptionMessage']}")
                    
                    # Nebim fatura numarasını ayrıştır
                    nebim_inv_no = ''
                    if isinstance(result, dict):
                        nebim_inv_no = (result.get('DocumentNumber', '')
                                      or result.get('EInvoiceNumber', '')
                                      or result.get('InvoiceNumber', ''))
                    elif isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
                        nebim_inv_no = (result[0].get('DocumentNumber', '')
                                      or result[0].get('EInvoiceNumber', '')
                                      or result[0].get('InvoiceNumber', ''))
                    
                    check_invoice.write({
                        'nebim_sent': True,
                        'nebim_sent_date': fields.Datetime.now(),
                        'nebim_response': str(result),
                        'nebim_error': False,
                    })
                    if nebim_inv_no:
                        check_invoice.write({'nebim_invoice_number': nebim_inv_no})
                    
                    _logger.info("Nebim Fatura başarılı: %s", check_invoice.name)
            except Exception as e:
                nebim_errors.append(f"[Fatura] {str(e)}")
                _logger.error("Nebim Fatura hatası (%s): %s", sale_order.name, e)
        else:
            _logger.info("Nebim Fatura toggle kapalı: %s", sale_order.name)
        
        # ═══ Hata özeti yaz (savepoint dışında, güvenli) ═══
        if nebim_errors:
            try:
                error_msg = ' | '.join(nebim_errors)
                sale_order.write({'nebim_order_response': f'HATA: {error_msg}'})
            except Exception:
                _logger.warning("Nebim hata özeti yazılamadı: %s", sale_order.name)
            # RAISE YAPILMIYOR — Cursor korunuyor, UI çalışmaya devam eder
