
import json
import logging
import pytz

from datetime import datetime, timedelta, timezone

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from .trendyol_api import TrendyolAPI

_logger = logging.getLogger(__name__)

IST = pytz.timezone('Europe/Istanbul')

TRENDYOL_STATUS = [
    ('awaiting', 'Beklemede (Awaiting)'),
    ('created', 'Oluşturuldu (Created)'),
    ('picking', 'Toplanıyor (Picking)'),
    ('invoiced', 'Faturalandı (Invoiced)'),
    ('shipped', 'Kargoda (Shipped)'),
    ('cancelled', 'İptal (Cancelled)'),
    ('delivered', 'Teslim Edildi (Delivered)'),
    ('undelivered', 'Teslim Edilemedi (UnDelivered)'),
    ('returned', 'İade (Returned)'),
    ('unsupplied', 'Tedarik Edilemedi (UnSupplied)'),
]


class TrendyolOrder(models.Model):
    _name = 'trendyol.order'
    _description = 'Trendyol Sipariş'
    _order = 'order_date desc'
    _rec_name = 'name'

    # ─── Temel Bilgiler ──────────────────────────────────
    name = fields.Char(string='Referans', readonly=True, copy=False)
    trendyol_order_number = fields.Char(string='Trendyol Sipariş No', index=True, readonly=True)
    shipment_package_id = fields.Char(string='Paket ID', index=True, readonly=True)
    trendyol_status = fields.Selection(TRENDYOL_STATUS, string='Trendyol Durumu', readonly=True)
    order_date = fields.Datetime(string='Sipariş Tarihi', readonly=True)

    # ─── Mağaza ──────────────────────────────────────────
    store_id = fields.Many2one('trendyol.store', string='Mağaza', index=True, readonly=True)
    store_name = fields.Char(string='Mağaza Adı', related='store_id.name', store=True, readonly=True)
    seller_id = fields.Char(string='Seller ID', related='store_id.seller_id', store=True, readonly=True)

    # ─── Müşteri ─────────────────────────────────────────
    trendyol_customer_id = fields.Char(string='Trendyol Müşteri ID', readonly=True)
    customer_name = fields.Char(string='Müşteri Adı', readonly=True)
    customer_email = fields.Char(string='E-posta', readonly=True)

    # ─── Adres ───────────────────────────────────────────
    shipping_address = fields.Text(string='Teslimat Adresi', readonly=True)
    shipping_city = fields.Char(string='Şehir', readonly=True)
    shipping_district = fields.Char(string='İlçe', readonly=True)
    invoice_address = fields.Text(string='Fatura Adresi', readonly=True)

    # ─── Kargo ───────────────────────────────────────────
    cargo_provider = fields.Char(string='Kargo Firması', readonly=True)
    cargo_tracking_number = fields.Char(string='Kargo Takip No', readonly=True)
    cargo_tracking_link = fields.Char(string='Kargo Takip Linki', readonly=True)
    cargo_deci = fields.Float(string='Kargo Desi', readonly=True, digits=(5, 1),
                               help='Paketin volumetrik ağırlığı (desi)')

    # ─── Finansal ────────────────────────────────────────
    total_amount = fields.Float(string='Toplam Tutar', readonly=True)
    total_discount = fields.Float(string='Toplam İndirim', readonly=True)
    currency_code = fields.Char(string='Para Birimi', default='TRY', readonly=True)
    commercial = fields.Boolean(string='Kurumsal Fatura', readonly=True)
    tax_number = fields.Char(string='Vergi No', readonly=True)
    tax_office = fields.Char(string='Vergi Dairesi', readonly=True)
    company_name = fields.Char(string='Firma Adı', readonly=True)
    micro = fields.Boolean(string='Mikro İhracat', default=False, readonly=True,
                           help='Trendyol mikro ihracat siparişi')
    etgb_no = fields.Char(string='ETGB No', readonly=True,
                          help='Elektronik Ticaret Gümrük Beyannamesi numarası')
    etgb_date = fields.Datetime(string='ETGB Tarihi', readonly=True)

    # ─── Komisyon ────────────────────────────────────────
    total_commission = fields.Float(string='Toplam Komisyon', readonly=True, digits=(12, 2))
    commission_rate = fields.Float(string='Komisyon Oranı (%)', readonly=True, digits=(5, 2))
    net_amount = fields.Float(string='Net Tutar', readonly=True, digits=(12, 2),
                              help='Toplam Tutar - İndirim - Komisyon')

    # ─── Finansal Özet (Settlements API'den) ─────────────
    platform_fee = fields.Float(string='Platform Hizmet Bedeli', readonly=True, digits=(12, 2))
    shipping_cost = fields.Float(string='Gönderi Kargo Tutarı', readonly=True, digits=(12, 2))
    return_cargo_cost = fields.Float(string='İade Kargo Tutarı', readonly=True, digits=(12, 2))
    penalty_amount = fields.Float(string='Ceza Tutarı', readonly=True, digits=(12, 2))
    seller_revenue = fields.Float(string='Satıcı Hakediş', readonly=True, digits=(12, 2))
    final_net_amount = fields.Float(string='Net Sipariş Tutarı', readonly=True, digits=(12, 2),
                                    help='Hakediş - Platform Hizmet - Kargo - İade Kargo - Ceza')

    # ─── İlişkiler ───────────────────────────────────────
    sale_order_id = fields.Many2one('sale.order', string='Odoo Siparişi', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Müşteri', readonly=True)
    settlement_ids = fields.One2many('trendyol.settlement', 'order_id', string='Finansal İşlemler')

    # ─── Teknik ──────────────────────────────────────────
    raw_data = fields.Text(string='Ham JSON', readonly=True)
    line_ids = fields.One2many('trendyol.order.line', 'order_id', string='Ürün Kalemleri')
    state = fields.Selection([
        ('draft', 'Taslak'),
        ('synced', 'Senkronize'),
        ('error', 'Hata'),
    ], string='Durum', default='draft')
    error_message = fields.Text(string='Hata Mesajı')

    _unique_package = models.Constraint(
        'UNIQUE(shipment_package_id)',
        'Bu paket ID zaten kayıtlı!',
    )

    # ═══════════════════════════════════════════════════════
    # PAKET İŞLEME (Sync ve action metodları ayrı dosyalarda)
    # → trendyol_order_sync.py: Senkronizasyon, iptal, iade
    # → trendyol_order_actions.py: Toplu işlemler, retry, refresh
    # ═══════════════════════════════════════════════════════


    @api.private
    def _process_package(self, package_data, store):
        """Tek bir sipariş paketini işle."""
        package_id = str(package_data.get('id') or package_data.get('shipmentPackageId', ''))
        order_number = str(package_data.get('orderNumber', ''))
        status_raw = (package_data.get('status') or package_data.get('shipmentPackageStatus', '')).lower()

        # Mevcut kayıt var mı?
        existing = self.search([('shipment_package_id', '=', package_id)], limit=1)

        if existing:
            vals = {}
            if existing.trendyol_status != status_raw:
                vals['trendyol_status'] = status_raw
                # Ham veriyi sadece durum değiştiğinde güncelle
                vals['raw_data'] = json.dumps(package_data, ensure_ascii=False)
            if not existing.store_id:
                vals['store_id'] = store.id

            # Komisyon bilgisi güncelle (order-level + line-level)
            if store.process_commission:
                commission_vals = self._extract_commission(package_data)
                vals.update(commission_vals)
                # Line-level komisyon oranı güncelle (O(n) — dict lookup)
                line_map = {}
                for odoo_line in existing.line_ids:
                    if odoo_line.trendyol_line_id:
                        line_map[odoo_line.trendyol_line_id] = odoo_line
                    if odoo_line.barcode:
                        line_map[odoo_line.barcode] = odoo_line

                for api_line in package_data.get('lines', []):
                    rate = api_line.get('commission', 0)
                    if not rate:
                        continue
                    line_id_str = str(api_line.get('lineId') or api_line.get('id', ''))
                    barcode = api_line.get('barcode', '')
                    odoo_line = line_map.get(line_id_str) or line_map.get(barcode)
                    if odoo_line and odoo_line.commission_rate != rate:
                        odoo_line.write({'commission_rate': rate})

            if vals:
                existing.write(vals)
                if status_raw in ('cancelled', 'unsupplied') and existing.sale_order_id:
                    self._cancel_odoo_order(existing, store)
            return 'updated'

        # Yeni kayıt oluştur
        vals = self._prepare_order_vals(package_data, store)
        trendyol_order = self.create(vals)

        # Odoo sale.order oluştur
        try:
            sale_order = trendyol_order._create_sale_order(package_data, store)
            trendyol_order.write({
                'sale_order_id': sale_order.id,
                'partner_id': sale_order.partner_id.id,
                'state': 'synced',
            })
        except Exception as e:
            trendyol_order.write({
                'state': 'error',
                'error_message': str(e),
            })
            _logger.exception("Sale order oluşturma hatası [%s]: %s", store.name, e)

        return 'created'

    @api.private
    def _extract_commission(self, data):
        """Trendyol verisinden komisyon bilgilerini çıkar.

        Trendyol API'de line.commission = komisyon ORANI (%) dir, tutar değil!
        Hesaplama:
            1. İndirimli tutar = grossAmount - totalDiscount
            2. Komisyon tutarı = indirimli_tutar × komisyon_oranı / 100
            3. Net tutar = indirimli_tutar - komisyon_tutarı
        """
        gross_amount = (data.get('grossAmount')
                        or data.get('packageGrossAmount')
                        or data.get('totalPrice')
                        or data.get('packageTotalPrice', 0))
        total_discount = (data.get('totalDiscount')
                          or data.get('packageTotalDiscount', 0))
        net_after_discount = gross_amount - total_discount

        # Komisyon oranını lines'tan al (tüm kalemlerde genelde aynı)
        commission_rate = 0.0
        for line in data.get('lines', []):
            line_rate = line.get('commission', 0)
            if line_rate and line_rate > commission_rate:
                commission_rate = line_rate

        # Komisyon tutarı = indirimli tutar × oran / 100
        total_commission = round(net_after_discount * commission_rate / 100, 2)

        # Net tutar = indirimli tutar - komisyon
        net_amount = round(net_after_discount - total_commission, 2)

        return {
            'total_commission': total_commission,
            'commission_rate': commission_rate,
            'net_amount': net_amount,
        }

    @api.private
    def _prepare_order_vals(self, data, store):
        """Trendyol verisinden trendyol.order vals hazırla."""
        order_number = str(data.get('orderNumber', ''))
        package_id = str(data.get('id') or data.get('shipmentPackageId', ''))
        status = (data.get('status') or data.get('shipmentPackageStatus', '')).lower()

        # Tarih dönüşümü (timestamp ms → UTC datetime)
        order_date_ts = data.get('orderDate', 0)
        order_date = datetime.fromtimestamp(order_date_ts / 1000, tz=timezone.utc).replace(tzinfo=None) if order_date_ts else fields.Datetime.now()

        # Müşteri bilgileri
        customer_name = f"{data.get('customerFirstName', '')} {data.get('customerLastName', '')}".strip()

        # Adres bilgileri
        ship_addr = data.get('shipmentAddress', {}) or {}
        inv_addr = data.get('invoiceAddress', {}) or {}

        shipping_text = ship_addr.get('fullAddress') or ship_addr.get('address1', '')
        invoice_text = inv_addr.get('fullAddress') or inv_addr.get('address1', '')

        # Kurumsal bilgi
        commercial = data.get('commercial', False)

        # ── Referans formatı ──
        if store.order_ref_type == 'package_id':
            ref_name = f"TY-{package_id}"
        else:
            ref_name = f"TY-{order_number}"

        # Kalemler
        lines = data.get('lines', [])
        line_vals = []
        for line in lines:
            lv = {
                'trendyol_line_id': str(line.get('lineId') or line.get('id', '')),
                'barcode': line.get('barcode', ''),
                'merchant_sku': line.get('merchantSku', ''),
                'stock_code': line.get('stockCode', ''),
                'product_name': line.get('productName', ''),
                'quantity': line.get('quantity', 1),
                'unit_price': (line.get('price')
                               or line.get('amount')
                               or line.get('lineUnitPrice')
                               or line.get('lineGrossAmount', 0)),
                'discount': (line.get('discount')
                             or line.get('lineTotalDiscount')
                             or line.get('lineSellerDiscount', 0)),
                'vat_rate': line.get('vatRate', 0),
                'product_size': line.get('productSize', ''),
                'product_color': line.get('productColor', ''),
            }
            # Komisyon oranı (API'den gelen değer ORAN'dır, tutar değil)
            if store.process_commission:
                lv['commission_rate'] = line.get('commission', 0)
            line_vals.append((0, 0, lv))

        vals = {
            'name': ref_name,
            'trendyol_order_number': order_number,
            'shipment_package_id': package_id,
            'trendyol_status': status if status in dict(TRENDYOL_STATUS) else 'created',
            'order_date': order_date,
            'store_id': store.id,
            'trendyol_customer_id': str(data.get('customerId', '')),
            'customer_name': customer_name,
            'customer_email': data.get('customerEmail', ''),
            'shipping_address': shipping_text,
            'shipping_city': ship_addr.get('city', ''),
            'shipping_district': ship_addr.get('district', ''),
            'invoice_address': invoice_text,
            'cargo_provider': data.get('cargoProviderName', ''),
            'cargo_tracking_number': str(data.get('cargoTrackingNumber', '')),
            'cargo_tracking_link': data.get('cargoTrackingLink', ''),
            'cargo_deci': data.get('cargoDeci') or data.get('deci', 0) or 1,
            'total_amount': (data.get('grossAmount')
                            or data.get('packageGrossAmount')
                            or data.get('totalPrice')
                            or data.get('packageTotalPrice', 0)),
            'total_discount': (data.get('totalDiscount')
                               or data.get('packageTotalDiscount', 0)),
            'currency_code': data.get('currencyCode', 'TRY'),
            'commercial': commercial,
            'tax_number': inv_addr.get('taxNumber', '') if commercial else '',
            'tax_office': inv_addr.get('taxOffice', '') if commercial else '',
            'company_name': inv_addr.get('company', '') if commercial else '',
            'raw_data': json.dumps(data, ensure_ascii=False),
            'line_ids': line_vals,
            'micro': data.get('micro', False),
            'etgb_no': data.get('etgbNo', ''),
        }

        # ETGB tarihi (timestamp ms)
        etgb_date_ts = data.get('etgbDate', 0)
        if etgb_date_ts:
            vals['etgb_date'] = datetime.fromtimestamp(etgb_date_ts / 1000, tz=timezone.utc).replace(tzinfo=None)

        # Komisyon bilgisi
        if store.process_commission:
            vals.update(self._extract_commission(data))

        return vals

    @api.private
    def _create_sale_order(self, package_data, store):
        """Trendyol siparişinden Odoo sale.order oluştur."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()

        # Müşteri bul/oluştur (Adresleri ayrıştırılmış olarak döner)
        partner_dict = self._find_or_create_partner(package_data, store)

        # Sale order oluştur
        so_vals = {
            'partner_id': partner_dict['partner_id'],
            'partner_invoice_id': partner_dict.get('partner_invoice_id', partner_dict['partner_id']),
            'partner_shipping_id': partner_dict.get('partner_shipping_id', partner_dict['partner_id']),
            'origin': self.name,
            'client_order_ref': self.trendyol_order_number,
            'date_order': self.order_date,
            'trendyol_order_id': self.id,
            'trendyol_store_id': store.id,
        }

        # Depo — global ayardan al
        warehouse_id = int(ICP.get_param('trendyol_integration.warehouse_id', 0))
        if warehouse_id and 'warehouse_id' in self.env['sale.order']._fields:
            so_vals['warehouse_id'] = warehouse_id

        # Ürünleri toplu bul (N+1 → 2 sorgu)
        api_lines = package_data.get('lines', [])
        product_map = self._batch_find_products(api_lines)

        order_lines = []
        for line in api_lines:
            bc = line.get('barcode', '').strip()
            sku = line.get('merchantSku', '').strip()
            product = product_map.get(bc) or product_map.get(sku)
            if not product:
                # Batch'te bulunamadı, tek tek dene (nebim_barcode fallback)
                product = self._find_product_by_barcode(bc, sku)

            price = (line.get('price')
                     or line.get('amount')
                     or line.get('lineUnitPrice')
                     or line.get('lineGrossAmount', 0))
            qty = line.get('quantity', 1)
            unit_price = price / qty if qty else price

            ol_vals = {
                'name': line.get('productName', 'Bilinmeyen Ürün'),
                'product_uom_qty': qty,
                'price_unit': unit_price,
            }
            if product:
                ol_vals['product_id'] = product.id

            order_lines.append((0, 0, ol_vals))

        so_vals['order_line'] = order_lines

        sale_order = self.env['sale.order'].sudo().create(so_vals)

        # Otomatik onayla — mağaza bazında
        if store.auto_confirm:
            try:
                sale_order.action_confirm()
            except Exception as e:
                _logger.warning("Sipariş onaylama hatası %s: %s", sale_order.name, e)

        _logger.info("Odoo sipariş oluşturuldu [%s]: %s → %s", store.name, self.name, sale_order.name)
        return sale_order

    @api.private
    def _find_or_create_partner(self, data, store):
        """Müşteri bul veya oluştur. Hem fatura hem teslimat adresini yönetir."""
        Partner = self.env['res.partner'].sudo()
        customer_id = str(data.get('customerId', ''))
        prefix = store.customer_prefix or ''
        customer_ref = f"{prefix}{customer_id}"

        ship_addr = data.get('shipmentAddress', {}) or {}
        inv_addr = data.get('invoiceAddress', {}) or {}
        email = data.get('customerEmail', '')
        commercial = data.get('commercial', False)

        # Müşteri Adı
        customer_name = self._extract_customer_name(data, inv_addr)

        # Fatura / teslimat adres metinleri
        inv_full_text = inv_addr.get('fullAddress') or inv_addr.get('address1') or ''
        ship_full_text = ship_addr.get('fullAddress') or ship_addr.get('address1') or ''

        # 1- Ana müşteri bul veya oluştur
        main_partner = self._find_existing_partner(Partner, customer_ref, customer_id, email, store)

        if not main_partner:
            main_partner = self._create_main_partner(
                Partner, customer_ref, customer_id, customer_name,
                email, commercial, inv_addr, ship_addr,
                inv_full_text, ship_full_text, store)
        else:
            self._update_existing_partner(main_partner, customer_name, commercial, inv_addr, inv_full_text, ship_full_text)

        # 2- Teslimat ve fatura child contact'ları
        result = {
            'partner_id': main_partner.id,
            'partner_invoice_id': main_partner.id,
            'partner_shipping_id': main_partner.id,
        }
        result.update(self._ensure_child_addresses(
            Partner, main_partner, ship_addr, inv_addr,
            ship_full_text, inv_full_text, commercial))

        return result

    @api.private
    def _extract_customer_name(self, data, inv_addr):
        """Müşteri adını fatura adresinden veya root'tan çıkar."""
        inv_fname = inv_addr.get('firstName', '').strip()
        inv_lname = inv_addr.get('lastName', '').strip()
        if inv_fname or inv_lname:
            return f"{inv_fname} {inv_lname}".strip()
        return f"{data.get('customerFirstName', '')} {data.get('customerLastName', '')}".strip()

    @api.private
    def _resolve_country_state(self, country_code, city):
        """Ülke ve il çözümle."""
        code = (country_code or 'TR').upper()
        country = self.env['res.country'].search([('code', '=', code)], limit=1)
        state_id = False
        if country and city and country.code == 'TR':
            state = self.env['res.country.state'].search(
                [('country_id', '=', country.id), ('name', 'ilike', city)], limit=1)
            if state:
                state_id = state.id
        return country, state_id

    @api.private
    def _find_existing_partner(self, Partner, customer_ref, customer_id, email, store):
        """Mevcut müşteriyi ref, comment veya email ile bul."""
        partner = Partner.search([('ref', '=', customer_ref)], limit=1)
        if not partner:
            partner = Partner.search([('comment', 'ilike', f'trendyol_id:{customer_id}')], limit=1)
            if partner and not partner.ref:
                partner.write({'ref': customer_ref})
        if not partner and email and not store.skip_customer_email:
            partner = Partner.search([('email', '=', email)], limit=1)
            if partner and not partner.ref:
                partner.write({'ref': customer_ref})
        return partner

    def _create_main_partner(self, Partner, customer_ref, customer_id, customer_name,
                              email, commercial, inv_addr, ship_addr,
                              inv_full_text, ship_full_text, store):
        """Yeni ana müşteri oluştur."""
        c_country, c_state_id = self._resolve_country_state(
            inv_addr.get('countryCode') or ship_addr.get('countryCode'),
            inv_addr.get('city') or ship_addr.get('city', ''))

        vals = {
            'name': customer_name or 'Trendyol Müşteri',
            'ref': customer_ref,
            'phone': inv_addr.get('phone') or ship_addr.get('phone') or '',
            'street': inv_full_text[:128] if inv_full_text else ship_full_text[:128],
            'city': inv_addr.get('city') or ship_addr.get('city', ''),
            'comment': f'trendyol_id:{customer_id}',
            'customer_rank': 1,
        }
        if not store.skip_customer_email and email:
            vals['email'] = email
        if commercial:
            vals['company_type'] = 'company'
            vals['name'] = inv_addr.get('company', '') or customer_name
            vals['vat'] = inv_addr.get('taxNumber', '')
        if c_country:
            vals['country_id'] = c_country.id
        if c_state_id:
            vals['state_id'] = c_state_id

        return Partner.create(vals)

    def _update_existing_partner(self, partner, customer_name, commercial, inv_addr, inv_full_text, ship_full_text):
        """Mevcut müşteriyi güncelle."""
        upd_vals = {}
        if commercial and inv_addr.get('company'):
            upd_vals['name'] = inv_addr.get('company')
        elif customer_name and partner.name != customer_name:
            upd_vals['name'] = customer_name

        new_street = inv_full_text[:128] if inv_full_text else ship_full_text[:128]
        if new_street and partner.street != new_street:
            upd_vals['street'] = new_street

        if upd_vals:
            partner.write(upd_vals)

    def _ensure_child_addresses(self, Partner, main_partner, ship_addr, inv_addr,
                                 ship_full_text, inv_full_text, commercial):
        """Gerekirse teslimat ve fatura alt adresleri oluştur."""
        result = {}

        # Teslimat adresi farklıysa
        if ship_full_text and ship_full_text != main_partner.street and ship_full_text != inv_full_text:
            shipping_partner = Partner.search([
                ('parent_id', '=', main_partner.id),
                ('type', '=', 'delivery'),
                ('street', 'ilike', ship_full_text[:30])
            ], limit=1)

            if not shipping_partner:
                s_country, s_state_id = self._resolve_country_state(
                    ship_addr.get('countryCode'), ship_addr.get('city', ''))
                shipping_partner = Partner.create({
                    'parent_id': main_partner.id,
                    'type': 'delivery',
                    'name': f"{ship_addr.get('firstName', '')} {ship_addr.get('lastName', '')}".strip() or main_partner.name,
                    'phone': ship_addr.get('phone') or main_partner.phone,
                    'street': ship_full_text[:128],
                    'city': ship_addr.get('city', ''),
                    'country_id': s_country.id if s_country else False,
                    'state_id': s_state_id if s_state_id else False,
                })
            result['partner_shipping_id'] = shipping_partner.id

        # Fatura adresi farklıysa (kurumsal)
        if commercial and inv_full_text and inv_full_text != main_partner.street:
            invoice_partner = Partner.search([
                ('parent_id', '=', main_partner.id),
                ('type', '=', 'invoice'),
                ('street', 'ilike', inv_full_text[:30])
            ], limit=1)

            if not invoice_partner:
                i_country, i_state_id = self._resolve_country_state(
                    inv_addr.get('countryCode'), inv_addr.get('city', ''))
                invoice_partner = Partner.create({
                    'parent_id': main_partner.id,
                    'type': 'invoice',
                    'name': inv_addr.get('company') or main_partner.name,
                    'street': inv_full_text[:128],
                    'city': inv_addr.get('city', ''),
                    'country_id': i_country.id if i_country else False,
                    'state_id': i_state_id if i_state_id else False,
                    'vat': inv_addr.get('taxNumber', ''),
                })
            result['partner_invoice_id'] = invoice_partner.id

        return result

    @api.private
    def _find_product_by_barcode(self, barcode, merchant_sku=''):
        """Barkod ile ürün bul. Bulunamazsa merchantSku dene.

        Arama sırası:
        1. barcode alanı (exact match)
        2. nebim_barcode alanı (exact match, sonra ilike)
        3. default_code (merchantSku)
        """
        Product = self.env['product.product'].sudo()

        if barcode:
            product = Product.search([('barcode', '=', barcode)], limit=1)
            if product:
                return product
            # nebim_barcode desteği — önce exact, sonra ilike
            if 'nebim_barcode' in Product._fields:
                product = Product.search([('nebim_barcode', '=', barcode)], limit=1)
                if not product:
                    product = Product.search([('nebim_barcode', 'ilike', barcode)], limit=1)
                if product:
                    return product

        if merchant_sku:
            product = Product.search([('default_code', '=', merchant_sku)], limit=1)
            if product:
                return product

        _logger.warning("Ürün bulunamadı: barcode=%s, sku=%s", barcode, merchant_sku)
        return False

    @api.private
    def _batch_find_products(self, lines):
        """Birden fazla kalem için ürünleri toplu olarak bul.

        Tek sorguda tüm barkod ve SKU'ları arar, N+1 sorgu sorununu çözer.
        Returns: dict {barcode_or_sku: product_record}
        """
        Product = self.env['product.product'].sudo()
        barcodes = [l.get('barcode', '').strip() for l in lines if l.get('barcode', '').strip()]
        skus = [l.get('merchantSku', '').strip() for l in lines if l.get('merchantSku', '').strip()]

        product_map = {}

        if barcodes:
            products = Product.search([('barcode', 'in', barcodes)])
            for p in products:
                if p.barcode:
                    product_map[p.barcode] = p

            # nebim_barcode fallback — batch
            missing_barcodes = [b for b in barcodes if b not in product_map]
            if missing_barcodes and 'nebim_barcode' in Product._fields:
                for bc in missing_barcodes:
                    product = Product.search([('nebim_barcode', '=', bc)], limit=1)
                    if not product:
                        product = Product.search([('nebim_barcode', 'ilike', bc)], limit=1)
                    if product:
                        product_map[bc] = product

        # Henüz bulunamayanlar için SKU ile dene
        missing_skus = [s for s in skus if s not in product_map]
        if missing_skus:
            products = Product.search([('default_code', 'in', missing_skus)])
            for p in products:
                if p.default_code:
                    product_map[p.default_code] = p

        return product_map

    # ═══════════════════════════════════════════════════════
    # Aşağıdaki metodlar _inherit ile ayrı dosyalarda tanımlı:
    # → trendyol_order_sync.py: sync_orders_from_trendyol, sync_orders_for_store,
    #   _sync_cancelled_orders, _sync_returned_orders, _cancel_odoo_order,
    #   cron_sync_trendyol_orders
    # → trendyol_order_actions.py: action_retry_sync, action_refresh_from_trendyol,
    #   action_delete_error_orders, action_mark_synced, action_retry_all_errors,
    #   _notify
    # ═══════════════════════════════════════════════════════


class TrendyolOrderLine(models.Model):
    _name = 'trendyol.order.line'
    _description = 'Trendyol Sipariş Kalemi'

    order_id = fields.Many2one('trendyol.order', string='Sipariş', ondelete='cascade')
    trendyol_line_id = fields.Char(string='Line ID')
    barcode = fields.Char(string='Barkod')
    merchant_sku = fields.Char(string='Merchant SKU')
    stock_code = fields.Char(string='Stok Kodu')
    product_name = fields.Char(string='Ürün Adı')
    quantity = fields.Integer(string='Adet', default=1)
    unit_price = fields.Float(string='Birim Fiyat')
    discount = fields.Float(string='İndirim')
    vat_rate = fields.Float(string='KDV Oranı')
    product_size = fields.Char(string='Beden')
    product_color = fields.Char(string='Renk')
    commission_rate = fields.Float(string='Komisyon Oranı (%)', digits=(5, 2))
    commission_amount = fields.Float(string='Komisyon Tutarı', digits=(12, 2),
                                     compute='_compute_commission_amount', store=True)
    product_id = fields.Many2one('product.product', string='Odoo Ürünü', compute='_compute_product', store=True)

    @api.depends('unit_price', 'discount', 'commission_rate')
    def _compute_commission_amount(self):
        """Komisyon tutarı = (birim fiyat - indirim) × komisyon oranı / 100"""
        for line in self:
            net_price = (line.unit_price or 0) - (line.discount or 0)
            line.commission_amount = round(net_price * (line.commission_rate or 0) / 100, 2)

    @api.depends('barcode', 'merchant_sku')
    def _compute_product(self):
        Product = self.env['product.product'].sudo()

        # Batch: tüm barkod ve SKU'ları topla
        barcodes = [l.barcode for l in self if l.barcode]
        skus = [l.merchant_sku for l in self if l.merchant_sku]

        bc_map = {}
        if barcodes:
            for p in Product.search([('barcode', 'in', barcodes)]):
                if p.barcode:
                    bc_map[p.barcode] = p

        sku_map = {}
        if skus:
            for p in Product.search([('default_code', 'in', skus)]):
                if p.default_code:
                    sku_map[p.default_code] = p

        for line in self:
            product = bc_map.get(line.barcode) or sku_map.get(line.merchant_sku) or False
            line.product_id = product


class TrendyolSyncLog(models.Model):
    _name = 'trendyol.sync.log'
    _description = 'Trendyol Senkronizasyon Logu'
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(string='Referans', default=lambda self: _('Yeni'), readonly=True, copy=False)
    store_id = fields.Many2one('trendyol.store', string='Mağaza', readonly=True)
    sync_type = fields.Selection([
        ('order', 'Sipariş Senkronizasyonu'),
        ('cancel', 'İptal Senkronizasyonu'),
        ('manual', 'Manuel İşlem'),
    ], string='Tür', default='order')
    state = fields.Selection([
        ('running', 'Çalışıyor'),
        ('done', 'Tamamlandı'),
        ('error', 'Hata'),
    ], string='Durum', default='running')
    start_date = fields.Datetime(string='Başlangıç')
    end_date = fields.Datetime(string='Bitiş')
    records_processed = fields.Integer(string='İşlenen')
    records_created = fields.Integer(string='Oluşturulan')
    records_updated = fields.Integer(string='Güncellenen')
    records_failed = fields.Integer(string='Başarısız')
    log_details = fields.Text(string='İşlem Detayları')
    error_details = fields.Text(string='Hata Detayları')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Yeni')) == _('Yeni'):
                vals['name'] = self.env['ir.sequence'].next_by_code('trendyol.sync.log') or _('Yeni')
        return super().create(vals_list)
