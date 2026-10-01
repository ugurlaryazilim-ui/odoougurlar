import json
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Order = env['pazarama.order']
    filled = 0
    # Yeni alanlar (entegrasyon bedeli, kargo borcu, stopaj, sipariş bağlantısı) ham veriden doldurulur
    for rec in env['pazarama.settlement'].search([]):
        try:
            item = json.loads(rec.raw_data or '{}')
        except ValueError:
            item = {}
        vals = {
            'integration_amount': item.get('integrationAmount') or 0.0,
            'cargo_debt': item.get('merchantCargoDebt') or 0.0,
            'stoppage_amount': item.get('stoppageAmount') or 0.0,
        }
        if rec.order_id:
            order = Order.search([('store_id', '=', rec.store_id.id), ('order_number', '=', rec.order_id)], limit=1)
            if order:
                vals['pazarama_order_id'] = order.id
        rec.write(vals)
        filled += 1
    _logger.info("Pazarama migration: %d finans kaydı yeni alanlarla dolduruldu", filled)
