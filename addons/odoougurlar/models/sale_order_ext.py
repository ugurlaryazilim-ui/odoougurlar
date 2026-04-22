from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    nebim_customer_sent = fields.Boolean(string='Nebim Cari Açıldı', default=False, readonly=True)
    nebim_customer_code = fields.Char(string='Nebim Cari Kodu', readonly=True)
    nebim_address_id = fields.Char(string='Nebim Adres ID', readonly=True)
    nebim_order_sent = fields.Boolean(string='Nebim Sipariş Aktarıldı', default=False, readonly=True)
    nebim_order_response = fields.Text(string='Nebim Sipariş Cevabı', readonly=True)
    nebim_export_file_number = fields.Char(string='Nebim ExportFileNumber', readonly=True)

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
        if hasattr(order, 'trendyol_order_id') and order.trendyol_order_id:
            marketplace_name = 'Trendyol'
        elif hasattr(order, 'hb_order_id') and order.hb_order_id:
            marketplace_name = 'Hepsiburada'
        elif hasattr(order, 'amazon_order_id') and order.amazon_order_id:
            marketplace_name = 'Amazon'
        elif hasattr(order, 'pazarama_order_id') and order.pazarama_order_id:
            marketplace_name = 'Pazarama'
        
        if not marketplace_name:
            return

        try:
            mapping = self.env['odoougurlar.marketplace.mapping'].sudo().find_mapping(
                marketplace_name, order.partner_id.country_id.id
            )

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

