import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # 1) Teslimat tipi: siparişin ham JSON'undan (Bugün Kargoda platform bedeli için)
    cr.execute("""
        UPDATE trendyol_order
           SET fast_delivery_type = substring(raw_data from '"fastDeliveryType"\\s*:\\s*"([A-Za-z]+)"')
         WHERE fast_delivery_type IS NULL AND raw_data LIKE '%%fastDeliveryType%%'
    """)
    _logger.info("Trendyol: %s siparişin teslimat tipi ham veriden dolduruldu", cr.rowcount)

    # 2) Dağıtım artık ödeme + tür bazında gruplu (satır anahtarı değişti) → eski satırlar silinir,
    #    hizmet bedeli faturaları yeniden dağıtılmak üzere 'bekliyor'a alınır (cron / buton dağıtır)
    cr.execute("DELETE FROM trendyol_settlement WHERE source = 'fee_allocation'")
    _logger.info("Trendyol: %s eski dağıtım satırı silindi", cr.rowcount)
    cr.execute("""
        UPDATE trendyol_settlement f
           SET allocation_state = 'pending', allocation_checked_at = NULL,
               allocation_note = 'Gruplu dağıtıma geçiş — yeniden dağıtılacak',
               signed_seller_revenue = COALESCE(f.credit, 0) - COALESCE(f.debt, 0)
         WHERE f.source = 'otherfinancials'
           AND f.transaction_type IN ('platform_fee', 'international_fee')
           AND COALESCE(f.order_number, '') = '' AND COALESCE(f.shipment_package_id, '') = ''
           AND COALESCE(f.allocation_state, '') <> 'pending'
           AND NOT EXISTS (SELECT 1 FROM trendyol_settlement p
                            WHERE p.store_id = f.store_id AND p.source = 'platform_invoice'
                              AND p.receipt_id = f.trendyol_id)
    """)
    _logger.info("Trendyol: %s hizmet bedeli faturası yeniden dağıtım için sıraya alındı", cr.rowcount)
