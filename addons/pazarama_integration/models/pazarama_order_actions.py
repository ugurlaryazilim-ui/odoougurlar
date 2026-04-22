# -*- coding: utf-8 -*-
"""Pazarama sipariş toplu işlemleri — retry, refresh, delete, mark."""
import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class PazaramaOrderActions(models.Model):
    """Toplu işlem ve UI aksiyon metodları."""
    _inherit = 'pazarama.order'

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
                    store = self.env['pazarama.store'].search([('active', '=', True)], limit=1)
                if not store:
                    fail += 1
                    continue
                
                # Sadece Odoo'da faturalandırma aşamasına girenleri içeri al (Örn: orderStatus == 3 'Sipariş Alındı' ise)
                if order.order_status in [3, 12]:
                    # Create odoo sale order from pazarama_order_sync method 
                    shipment_addr = package_data.get('shipmentAddress') or {}
                    billing_addr = package_data.get('billingAddress') or {}
                    customer_email = package_data.get('customerEmail') or shipment_addr.get('customerEmail') or ''
                    phone_number = shipment_addr.get('phoneNumber') or ''

                    sale_order = self._create_odoo_sale_order(order, store, shipment_addr, billing_addr, customer_email, phone_number)
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
                _logger.exception("Pazarama Tekrar deneme hatası %s: %s", order.order_number, e)

        return self._notify(
            'Tekrar Deneme Sonucu',
            f'✅ Başarılı: {success}\n❌ Başarısız/Atlanan: {fail}',
            'success' if fail == 0 else 'warning',
        )

    def action_refresh_from_pazarama(self):
        """Seçili siparişlerin durumunu Pazarama API'den güncelle."""
        if not self:
            return

        store_orders = {}
        for order in self:
            store = order.store_id
            if not store:
                continue
            if store.id not in store_orders:
                store_orders[store.id] = {'store': store, 'orders': self.env['pazarama.order']}
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
                if not order.order_number:
                    continue
                try:
                    # Pazarama getOrders endpointini saat araligiyla verebiliriz ama orderNumber a gore filtremiz yok (Payload'da startDate, endDate istiyor).
                    # Belgede orderNumber desteklendigini gorduk:
                    # Request (Order / Saat&Dakika): "orderNumber": 735071747, "startDate":...
                    # So we can pass orderNumber in getOrdersForApi.
                    body = {
                        'pageSize': 1,
                        'pageNumber': 1,
                        'orderNumber': order.order_number
                    }
                    result = api._request('POST', '/order/getOrdersForApi', data=body)
                    
                    if result['success']:
                        content = result.get('data', {}).get('data', [])
                        if content:
                            pkg = content[0]
                            new_status = pkg.get('orderStatus')
                            vals = {
                                'order_status': new_status if new_status else order.order_status,
                                'raw_data': json.dumps(pkg, ensure_ascii=False),
                            }
                            
                            # Update items
                            # (Cargo tracking comes grouped under items, picking first one broadly)
                            items = pkg.get('items', [])
                            if items:
                                first_cargo = items[0].get('cargo', {})
                                if first_cargo.get('trackingNumber'):
                                    vals['cargo_tracking_number'] = str(first_cargo['trackingNumber'])
                                if first_cargo.get('companyName'):
                                    vals['cargo_provider'] = first_cargo['companyName']

                            order.write(vals)
                            updated += 1
                except Exception as e:
                    _logger.warning("Durum güncelleme hatası %s: %s", order.order_number, e)

        return self._notify(
            'Durum Güncelleme',
            f'✅ {updated}/{len(self)} sipariş Pazarama\'dan güncellendi.',
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
                'title': f'Pazarama - {title}',
                'message': message,
                'type': ntype,
                'sticky': ntype in ('danger', 'warning'),
            },
        }
