import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Order = env['pttavm.order']

    # 1) Mevcut kayıtlar: satır durumları ve sipariş durumu artık tüm satırlardan hesaplanır
    #    (eskiden yalnızca ilk ürünün durumu yazılıyordu). Odoo siparişlerine burada dokunulmaz;
    #    gerekli iptal / güncelleme ilk senkronda yapılır.
    refreshed = 0
    for rec in Order.search([('raw_data', '!=', False)]):
        try:
            with cr.savepoint():
                data = rec._raw_json()
                if data.get('siparisUrunler'):
                    rec._apply_order_json(data)
                    refreshed += 1
        except Exception as e:
            _logger.warning("PttAVM migration: %s güncellenemedi: %s", rec.order_number, e)
    _logger.info("PttAVM migration: %d sipariş kaydı satır durumlarıyla yenilendi", refreshed)

    # 2) Aynı mağazada mükerrer sipariş kaydı varsa tekil kısıt eklenemez — raporla
    cr.execute("""
        SELECT store_id, order_number, count(*) FROM pttavm_order
        GROUP BY store_id, order_number HAVING count(*) > 1
    """)
    dups = cr.fetchall()
    if dups:
        _logger.warning("PttAVM migration: %d mükerrer sipariş numarası var (elle temizlenmeli): %s",
                        len(dups), ', '.join(r[1] for r in dups[:20]))

    # 3) Cron kaydı artık noupdate: aralığı mağaza ayarından yeniden uygula
    stores = env['pttavm.store'].search([], limit=1)
    if stores:
        stores._update_cron_interval()
