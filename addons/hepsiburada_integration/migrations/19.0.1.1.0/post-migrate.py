import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Mevcut HB siparişlerine mağaza bağlantısı (store_id) ver — merchant_id üzerinden."""
    cr.execute("""
        UPDATE hepsiburada_order o
           SET store_id = s.id
          FROM hepsiburada_store s
         WHERE o.store_id IS NULL
           AND o.merchant_id = s.merchant_id
    """)
    _logger.info("hepsiburada_integration: %s siparişe mağaza bağlandı", cr.rowcount)
