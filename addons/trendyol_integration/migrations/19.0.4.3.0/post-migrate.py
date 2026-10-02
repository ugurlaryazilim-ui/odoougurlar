import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # 1) Uluslararası Hizmet Bedeli artık ayrı tür (eskiden platform_fee'ye düşüyordu)
    cr.execute("""
        UPDATE trendyol_settlement SET transaction_type = 'international_fee'
         WHERE transaction_type = 'platform_fee' AND transaction_type_raw ILIKE '%%uluslararas%%'
    """)
    _logger.info("Trendyol: %s kayıt 'Uluslararası Hizmet Bedeli' türüne taşındı", cr.rowcount)

    # 2) Kalemleri sipariş bazında yazılmış toplu kargo faturaları → dağıtıldı (hakedişte çift sayılmaz)
    cr.execute("""
        UPDATE trendyol_settlement inv
           SET allocation_state = 'allocated',
               allocation_note = 'Kalemleri sipariş bazında kayıtlı (kargo faturası)'
         WHERE inv.source = 'otherfinancials' AND inv.transaction_type = 'shipping_cargo'
           AND EXISTS (SELECT 1 FROM trendyol_settlement c
                        WHERE c.store_id = inv.store_id AND c.source = 'cargo_invoice'
                          AND c.receipt_id = inv.trendyol_id)
    """)
    _logger.info("Trendyol: %s toplu kargo faturası 'dağıtıldı' olarak işaretlendi", cr.rowcount)

    # 3) Hakedişe Etki: kesinti satırlarında alacak − borç (stored compute; _compute_signed ile aynı kural)
    cr.execute("""
        UPDATE trendyol_settlement
           SET signed_seller_revenue = CASE
                   WHEN transaction_type = 'payment' OR allocation_state = 'allocated' THEN 0
                   ELSE COALESCE(credit, 0) - COALESCE(debt, 0) END
         WHERE COALESCE(source, '') <> 'settlements' AND ABS(COALESCE(seller_revenue, 0)) <= 0.005
    """)
    _logger.info("Trendyol: %s kesinti kaydının hakediş etkisi yeniden hesaplandı", cr.rowcount)
