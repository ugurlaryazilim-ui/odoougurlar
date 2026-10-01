import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Order = env['pazarama.order']

    # 1) Mevcut kayıtlar: kalem durumları, kargo firma ID'si, vergi dairesi ve sipariş durumu
    #    ham veriden yeniden hesaplanır. Odoo siparişlerine burada dokunulmaz.
    refreshed = 0
    for rec in Order.search([('raw_data', '!=', False)]):
        try:
            with cr.savepoint():
                data = rec._raw_json()
                if not data.get('items'):
                    continue
                bill = data.get('billingAddress') or {}
                if bill.get('taxOffice') and not rec.tax_office:
                    rec.tax_office = bill['taxOffice']
                rec._apply_order_json(data)
                refreshed += 1
        except Exception as e:
            _logger.warning("Pazarama migration: %s güncellenemedi: %s", rec.order_number, e)
    _logger.info("Pazarama migration: %d sipariş kaydı yenilendi", refreshed)

    # 2) Güncelleme öncesi Odoo siparişi açılmamış (iptal olmayan) kayıtlar: yeni kod bunları otomatik
    #    açmasın (eski siparişler birden Nebim'e gitmesin) — yalnızca 'Tekrar Dene' ile aktarılır.
    cr.execute("""
        UPDATE pazarama_order SET legacy_no_sale = TRUE,
               error_message = 'Eski kayıt: Odoo siparişi otomatik açılmaz; gerekiyorsa Tekrar Dene.'
        WHERE sale_order_id IS NULL AND COALESCE(order_status, 0) NOT IN (6, 13, 14, 18)
        RETURNING order_number
    """)
    legacy = [r[0] for r in cr.fetchall()]
    if legacy:
        _logger.info("Pazarama migration: %d eski kayıt otomatik aktarımdan hariç tutuldu: %s",
                     len(legacy), ', '.join(legacy[:20]))

    # 3) Aynı mağazada mükerrer sipariş kaydı varsa tekil kısıt eklenemez — raporla
    cr.execute("""
        SELECT store_id, order_id, count(*) FROM pazarama_order
        GROUP BY store_id, order_id HAVING count(*) > 1
    """)
    dups = cr.fetchall()
    if dups:
        _logger.warning("Pazarama migration: %d mükerrer sipariş var (elle temizlenmeli): %s",
                        len(dups), ', '.join(r[1] for r in dups[:20]))

    # 4) Cron kaydı artık noupdate: aralığı mağaza ayarından yeniden uygula
    stores = env['pazarama.store'].search([], limit=1)
    if stores:
        stores._sync_cron_settings()
