from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    nebim_customer_sent = fields.Boolean(string='Nebim Cari Açıldı', default=False, readonly=True)
    nebim_customer_code = fields.Char(string='Nebim Cari Kodu', readonly=True)
    nebim_address_id = fields.Char(string='Nebim Adres ID', readonly=True)
    nebim_customer_request = fields.Text(string='Nebim Cari İstek', readonly=True)
    nebim_customer_response = fields.Text(string='Nebim Cari Cevabı', readonly=True)
    nebim_order_sent = fields.Boolean(string='Nebim Sipariş Aktarıldı', default=False)
    nebim_order_response = fields.Text(string='Nebim Sipariş Cevabı', readonly=True)
    nebim_order_request = fields.Text(string='Nebim Sipariş İstek', readonly=True)
    nebim_export_file_number = fields.Char(string='Nebim ExportFileNumber', readonly=True)
    nebim_header_id = fields.Char(string='Nebim HeaderID', readonly=True,
                                  help='Nebim sipariş yanıtından alınan benzersiz HeaderID (GUID). Silme işleminde kullanılır.')

    # ─── Pazaryeri Bilgileri (Computed) ────────────────────
    marketplace_name = fields.Char(
        string='Pazaryeri', compute='_compute_marketplace_info',
        readonly=True,
    )
    marketplace_order_number = fields.Char(
        string='Pazaryeri Sipariş No', compute='_compute_marketplace_info',
        readonly=True,
    )
    marketplace_store_name = fields.Char(
        string='Mağaza Adı', compute='_compute_marketplace_info',
        readonly=True,
    )
    marketplace_seller_id = fields.Char(
        string='Seller ID', compute='_compute_marketplace_info',
        readonly=True,
    )
    marketplace_status_display = fields.Char(
        string='Pazaryeri Durumu', compute='_compute_marketplace_status',
        readonly=True,
    )
    marketplace_status_category = fields.Selection([
        ('success', 'Teslim/Kargo'),
        ('warning', 'Beklemede'),
        ('danger', 'İptal/İade'),
        ('info', 'Diğer'),
    ], string='Durum Kategorisi', compute='_compute_marketplace_status',
        readonly=True,
    )
    picking_batch_names = fields.Char(
        string='Rota', readonly=True, copy=False,
        help='Picking batch ataması sırasında otomatik yazılır. '
             'Kalıcı alan — faturalama sonrası silinmez.',
    )

    _MP_FIELDS = [
        ('trendyol_order_id', 'Trendyol'),
        ('hb_order_id', 'Hepsiburada'),
        ('amazon_order_id', 'Amazon'),
        ('pazarama_order_id', 'Pazarama'),
        ('n11_order_id', 'N11'),
        ('flo_order_id', 'Flo'),
        ('idefix_order_id', 'Idefix'),
        ('pttavm_order_id', 'PttAvm'),
        ('shopify_order_id', 'Shopify'),
    ]

    # store_field → sale.order'daki Many2one alan, seller_field → store modeldeki seller alanı
    _MP_STORE_FIELDS = [
        ('trendyol_store_id', 'seller_id', 'Trendyol'),
        ('n11_store_id', None, 'N11'),
        ('amazon_store_id', None, 'Amazon'),
        ('pazarama_store_id', None, 'Pazarama'),
        ('flo_store_id', 'flo_seller_id', 'Flo'),
        ('idefix_store_id', None, 'Idefix'),
        ('pttavm_store_id', None, 'PttAvm'),
    ]

    @api.depends('client_order_ref')
    def _compute_marketplace_info(self):
        for order in self:
            mp_name = False
            store_name = False
            seller_id = False

            for field, name in self._MP_FIELDS:
                if field in order._fields and order[field]:
                    mp_name = name
                    break

            # Mağaza adı ve seller ID — sale.order üzerindeki store Many2one'dan
            for store_field, seller_field, mp in self._MP_STORE_FIELDS:
                if store_field in order._fields and order[store_field]:
                    store = order[store_field]
                    store_name = store.name or ''
                    if seller_field and hasattr(store, seller_field):
                        seller_id = getattr(store, seller_field, '') or ''
                    break

            # Shopify özel: sale.order → shopify_order_id → store_id
            if not store_name and 'shopify_order_id' in order._fields and order.shopify_order_id:
                shopify_order = order.shopify_order_id
                if hasattr(shopify_order, 'store_id') and shopify_order.store_id:
                    store_name = shopify_order.store_id.name or ''

            # Hepsiburada özel: hb_store_id Char alanı merchant_id tutar
            # hepsiburada.store modelinden mağaza adını çek
            if not store_name and 'hb_store_id' in order._fields and order.hb_store_id:
                if 'hepsiburada.store' in order.env:
                    hb_store = order.env['hepsiburada.store'].sudo().search(
                        [('merchant_id', '=', order.hb_store_id)], limit=1)
                    if hb_store:
                        store_name = hb_store.name
                        seller_id = order.hb_store_id  # Merchant ID → seller_id
                    else:
                        store_name = order.hb_store_id  # Fallback: merchant ID göster

            order.marketplace_name = mp_name
            order.marketplace_order_number = order.client_order_ref if mp_name else False
            order.marketplace_store_name = store_name
            order.marketplace_seller_id = seller_id

    # Trendyol status değerlerinden Türkçe karşılıklar
    _TY_STATUS_TR = {
        'awaiting': 'Beklemede',
        'created': 'Oluşturuldu',
        'picking': 'Toplanıyor',
        'invoiced': 'Faturalandi',
        'shipped': 'Kargoda',
        'cancelled': 'İptal',
        'delivered': 'Teslim Edildi',
        'undelivered': 'Teslim Edilemedi',
        'returned': 'İade',
        'unsupplied': 'Tedarik Edilemedi',
    }

    # İptal/İade sayılan Trendyol statüleri
    _TY_CANCEL = {'cancelled', 'unsupplied', 'returned', 'undelivered'}
    _TY_SUCCESS = {'delivered', 'shipped'}
    _TY_WARNING = {'created', 'picking', 'awaiting'}

    @api.depends('client_order_ref')
    def _compute_marketplace_status(self):
        for order in self:
            display = ''
            category = 'info'

            # Trendyol
            if 'trendyol_order_id' in order._fields and order.trendyol_order_id:
                ty = order.trendyol_order_id
                status_val = ty.trendyol_status or ''
                display = self._TY_STATUS_TR.get(status_val, status_val)
                if status_val in self._TY_CANCEL:
                    category = 'danger'
                elif status_val in self._TY_SUCCESS:
                    category = 'success'
                elif status_val in self._TY_WARNING:
                    category = 'warning'

            # Hepsiburada
            elif 'hb_order_id' in order._fields and order.hb_order_id:
                hb = order.hb_order_id
                display = hb.status_display if hasattr(hb, 'status_display') and hb.status_display else (hb.status or '')
                status_raw = (hb.status or '').lower()
                if status_raw in ('cancelled', 'undelivered'):
                    category = 'danger'
                elif status_raw in ('delivered',):
                    category = 'success'
                elif status_raw in ('shipped',):
                    category = 'success'
                else:
                    category = 'warning'

            # N11
            elif 'n11_order_id' in order._fields and order.n11_order_id:
                n11 = order.n11_order_id
                display = n11.order_status_display if hasattr(n11, 'order_status_display') and n11.order_status_display else (n11.order_status or '')
                status_raw = (n11.order_status or '').lower()
                if 'iptal' in status_raw or 'cancel' in status_raw or 'iade' in status_raw:
                    category = 'danger'
                elif 'teslim' in status_raw or 'deliver' in status_raw:
                    category = 'success'
                elif 'kargo' in status_raw or 'ship' in status_raw:
                    category = 'success'
                else:
                    category = 'warning'

            # Pazarama
            elif 'pazarama_order_id' in order._fields and order.pazarama_order_id:
                pz = order.pazarama_order_id
                display = pz.order_status_display if hasattr(pz, 'order_status_display') and pz.order_status_display else str(pz.order_status or '')
                pz_status = pz.order_status or 0
                if pz_status in (6, 13, 14, 18):
                    category = 'danger'
                elif pz_status == 11:
                    category = 'success'
                elif pz_status in (5,):
                    category = 'success'
                else:
                    category = 'warning'

            # İdefix
            elif 'idefix_order_id' in order._fields and order.idefix_order_id:
                ix = order.idefix_order_id
                display = ix.order_status_display if hasattr(ix, 'order_status_display') and ix.order_status_display else (ix.order_status or '')
                status_raw = (ix.order_status or '').lower()
                if status_raw in ('cancelled', 'canceled', 'refunded', 'returned'):
                    category = 'danger'
                elif status_raw in ('delivered',):
                    category = 'success'
                elif status_raw in ('shipped',):
                    category = 'success'
                else:
                    category = 'warning'

            # PttAvm
            elif 'pttavm_order_id' in order._fields and order.pttavm_order_id:
                pt = order.pttavm_order_id
                display = pt.order_status_display if hasattr(pt, 'order_status_display') and pt.order_status_display else (pt.order_status or '')
                status_raw = (pt.order_status or '').lower()
                if 'iptal' in status_raw or 'iade' in status_raw:
                    category = 'danger'
                elif 'teslim' in status_raw:
                    category = 'success'
                elif 'kargo' in status_raw:
                    category = 'success'
                else:
                    category = 'warning'

            # Amazon
            elif 'amazon_order_id' in order._fields and order.amazon_order_id:
                display = 'Amazon'
                category = 'info'

            # Shopify
            elif 'shopify_order_id' in order._fields and order.shopify_order_id:
                display = 'Shopify'
                category = 'info'

            order.marketplace_status_display = display
            order.marketplace_status_category = category

    def action_reprint_cargo_label(self):
        """Siparişin kargo etiketini yeniden yazdır (popup pencerede PDF aç)."""
        self.ensure_one()

        # Siparişe ait picking'i bul (outgoing, done öncelikli)
        picking = self.env['stock.picking'].sudo().search([
            ('origin', '=', self.name),
            ('picking_type_code', '=', 'outgoing'),
        ], order='state desc, id desc', limit=1)

        if not picking:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Uyarı',
                    'message': f'{self.name} siparişine ait sevkiyat bulunamadı.',
                    'type': 'warning',
                    'sticky': False,
                },
            }

        # Tarayıcıda JS ile render + window.print() (packing.js ile birebir aynı)
        return {
            'type': 'ir.actions.client',
            'tag': 'cargo_label_reprint',
            'name': 'Kargo Etiketi',
            'params': {
                'picking_id': picking.id,
            },
        }

    def action_view_earchive_invoice(self):
        """Siparişin e-arşiv faturasını popup pencerede gösterir.

        usp_Invoice_EArchieveURL stored procedure'ü:
            @DocumentNumber → InvoiceURL, EInvoiceNumber, InvoiceDate
        """
        self.ensure_one()

        doc_number = self.client_order_ref or self.name
        if not doc_number:
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'Hata',
                               'message': 'Sipariş referansı (DocumentNumber) bulunamadı.',
                               'type': 'warning'}}

        try:
            connector = self.env['odoougurlar.nebim.connector'].sudo()
            params = [{'Name': 'DocumentNumber', 'Value': doc_number}]
            result = connector.run_proc('usp_Invoice_EArchieveURL', params)

            if not result or (isinstance(result, list) and len(result) == 0):
                return {'type': 'ir.actions.client', 'tag': 'display_notification',
                        'params': {'title': 'Bilgi',
                                   'message': f'"{doc_number}" için e-arşiv fatura bulunamadı.',
                                   'type': 'warning'}}

            row = result[0] if isinstance(result, list) else result
            invoice_url = row.get('InvoiceURL', '') if isinstance(row, dict) else ''

            if not invoice_url:
                return {'type': 'ir.actions.client', 'tag': 'display_notification',
                        'params': {'title': 'Bilgi',
                                   'message': f'Fatura URL\'si henüz oluşmamış. (EInvoice: {row.get("EInvoiceNumber", "")})',
                                   'type': 'warning'}}

            return {
                'type': 'ir.actions.client',
                'tag': 'earchive_viewer',
                'name': 'E-Arşiv Fatura',
                'params': {
                    'invoice_url': invoice_url,
                    'einvoice_number': row.get('EInvoiceNumber', '') if isinstance(row, dict) else '',
                },
            }

        except Exception as e:
            _logger.error("E-Arşiv fatura URL hatası (SO=%s, DocNum=%s): %s",
                          self.name, doc_number, e)
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'Hata',
                               'message': f'E-arşiv fatura sorgulanırken hata: {str(e)}',
                               'type': 'danger'}}

    def action_reset_nebim(self):
        """Nebim senkronizasyon bayraklarını sıfırla.
        
        Kullanıcı siparişteki ürünleri/fiyatları değiştirdiğinde ve
        Nebim'deki eski siparişi sildiğinde bu butona basarak
        Nebim sync'i sıfırlar. Bir sonraki 'Paketle ve Faturala'da
        güncel ürünlerle sipariş + fatura tekrar gönderilir.
        """
        self.ensure_one()
        
        # Sipariş bayraklarını sıfırla
        self.write({
            'nebim_order_sent': False,
            'nebim_order_response': '',
            'nebim_export_file_number': '',
        })
        
        # OrderLineID'leri temizle (eski Nebim siparişine referans)
        for line in self.order_line:
            if line.nebim_order_line_id:
                line.write({'nebim_order_line_id': False})
        
        # Eski faturaları iptal et — yeni fatura güncel ürünlerle oluşsun
        cancelled_count = 0
        deleted_count = 0
        for inv in self.invoice_ids:
            try:
                if inv.state == 'draft':
                    # Draft faturayı sil
                    inv.unlink()
                    deleted_count += 1
                elif inv.state == 'posted':
                    # Posted faturayı iptal et (credit note olmadan)
                    inv.button_draft()
                    inv.button_cancel()
                    cancelled_count += 1
            except Exception as e:
                _logger.warning("Fatura iptal/silme hatası (%s): %s", inv.name, e)
        
        _logger.info(
            "Nebim sıfırlandı: %s — %d fatura iptal, %d taslak silindi",
            self.name, cancelled_count, deleted_count
        )
        
        # ── 3. Güncel siparişi hemen Nebim'e gönder ──
        order_msg = ''
        try:
            # Pazaryeri tespiti
            marketplace_name = None
            _mp_fields = [
                ('trendyol_order_id', 'Trendyol'),
                ('hb_order_id', 'Hepsiburada'),
                ('amazon_order_id', 'Amazon'),
                ('pazarama_order_id', 'Pazarama'),
                ('n11_order_id', 'N11'),
                ('flo_order_id', 'Flo'),
                ('idefix_order_id', 'Idefix'),
                ('pttavm_order_id', 'PttAvm'),
                ('shopify_order_id', 'Shopify'),
            ]
            for field, name in _mp_fields:
                if hasattr(self, field) and getattr(self, field):
                    marketplace_name = name
                    break
            
            if not marketplace_name:
                raise Exception("Pazaryeri bilgisi bulunamadı")
            
            mapping = self.env['odoougurlar.marketplace.mapping'].sudo().find_mapping(
                marketplace_name, self.partner_id.country_id.id
            )
            
            order_proc = self.env['odoougurlar.order.processor'].sudo()
            order_proc.sync_order(self, mapping)
            order_msg = '✅ Güncel sipariş Nebim\'e gönderildi.'
            _logger.info("Nebim sipariş tekrar gönderildi: %s", self.name)
            
        except Exception as e:
            order_msg = f'⚠️ Sipariş gönderilemedi: {str(e)}'
            _logger.error("Nebim sipariş tekrar gönderim hatası (%s): %s", self.name, e)
        
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {
                    'title': 'Nebim Sıfırlandı',
                    'message': f'{self.name} sıfırlandı. {order_msg} '
                               'Artık "Paketle ve Faturala" yapabilirsiniz.',
                    'type': 'success' if '✅' in order_msg else 'warning',
                    'sticky': True,
                }}

    def action_cancel(self):
        """Sipariş iptal edildiğinde, Nebim'e gönderilmişse otomatik sil.

        Nebim V3 IntegratorService Delete endpoint'ine istek göndererek
        siparişi Nebim'den siler. Stok serbest kalır.

        Kritik Kurallar:
        - Sadece nebim_order_sent=True olan siparişler silinir
        - Nebim silme hatası Odoo iptalini ASLA engellemez
        - cr.savepoint() ile korumalı — Nebim hatası rollback yapılır
        - Her işlem loglanır
        """
        # Önce Odoo'nun kendi iptalini yap
        res = super().action_cancel()

        # Toggle kontrolü
        ICP = self.env['ir.config_parameter'].sudo()
        auto_delete = ICP.get_param('odoougurlar.nebim_auto_delete_on_cancel', 'True') == 'True'

        if not auto_delete:
            return res

        for order in self:
            if not order.nebim_order_sent:
                continue  # Nebim'e hiç gönderilmemiş, atlat

            try:
                with self.env.cr.savepoint():
                    self._nebim_delete_order(order)
            except Exception as e:
                # Nebim silme hatası Odoo iptalini ASLA engellemez
                _logger.error(
                    "Nebim sipariş silme hatası (Odoo iptal yine de geçerli): %s - %s",
                    order.name, e
                )

        return res

    def _nebim_delete_order(self, order):
        """Nebim'den siparişi siler.

        Strateji: Sipariş oluşturulurken Nebim'e gönderilen orijinal payload'u
        (nebim_order_request) alıp aynısını Delete endpoint'ine göndeririz.
        Nebim kaydı tam olarak aynı yapıda eşleştirir.

        Fallback: Orijinal request yoksa minimal payload ile dener.
        """
        import json as _json

        connector = self.env['odoougurlar.nebim.connector'].sudo()
        doc_number = order.client_order_ref or order.name
        customer_code = order.nebim_customer_code or ''

        # ── 1. Orijinal sipariş request payload'unu kullan
        payload = None
        if order.nebim_order_request:
            try:
                payload = _json.loads(order.nebim_order_request)
                _logger.info(
                    "Nebim silme: Orijinal request payload kullanılıyor: %s (DocNum: %s)",
                    order.name, doc_number
                )
            except Exception as e:
                _logger.warning("Nebim silme: Orijinal request parse edilemedi (%s): %s", order.name, e)

        # ── 2. Fallback: Orijinal request yoksa minimal payload
        if not payload:
            model_type = 13
            store_code = '002'
            warehouse_code = '002'

            marketplace_name = order.marketplace_name
            if marketplace_name:
                try:
                    mapping = self.env['odoougurlar.marketplace.mapping'].sudo().find_mapping(
                        marketplace_name, order.partner_id.country_id.id
                    )
                    if mapping:
                        model_type = int(mapping.nebim_order_model_type) if mapping.nebim_order_model_type else 13
                        is_export = int(mapping.nebim_invoice_model_type) == 24 if mapping.nebim_invoice_model_type else False
                        if is_export:
                            model_type = 14
                        store_code = mapping.store_code or '002'
                        warehouse_code = mapping.warehouse_code or '002'
                except Exception:
                    pass

            payload = {
                'ModelType': model_type,
                'InternalDescription': doc_number,
                'DocumentNumber': doc_number,
                'Description': doc_number,
                'OfficeCode': 'M',
                'StoreCode': store_code,
                'WarehouseCode': warehouse_code,
                'CurrAccCode': customer_code,
                'CustomerCode': customer_code,
            }
            _logger.info(
                "Nebim silme: Fallback minimal payload kullanılıyor: %s (DocNum: %s)",
                order.name, doc_number
            )

        _logger.info(
            "Nebim sipariş silme isteği: %s → Delete endpoint | Payload: %s",
            order.name, _json.dumps(payload, ensure_ascii=False, default=str)[:500]
        )

        # Sipariş oluşturmadaki aynı metod — endpoint olarak 'Delete' gönder
        result = connector.post_data('Delete', payload)

        # ── Sonuç doğrulama
        if isinstance(result, dict) and result.get('ExceptionMessage'):
            raise Exception(f"Nebim Delete Hatası: {result['ExceptionMessage']}")

        # Boş yanıt kontrolü — Nebim hata vermeden boş dönüyorsa uyar
        if result is None or result == '' or result == {}:
            _logger.warning(
                "⚠️ Nebim Delete boş yanıt döndü! Sipariş silinmemiş olabilir: %s (DocNum: %s, CurrAccCode: %s)",
                order.name, doc_number, customer_code
            )

        # Bayrakları sıfırla
        order.sudo().write({
            'nebim_order_sent': False,
            'nebim_order_response': f'[İPTAL] Nebim Delete yanıt: {result}',
        })

        _logger.info(
            "Nebim sipariş silme tamamlandı: %s → DocNum: %s, CurrAccCode: %s, Yanıt: %s",
            order.name, doc_number, customer_code, result
        )

    def action_confirm(self):
        """Sipariş onaylandığında, toggle açıksa Cari ve Sipariş Nebim'e gönderilir."""
        res = super().action_confirm()
        for order in self:
            try:
                self._auto_nebim_sync(order)
            except Exception as e:
                _logger.warning("Sipariş onayında Nebim auto-sync hatası (sipariş yine de onaylandı): %s", e)
        return res

    def _auto_nebim_sync(self, order):
        """Sipariş onayında otomatik Cari ve Sipariş Nebim'e gönder."""
        ICP = self.env['ir.config_parameter'].sudo()
        customer_enabled = ICP.get_param('odoougurlar.nebim_sync_customer_enabled', 'False') == 'True'
        order_enabled = ICP.get_param('odoougurlar.nebim_sync_order_enabled', 'False') == 'True'

        if not customer_enabled and not order_enabled:
            return

        # Pazaryeri siparişi mi kontrol et
        marketplace_name = None
        _mp_fields = [
            ('trendyol_order_id', 'Trendyol'),
            ('hb_order_id', 'Hepsiburada'),
            ('amazon_order_id', 'Amazon'),
            ('pazarama_order_id', 'Pazarama'),
            ('n11_order_id', 'N11'),
            ('flo_order_id', 'Flo'),
            ('idefix_order_id', 'Idefix'),
            ('pttavm_order_id', 'PttAvm'),
            ('shopify_order_id', 'Shopify'),
        ]
        for field, name in _mp_fields:
            if hasattr(order, field) and getattr(order, field):
                marketplace_name = name
                break

        if not marketplace_name:
            return

        try:
            mapping = self.env['odoougurlar.marketplace.mapping'].sudo().find_mapping(
                marketplace_name, order.partner_id.country_id.id
            )

            if not mapping:
                _logger.error(
                    "Auto-sync: '%s' için marketplace mapping bulunamadı! "
                    "Ayarlar > Nebim > Pazaryeri Eşleştirmeleri'nde '%s' kuralı tanımlayın.",
                    marketplace_name, marketplace_name)
                try:
                    order.write({
                        'nebim_customer_response': f'[Auto-Sync] HATA: "{marketplace_name}" için marketplace mapping bulunamadı!'
                    })
                except Exception:
                    pass
                return

            # Cari (savepoint korumalı)
            if customer_enabled and not order.nebim_customer_sent:
                try:
                    with self.env.cr.savepoint():
                        customer_proc = self.env['odoougurlar.customer.processor'].sudo()
                        cust_code, addr_id = customer_proc.sync_customer(
                            order.partner_id, mapping, sale_order=order
                        )
                        order.write({
                            'nebim_customer_sent': True,
                            'nebim_customer_code': cust_code or '',
                            'nebim_address_id': addr_id or ''
                        })
                        _logger.info("Auto-sync Cari başarılı: %s → %s", order.name, cust_code)
                except Exception as e:
                    _logger.error("Auto-sync Cari hatası (%s): %s", order.name, e)
                    try:
                        # NebimCustomerError taşıyorsa request JSON'u da kaydet
                        request_json = getattr(e, 'request_json', '')
                        write_vals = {'nebim_customer_response': f'[Auto-Sync] CARİ HATA: {str(e)}'}
                        if request_json:
                            write_vals['nebim_customer_request'] = request_json
                        order.write(write_vals)
                    except Exception:
                        pass

            # Sipariş (savepoint korumalı)
            if order_enabled and not order.nebim_order_sent:
                try:
                    with self.env.cr.savepoint():
                        order_proc = self.env['odoougurlar.order.processor'].sudo()
                        order_proc.sync_order(order, mapping)
                        _logger.info("Auto-sync Sipariş başarılı: %s", order.name)
                except Exception as e:
                    _logger.error("Auto-sync Sipariş hatası (%s): %s", order.name, e)
                    try:
                        order.write({'nebim_order_response': f'[Auto-Sync] HATA: {str(e)}'})
                    except Exception:
                        pass

        except Exception as e:
            _logger.error("Auto-sync Nebim genel hata (%s): %s", order.name, e)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    nebim_order_line_id = fields.Char(string='Nebim OrderLineID', readonly=True)


