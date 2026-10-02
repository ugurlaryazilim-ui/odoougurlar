import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # TR kanalı (TRENDYOLTR) dağıtımları yeniden yapılır:
    # - Uluslararası bedel Türkiye paketlerine de paylaştırılmıştı (yalnız yurt dışı paketlere ait)
    # - Platform bedeli eşit bölünebildiğinde standart tarifeyle (13,19 / 5,99) doğrulanmadan dağıtılmıştı
    # AZ kanalı doğruydu, dokunulmaz.
    cr.execute("""
        DELETE FROM trendyol_settlement
         WHERE source = 'fee_allocation' AND COALESCE(affiliate, '') NOT ILIKE '%%AZ%%'
    """)
    _logger.info("Trendyol: %s TR kanalı dağıtım satırı silindi", cr.rowcount)
    cr.execute("""
        UPDATE trendyol_settlement f
           SET allocation_state = 'pending', allocation_checked_at = NULL,
               allocation_note = 'TR kuralları düzeltildi — yeniden dağıtılacak',
               signed_seller_revenue = COALESCE(f.credit, 0) - COALESCE(f.debt, 0)
         WHERE f.source = 'otherfinancials'
           AND f.transaction_type IN ('platform_fee', 'international_fee')
           AND COALESCE(f.order_number, '') = '' AND COALESCE(f.shipment_package_id, '') = ''
           AND COALESCE(f.affiliate, '') NOT ILIKE '%%AZ%%'
           AND COALESCE(f.allocation_state, '') <> 'pending'
           AND NOT EXISTS (SELECT 1 FROM trendyol_settlement p
                            WHERE p.store_id = f.store_id AND p.source = 'platform_invoice'
                              AND p.receipt_id = f.trendyol_id)
    """)
    _logger.info("Trendyol: %s TR hizmet bedeli faturası yeniden dağıtım için sıraya alındı", cr.rowcount)
    cr.execute("""
        UPDATE trendyol_fee_payment t SET state = 'pending'
         WHERE t.state IN ('allocated', 'warning', 'unmatched')
           AND EXISTS (SELECT 1 FROM trendyol_settlement f
                        WHERE f.store_id = t.store_id AND f.payment_order_id = t.payment_order_id
                          AND f.source = 'otherfinancials' AND f.allocation_state = 'pending'
                          AND f.transaction_type IN ('platform_fee', 'international_fee'))
    """)
    _logger.info("Trendyol: %s ödeme yeniden kuyruğa alındı", cr.rowcount)
