import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # Komisyon faturası hakedişi ikinci kez azaltmaz: komisyon satış satırlarında zaten düşülü
    cr.execute("""
        UPDATE trendyol_settlement SET signed_seller_revenue = 0
         WHERE source = 'otherfinancials' AND transaction_type = 'commission'
           AND ABS(COALESCE(seller_revenue, 0)) <= 0.005 AND COALESCE(signed_seller_revenue, 0) <> 0
    """)
    _logger.info("Trendyol: %s komisyon faturasının hakediş etkisi sıfırlandı", cr.rowcount)

    # Mevcut komisyon faturaları dönemlerindeki kayıtlarla hemen eşleştirilir (API gerekmez)
    env = api.Environment(cr, SUPERUSER_ID, {})
    Settlement = env['trendyol.settlement']
    for store in env['trendyol.store'].with_context(active_test=False).search([]):
        res = Settlement._allocate_commission_invoices(store, recheck_days=36500)
        _logger.info("Trendyol komisyon faturaları eşleştirildi [%s]: %s", store.name, res)
