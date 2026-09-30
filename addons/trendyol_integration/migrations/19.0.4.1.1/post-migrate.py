import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Kargo faturası kalemlerinde "İade Kargo Bedeli" (İ.lower() eşleşmiyordu) gönderi kargosu sayılmıştı
    cr.execute("""
        UPDATE trendyol_settlement
           SET transaction_type = 'return_cargo'
         WHERE source = 'cargo_invoice'
           AND transaction_type = 'shipping_cargo'
           AND transaction_type_raw ILIKE '%%ade kargo%%'
    """)
    _logger.info("trendyol_integration: %s iade kargo kalemi düzeltildi", cr.rowcount)

    # Kupon yönü (hakedişi azaltır) ve gönderi başı platform bedeliyle sipariş özetleri yeniden
    env = api.Environment(cr, SUPERUSER_ID, {})
    Settlement = env['trendyol.settlement']
    for store in env['trendyol.store'].with_context(active_test=False).search([]):
        Settlement._update_order_financial_summary(store)
