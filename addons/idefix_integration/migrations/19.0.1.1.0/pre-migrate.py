import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Yeni UNIQUE(store_id, order_id) kısıtı eklenebilsin diye mükerrer sevkiyat kayıtlarını temizler.
    Odoo siparişine bağlı kayıt korunur; yalnızca siparişsiz kopyalar silinir."""
    if not version:
        return
    cr.execute("""
        SELECT store_id, order_id, array_agg(id ORDER BY (sale_order_id IS NULL), id)
        FROM idefix_order GROUP BY store_id, order_id HAVING count(*) > 1
    """)
    removed = []
    for _store_id, order_id, ids in cr.fetchall():
        cr.execute("SELECT id FROM idefix_order WHERE id = ANY(%s) AND id != %s AND sale_order_id IS NULL",
                   (ids[1:], ids[0]))
        drop = [r[0] for r in cr.fetchall()]
        if drop:
            cr.execute("DELETE FROM idefix_order WHERE id = ANY(%s)", (drop,))
            removed.append(order_id)
    if removed:
        _logger.info("Idefix migration: %d mükerrer sevkiyat kopyası silindi: %s",
                     len(removed), ', '.join(removed[:20]))
