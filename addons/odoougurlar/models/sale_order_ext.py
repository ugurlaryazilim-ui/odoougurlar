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


