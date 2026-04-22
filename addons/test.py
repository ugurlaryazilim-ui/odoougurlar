import odoo.modules.registry
from odoo import api, SUPERUSER_ID
import json

odoo.tools.config.parse_config(['-c', '/etc/odoo/odoo.conf'])
registry = odoo.modules.registry.Registry('ugurlar')

with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    latest = env['n11.order'].search([], order='id desc', limit=10)
    for order in latest:
        raw = json.loads(order.raw_data)
        addr = raw.get('shippingAddress', {})
        print(f"Order: {order.order_number} | City: {addr.get('city')} | District: {addr.get('district')} | Nhood: {addr.get('neighborhood')}")
