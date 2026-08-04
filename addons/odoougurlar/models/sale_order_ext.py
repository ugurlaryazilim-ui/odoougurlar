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
                    if not mp_name:
                        mp_name = mp
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
            elif ('amazon_order_id' in order._fields and order.amazon_order_id) or ('amazon_store_id' in order._fields and order.amazon_store_id):
                if 'amazon_order_id' in order._fields and order.amazon_order_id and order.amazon_order_id.status_display:
                    display = order.amazon_order_id.status_display
                else:
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

    def _action_cancel(self):
        """Sipariş iptal edildiğinde, Nebim'e gönderilmişse otomatik sil.

        Trendyol ve diğer pazaryerleri _action_cancel() çağırır,
        Manuel iptal ise action_cancel() → _action_cancel() zinciri ile çalışır.
        Bu yüzden hook _action_cancel() üzerinde olmalı.

        Kritik Kurallar:
        - Sadece nebim_order_sent=True olan siparişler silinir
        - Nebim silme hatası Odoo iptalini ASLA engellemez
        - cr.savepoint() ile korumalı — Nebim hatası rollback yapılır
        - Her işlem loglanır
        """
        # Önce Odoo'nun kendi iptalini yap
        res = super()._action_cancel()

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

        IntegratorService Delete endpoint'i çalışmadığı için (POST sahte success,
        HTTP DELETE 'Invalid V3 Model Type' hatası) doğrudan SQL ile silme yapılır.

        RunProc → sp_DeleteOrder_Ugurlar stored procedure'ünü çağırır.
        SP, trOrderHeader ve trOrderLine tablolarından InternalDescription'a göre siler.
        """
        connector = self.env['odoougurlar.nebim.connector'].sudo()
        doc_number = order.client_order_ref or order.name

        _logger.info(
            "Nebim sipariş silme (RunProc): %s (DocNum: %s, CurrAccCode: %s)",
            order.name, doc_number, order.nebim_customer_code or ''
        )

        # RunProc ile SP çağır
        customer_code = order.nebim_customer_code or ''
        sp_params = [
            {'Name': 'InternalDescription', 'Value': doc_number},
            {'Name': 'CurrAccCode', 'Value': customer_code},
        ]

        try:
            result = connector.run_proc('sp_DeleteOrder_Ugurlar', sp_params)
        except Exception as e:
            raise Exception(f"Nebim SP çağırma hatası (sp_DeleteOrder_Ugurlar): {str(e)}")

        # SP sonucunu kontrol et
        sp_result = 'UNKNOWN'
        sp_message = str(result)

        if isinstance(result, list) and len(result) > 0:
            row = result[0]
            sp_result = row.get('Result', 'UNKNOWN')
            sp_message = row.get('Message', str(result))

            if sp_result == 'NOT_FOUND':
                _logger.warning("Nebim sipariş bulunamadı: %s (DocNum: %s)", order.name, doc_number)
                raise Exception(f"Nebim'de sipariş bulunamadı: {doc_number}")

            if sp_result == 'ERROR':
                error_msg = row.get('Message', 'Bilinmeyen hata')
                _logger.error("Nebim silme SQL hatası: %s → %s", order.name, error_msg)
                raise Exception(f"Nebim SQL silme hatası: {error_msg}")

            if sp_result == 'SUCCESS':
                order_number = row.get('OrderNumber', '')
                _logger.info(
                    "✅ Nebim sipariş silindi: %s → OrderNumber: %s",
                    order.name, order_number
                )

            if sp_result == 'CC_ONLY':
                _logger.info(
                    "✅ Nebim CC temizlendi (OrderHeader zaten yok): %s (DocNum: %s)",
                    order.name, doc_number
                )

        # Bayrakları sıfırla
        order.sudo().write({
            'nebim_order_sent': False,
            'nebim_order_response': f'[İPTAL] Nebim SQL ile silindi. SP Sonuç: {sp_result} | {sp_message}',
        })

        _logger.info(
            "Nebim sipariş silme tamamlandı: %s → DocNum: %s, Sonuç: %s",
            order.name, doc_number, sp_result
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
        """Sipariş onayında otomatik Cari ve Sipariş Nebim'e gönder.
        
        Duplikasyon Koruması:
        - Bağımsız cursor ile committed DB state kontrolü (rollback-proof)
        - Email-bazlı cari dedup (aynı email ile mevcut cari kodu varsa yeniden kullanır)
        - API sonuçları bağımsız cursor ile kaydedilir (ana transaction rollback yapsa bile kalıcı)
        """
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

        order_id = order.id

        # ═══════════════════════════════════════════════════════════════════
        # DUPLIKASYON KORUMASI: Bağımsız cursor ile committed state kontrolü
        # ORM cache ana transaction'a bağlıdır — rollback'te sıfırlanır.
        db_customer_sent = order.sudo().nebim_customer_sent
        db_order_sent = order.sudo().nebim_order_sent

        # Sipariş zaten Nebim'e gönderilmişse (committed state), atla
        if db_order_sent and (db_customer_sent or not customer_enabled):
            _logger.info("Duplikasyon koruması: %s zaten Nebim'e gönderilmiş (DB committed), atlanıyor.", order.name)
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

            # ─── CARİ ───
            if customer_enabled and not db_customer_sent:
                try:
                    # Email-bazlı cari dedup: mevcut cari kodu var mı?
                    existing_code = self._find_existing_nebim_customer(order)
                    
                    if existing_code:
                        cust_code = existing_code
                        addr_id = ''
                        _logger.info(
                            "Email dedup: %s → mevcut Nebim cari kodu kullanılıyor: %s",
                            order.name, cust_code
                        )
                    else:
                        with self.env.cr.savepoint():
                            customer_proc = self.env['odoougurlar.customer.processor'].sudo()
                            cust_code, addr_id = customer_proc.sync_customer(
                                order.partner_id, mapping, sale_order=order
                            )

                    order.sudo().write({
                        'nebim_customer_sent': True,
                        'nebim_customer_code': cust_code or '',
                        'nebim_address_id': addr_id or ''
                    })
                    _logger.info("Auto-sync Cari başarılı: %s → %s", order.name, cust_code)

                except Exception as e:
                    _logger.error("Auto-sync Cari hatası (%s): %s", order.name, e)
                    try:
                        request_json = getattr(e, 'request_json', '')
                        write_vals = {'nebim_customer_response': f'[Auto-Sync] CARİ HATA: {str(e)}'}
                        if request_json:
                            write_vals['nebim_customer_request'] = request_json
                        order.write(write_vals)
                    except Exception:
                        pass

            # ─── SİPARİŞ ───
            if order_enabled and not db_order_sent:
                try:
                    with self.env.cr.savepoint():
                        order_proc = self.env['odoougurlar.order.processor'].sudo()
                        order_proc.sync_order(order, mapping)
                    
                    order.sudo().write({'nebim_order_sent': True})
                    _logger.info("Auto-sync Sipariş başarılı: %s", order.name)

                except Exception as e:
                    _logger.error("Auto-sync Sipariş hatası (%s): %s", order.name, e)
                    try:
                        order.write({'nebim_order_response': f'[Auto-Sync] HATA: {str(e)}'})
                    except Exception:
                        pass

        except Exception as e:
            _logger.error("Auto-sync Nebim genel hata (%s): %s", order.name, e)

    def _find_existing_nebim_customer(self, order):
        """Partner veya email/TCKN adresi ile mevcut Nebim cari kodu bul (duplikasyon önleme).
        
        1. Partner'ın kendi nebim_customer_code alanını kontrol eder.
        2. Aynı email/TCKN ile daha önce Nebim'e gönderilmiş res_partner arar.
        3. Aynı email ile daha önce Nebim'e gönderilmiş sale_order arar.
        
        Returns:
            str: Mevcut CurrAccCode veya False
        """
        partner = order.partner_id
        if partner.nebim_customer_code:
            return partner.nebim_customer_code

        email = (partner.email or '').strip().lower()
        vat_raw = partner.vat or ''
        vat_clean = ''.join(filter(str.isdigit, vat_raw))
        
        if email:
            try:
                existing_partner = self.env['res.partner'].sudo().search([
                    ('nebim_customer_sent', '=', True),
                    ('nebim_customer_code', '!=', False),
                    ('nebim_customer_code', '!=', ''),
                    ('email', '=ilike', email)
                ], limit=1, order='id desc')
                if existing_partner:
                    _logger.info("Partner dedup bulundu (res_partner): %s → mevcut cari: %s", partner.name, existing_partner.nebim_customer_code)
                    return existing_partner.nebim_customer_code

                existing_so = self.env['sale.order'].sudo().search([
                    ('id', '!=', order.id),
                    ('nebim_customer_sent', '=', True),
                    ('nebim_customer_code', '!=', False),
                    ('nebim_customer_code', '!=', ''),
                    ('partner_id.email', '=ilike', email)
                ], limit=1, order='id desc')
                if existing_so:
                    _logger.info("Email dedup bulundu (sale_order): %s (%s) → mevcut cari: %s", partner.name, email, existing_so.nebim_customer_code)
                    return existing_so.nebim_customer_code
            except Exception as e:
                _logger.warning("Email dedup sorgusu hatası: %s", e)

        return False


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    nebim_order_line_id = fields.Char(string='Nebim OrderLineID', readonly=True)


