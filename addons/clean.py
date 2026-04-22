import sys
import odoo
from odoo import api, SUPERUSER_ID
from datetime import datetime, timedelta

import odoo.modules.registry
odoo.tools.config.parse_config(['-c', '/etc/odoo/odoo.conf'])
registry = odoo.modules.registry.Registry('ugurlar')

with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    
    cutoff = datetime.now() - timedelta(hours=3)
    sale_orders = env['sale.order'].search([
        ('create_date', '>=', cutoff),
        ('n11_store_id', '!=', False)
    ])
    
    print(f"Silinecek Satis Sipariş sayısı: {len(sale_orders)}")
    count = 0
    for so in sale_orders:
        try:
            if so.state == 'done':
                so.action_unlock()
            if so.state != 'cancel':
                so.action_cancel()
        except Exception as e:
            print(f"Cancel error: {e}")
            
        try:
            for picking in so.picking_ids:
                if picking.state != 'cancel':
                    picking.action_cancel()
                picking.unlink()
        except Exception as e:
            pass
            
        try:
            so.unlink()
            count += 1
        except Exception as e:
            print(f"Unlink error: {e}")
            
    print(f"Toplam {count} adet Satis Siparişi temizlendi.")
