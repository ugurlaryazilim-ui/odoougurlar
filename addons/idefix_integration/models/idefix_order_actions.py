"""Idefix sipariş toplu işlemleri — retry, refresh, delete, mark."""
import json
import logging

from odoo import api, fields, models
from .idefix_order_sync import IDEFIX_VALID_ORDER_STATUSES

_logger = logging.getLogger(__name__)

class IdefixOrderActions(models.Model):
    """Toplu işlem ve UI aksiyon metodları."""
    _inherit = 'idefix.order'

    def action_retry_sync(self):
        """Seçili hatalı sipariş kayıtlarını tekrar dene."""
        errors = self.filtered(lambda o: not o.sale_order_id and o.raw_data)
        if not errors:
            return self._notify('Uyarı', 'Takılmıs, tekrar denenecek hatalı sipariş yok.', 'warning')

        success = 0
        fail = 0
        for order in errors:
            try:
                package_data = json.loads(order.raw_data)
                store = order.store_id
                if not store:
                    store = self.env['idefix.store'].search([('active', '=', True)], limit=1)
                if not store:
                    fail += 1
                    continue
                
                # Geçerli statülerdeki siparişler için Sale Order oluştur
                if order.order_status in IDEFIX_VALID_ORDER_STATUSES:
                    shipment_addr = package_data.get('shippingAddress') or {}
                    billing_addr = package_data.get('invoiceAddress') or {}
                    customer_email = package_data.get('customerContactMail') or ''
                    phone_number = shipment_addr.get('phone') or ''

                    sale_order = self._create_odoo_sale_order(
                        order, store, shipment_addr, billing_addr,
                        customer_email, phone_number
                    )
                    order.write({
                        'sale_order_id': sale_order.id,
                        'store_id': store.id,
                    })
                    
                    if store.auto_confirm and sale_order.state in ['draft', 'sent']:
                        sale_order.action_confirm()

                    success += 1
                else:
                    fail += 1
            except Exception as e:
                fail += 1
                _logger.exception("Idefix Tekrar deneme hatası %s: %s", order.order_number, e)

        return self._notify(
            'Tekrar Deneme Sonucu',
            f'✅ Başarılı: {success}\n❌ Başarısız/Atlanan: {fail}',
            'success' if fail == 0 else 'warning',
        )

    def action_refresh_from_idefix(self):
        """Seçili siparişlerin durumunu Idefix API'den güncelle."""
        if not self:
            return

        store_orders = {}
        for order in self:
            store = order.store_id
            if not store:
                continue
            if store.id not in store_orders:
                store_orders[store.id] = {'store': store, 'orders': self.env['idefix.order']}
            store_orders[store.id]['orders'] |= order

        updated = 0
        for data in store_orders.values():
            store = data['store']
            try:
                api = store.get_api()
            except Exception as e:
                _logger.warning("API bağlantı hatası [%s]: %s", store.name, e)
                continue

            for order in data['orders']:
                if not order.order_id:
                    continue
                try:
                    # Idefix'in kendi list endpoint'ini kullan
                    result = api.get_orders(
                        start_date=order.order_date,
                        end_date=fields.Datetime.now(),
                        page=1, limit=50
                    )
                    
                    if result.get('success'):
                        items = result.get('data', {}).get('items', [])
                        # order_id ile eşleştir
                        pkg = None
                        for item in items:
                            if str(item.get('id')) == order.order_id:
                                pkg = item
                                break
                        
                        if pkg:
                            new_status = pkg.get('status')
                            vals = {
                                'order_status': new_status if new_status else order.order_status,
                                'raw_data': json.dumps(pkg, ensure_ascii=False),
                            }
                            
                            # Kargo bilgisi
                            if pkg.get('cargoTrackingNumber'):
                                vals['cargo_tracking_number'] = str(pkg['cargoTrackingNumber'])
                            if pkg.get('cargoCompany'):
                                vals['cargo_provider'] = pkg['cargoCompany']

                            order.write(vals)
                            updated += 1
                except Exception as e:
                    _logger.warning("Durum güncelleme hatası %s: %s", order.order_number, e)

        return self._notify(
            'Durum Güncelleme',
            f'✅ {updated}/{len(self)} sipariş Idefix\'dan güncellendi.',
            'success' if updated else 'warning',
        )

    def action_delete_error_orders(self):
        to_delete = self.filtered(lambda o: not o.sale_order_id)
        if not to_delete:
            return self._notify('Bilgi', 'Silinecek taslak/hatalı kayıt yok.', 'warning')
        count = len(to_delete)
        to_delete.unlink()
        return self._notify('Silme', f'🗑️ {count} hatalı kayıt silindi.', 'success')

    def action_retry_all_errors(self):
        errors = self.search([('sale_order_id', '=', False)])
        if not errors:
            return self._notify('Bilgi', 'Tekrar denenecek hatalı sipariş yok.', 'info')
        return errors.action_retry_sync()

    def _notify(self, title, message, ntype='info'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': f'Idefix - {title}',
                'message': message,
                'type': ntype,
                'sticky': ntype in ('danger', 'warning'),
            },
        }
