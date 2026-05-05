
import json
import logging
import pytz
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

IST = pytz.timezone('Europe/Istanbul')

class PttavmOrderSync(models.Model):
    _inherit = 'pttavm.order'

    @api.model
    def sync_orders_from_pttavm(self):
        """Tüm aktif mağazalardan siparişleri senkronize et."""
        stores = self.env['pttavm.store'].search([('active', '=', True), ('auto_sync', '=', True)])
        for store in stores:
            try:
                self.sync_orders_for_store(store)
            except Exception as e:
                _logger.exception("Pttavm %s senkronizasyon hatası: %s", store.name, e)

    @api.model
    def sync_orders_for_store(self, store):
        """Seçilen mağazaya göre Pttavm'dan siparişleri çeker."""
        api_client = store.get_api()
        
        created_count = 0
        updated_count = 0
        error_count = 0
        
        day_range = store.order_day_range or 30
        # PttAVM API Türkiye saatinde çalışır — sorgu tarihlerini Türkiye saatine çevir
        now_turkey = datetime.now(pytz.UTC).astimezone(IST).replace(tzinfo=None)
        start_date = now_turkey - timedelta(days=day_range)
        end_date = now_turkey + timedelta(minutes=5)  # küçük güvenlik marjı
        
        _logger.info("PttAVM [%s] sipariş çekiliyor (TR saati): %s → %s (son %d gün)",
                     store.name, start_date, end_date, day_range)
        
        res = api_client.get_orders(start_date=start_date, end_date=end_date)
        
        if not res.get('success'):
            _logger.error("PttAVM Sipariş Çekme Hatası: %s", res.get('error'))
            return {'created': 0, 'updated': 0, 'errors': 1}
        
        raw_data = res.get('data', [])
        _logger.info("PttAVM [%s] API yanıt tipi: %s", store.name, type(raw_data).__name__)
        
        data_list = raw_data
        if isinstance(raw_data, dict):
            data_list = raw_data.get('data', raw_data.get('siparisler', raw_data.get('orders', [])))
            if not isinstance(data_list, list):
                _logger.info("PttAVM [%s] dict yanıt anahtarları: %s", store.name, list(raw_data.keys()))
                data_list = []
        
        if not data_list or not isinstance(data_list, list):
            _logger.info("PttAVM [%s] Sipariş bulunamadı. API yanıt: %s",
                         store.name, str(raw_data)[:500])
            store.sudo().write({'last_sync': fields.Datetime.now()})
            return {'created': 0, 'updated': 0, 'errors': 0}
        
        _logger.info("PttAVM [%s] %d sipariş bulundu", store.name, len(data_list))
            
        for order_json in data_list:
            try:
                with self.env.cr.savepoint():
                    action = self._process_order_json(order_json, store)
                    if action == 'created':
                        created_count += 1
                    elif action == 'updated':
                        updated_count += 1
            except Exception as e:
                error_count += 1
                _logger.exception("Pttavm Sipariş İşleme Hatası: %s", e)
        
        store.sudo().write({'last_sync': fields.Datetime.now()})
        return {'created': created_count, 'updated': updated_count, 'errors': error_count}

    @api.private
    def _process_order_json(self, order_json, store):
        """Gelen tekil JSON'u işler, PttavmOrder ve SaleOrder yaratır."""
        order_number = order_json.get('siparisNo')
        if not order_number:
            return 'skipped'

        # Pttavm uses SiparisNo as the primary identifier (there is no separated orderId root, or lineItemId might be used? lineItemId is inside siparisUrunler)
        existing_pttavm = self.search([('order_number', '=', order_number)], limit=1)
        
        # We will iterate through products to check if "siparisDurumu" is consistent, but let's grab the first product's status
        products = order_json.get('siparisUrunler', [])
        first_product_status = products[0].get('siparisDurumu') if products else ''
        
        if existing_pttavm:
            update_vals = {'order_status': first_product_status}
            cargo_tracking = order_json.get('kargoBarkod', '')
            if cargo_tracking and not existing_pttavm.cargo_tracking_number:
                update_vals['cargo_tracking_number'] = cargo_tracking
            existing_pttavm.write(update_vals)
            return 'updated'

        order_date_str = order_json.get('islemTarihi')
        order_date = False
        if order_date_str:
            try:
                # PttAVM API Türkiye saati döner — Odoo UTC saklar
                naive_dt = datetime.strptime(order_date_str[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                turkey_dt = IST.localize(naive_dt)
                order_date = turkey_dt.astimezone(pytz.UTC).replace(tzinfo=None)
            except Exception:
                _logger.warning("PttAVM tarih parse hatası: %s", order_date_str)
                order_date = fields.Datetime.now()
        else:
            order_date = fields.Datetime.now()
            
        customer_email = order_json.get('eposta', '')
        phone_number = order_json.get('telefonNo', '')

        # Fatura Tipi
        fatura_tipi = order_json.get('faturaTip') # Bireysel, Kurumsal
        is_commercial = True if fatura_tipi == 'Kurumsal' else False

        # FarkliAdres = 1 ise fatura ve teslimat farkli demektir
        
        shipment_addr = {
            'address': order_json.get('siparisAdresi'),
            'city': order_json.get('siparisIli'),
            'district': order_json.get('siparisIlce'),
            'ilKod': order_json.get('ilKod'),
            'ilceKod': order_json.get('ilceKod'),
        }
        
        billing_addr = {
            'address': order_json.get('faturaAdresi'),
            'city': order_json.get('faturaIli'),
            'district': order_json.get('faturaIlce'),
            'company_name': order_json.get('firmaUnvani') or order_json.get('tedarikciFirmaAdi'),
            'tax_office': order_json.get('vergiDaire'),
            'tax_number': order_json.get('vergiNo'),
            'tckn': order_json.get('tckn'),
            'farkliAdres': order_json.get('farkliAdres'),
            'isCommercial': is_commercial,
        }

        # Pttavm.Order kaydı oluştur
        vals = {
            'store_id': store.id,
            'order_id': order_number, # Mapping orderId to orderNumber
            'order_number': str(order_number),
            'order_date': order_date,
            'order_status': first_product_status,
            'payment_type': 1,
            'invoice_type': 2 if is_commercial else 1,
            'customer_id': str(order_json.get('musteriId', '')),
            'customer_name': f"{order_json.get('musteriAdi', '')} {order_json.get('musteriSoyadi', '')}".strip(),
            'customer_email': customer_email,
            'shipment_address': json.dumps(shipment_addr, ensure_ascii=False),
            'billing_address': json.dumps(billing_addr, ensure_ascii=False),
            'shipping_city': shipment_addr.get('city', ''),
            'shipping_district': shipment_addr.get('district', ''),
            'total_price': 0.0,
            'currency': 'TRY',
            'raw_data': json.dumps(order_json, ensure_ascii=False),
            'line_ids': [],
        }

        cargo_tracking = order_json.get('kargoBarkod', '')
        cargo_provider = ''

        total_order_price = 0.0

        for item in products:
            qty = item.get('toplamIslemAdedi', 1)
            price = item.get('kdvDahilToplamTutar', 0.0)
            
            line_vals = {
                'item_id': str(item.get('lineItemId', '')),
                'product_id': str(item.get('urunId', '')),
                'product_name': order_json.get('urunAdi') or item.get('urun'),
                'product_code': item.get('urunBarkod') or order_json.get('urunKodu'),
                'quantity': qty,
                # if qty > 1 given price usually includes total price in PttAvm, need to make unit price
                'sale_price': price / qty if qty else price,
                'status': item.get('siparisDurumu', ''),
                'cargo_tracking': cargo_tracking,
                'cargo_company': item.get('kargoKimden', ''),
            }
            vals['line_ids'].append((0, 0, line_vals))
            total_order_price += price
            
            if not cargo_provider and line_vals['cargo_company']:
                cargo_provider = line_vals['cargo_company']
            
        vals['total_price'] = total_order_price
        vals['cargo_tracking_number'] = cargo_tracking
        vals['cargo_provider'] = cargo_provider
        
        pttavm_order = self.create(vals)
        
        # kargo_yapilmasi_bekleniyor durumlari ise Odoo'ya aktar
        if first_product_status in ['kargo_yapilmasi_bekleniyor', 'havale_onayi_bekleniyor', 'onay_surecinde']:
            sale_order = self._create_odoo_sale_order(pttavm_order, store, shipment_addr, billing_addr, customer_email, phone_number, order_json)
            pttavm_order.write({'sale_order_id': sale_order.id})
            
            if store.auto_confirm and sale_order.state in ['draft', 'sent']:
                sale_order.action_confirm()
                
        return 'created'

    @api.private
    def _create_odoo_sale_order(self, p_order, store, ship_addr, bill_addr, customer_email, phone, raw_json):
        """Odoo Sale Order & Res Partner yaratır."""
        
        partner_env = self.env['res.partner']
        country_tr = self.env.ref('base.tr').id
        
        display_text = ship_addr.get('address') or ''
        
        customer_ref = ''
        if store.customer_prefix and p_order.customer_id:
            customer_ref = f"{store.customer_prefix}{p_order.customer_id}"

        final_email = '' if store.skip_customer_email else customer_email

        # Müşteri eşleştirme — önce ref ile, sonra name ile
        partner = False
        if customer_ref:
            partner = partner_env.search([('ref', '=', customer_ref)], limit=1)
        if not partner and phone:
            partner = partner_env.search([('phone', '=', phone)], limit=1)
        if not partner:
            partner_domain = [('name', '=ilike', p_order.customer_name)]
            partner = partner_env.search(partner_domain, limit=1)
        
        is_commercial = bill_addr.get('isCommercial')
        
        if not partner:
            partner = partner_env.create({
                'name': bill_addr.get('company_name') if is_commercial else p_order.customer_name,
                'email': final_email,
                'phone': phone,
                'street': display_text,
                'city': p_order.shipping_city,
                'country_id': country_tr,
                'ref': customer_ref,
                'company_type': 'company' if is_commercial else 'person'
            })
            
            if is_commercial:
                partner.write({
                    'vat': bill_addr.get('tax_number') or bill_addr.get('tckn'),
                    'is_subject_to_einvoice': raw_json.get('isInvoice', False)
                })
        
        invoice_partner = partner
        if bill_addr and bill_addr.get('farkliAdres') == 1:
            bill_display = bill_addr.get('address', '')
            invoice_partner = partner_env.create({
                'name': bill_addr.get('company_name') if is_commercial else f"{raw_json.get('faturaMusteriAdi','')} {raw_json.get('faturaMusteriSoyadi','')}".strip(),
                'type': 'invoice',
                'parent_id': partner.id,
                'street': bill_display,
                'city': bill_addr.get('city', ''),
                'vat': bill_addr.get('tax_number') or bill_addr.get('tckn'),
                'is_subject_to_einvoice': raw_json.get('isInvoice', False),
                'ref': customer_ref,
            })

        # Depo ayarını config'den al — Ayarlar > PttAVM > Depo Ayarları
        warehouse_id_str = self.env['ir.config_parameter'].sudo().get_param(
            'pttavm_integration.warehouse_id')
        warehouse_id = int(warehouse_id_str) if warehouse_id_str else False

        sale_vals = {
            'partner_id': partner.id,
            'partner_invoice_id': invoice_partner.id,
            'partner_shipping_id': partner.id,
            'pttavm_store_id': store.id,
            'pttavm_order_id': p_order.id,
            'client_order_ref': p_order.order_number,
            'date_order': p_order.order_date,
            'order_line': [],
        }
        if warehouse_id:
            sale_vals['warehouse_id'] = warehouse_id
        
        # Batch ürün arama (N+1 önleme)
        Product = self.env['product.product'].sudo()
        codes = [line.product_code for line in p_order.line_ids if line.product_code]
        product_map = {}
        if codes:
            products = Product.search([('barcode', 'in', codes)])
            for p in products:
                if p.barcode:
                    product_map[p.barcode] = p
            # nebim_barcode fallback
            missing = [c for c in codes if c not in product_map]
            if missing and 'nebim_barcode' in Product._fields:
                for bc in missing:
                    p = Product.search([('nebim_barcode', '=', bc)], limit=1)
                    if not p:
                        p = Product.search([('nebim_barcode', 'ilike', bc)], limit=1)
                    if p:
                        product_map[bc] = p
            # default_code fallback
            still_missing = [c for c in codes if c not in product_map]
            if still_missing:
                products = Product.search([('default_code', 'in', still_missing)])
                for p in products:
                    if p.default_code:
                        product_map[p.default_code] = p

        for line in p_order.line_ids:
            product = product_map.get(line.product_code)
            
            if not product:
                _logger.warning("Pttavm Urun Bulunamadi: %s", line.product_code)
                continue
                
            sale_vals['order_line'].append((0, 0, {
                'product_id': product.id,
                'product_uom_qty': line.quantity,
                'price_unit': line.sale_price,
                'pttavm_item_id': line.item_id,
            }))
            
        return self.env['sale.order'].create(sale_vals)
