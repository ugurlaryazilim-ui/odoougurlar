import logging
from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields

_logger = logging.getLogger(__name__)

_CANCEL = ('shipment_cancelled', 'shipment_unsupplied', 'shipment_split')


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Order = env['idefix.order']

    # 1) Mevcut kayıtlar ham veriden yeniden hesaplanır (kalem tutarları, kargo profili, vergi dairesi,
    #    fatura tipi). Odoo siparişlerine burada dokunulmaz.
    refreshed = 0
    for rec in Order.search([('raw_data', '!=', False)]):
        try:
            with cr.savepoint():
                data = rec._raw_json()
                if not data.get('items'):
                    continue
                header = Order._order_header_vals(rec.store_id, data)
                extra = {k: header[k] for k in ('tax_office', 'invoice_type') if rec[k] != header[k]}
                if extra:
                    rec.write(extra)
                rec._apply_order_json(data)
                refreshed += 1
        except Exception as e:
            _logger.warning("Idefix migration: %s güncellenemedi: %s", rec.order_number, e)
    _logger.info("Idefix migration: %d sevkiyat kaydı yenilendi", refreshed)

    # 2) Güncelleme öncesi Odoo siparişi açılmamış (kapanmamış) kayıtlar: yeni kod bunları otomatik
    #    açmasın (eski siparişler birden Nebim'e gitmesin) — yalnızca 'Tekrar Dene' ile aktarılır.
    cr.execute("""
        UPDATE idefix_order SET legacy_no_sale = TRUE,
               error_message = 'Eski kayıt: Odoo siparişi otomatik açılmaz; gerekiyorsa Tekrar Dene.'
        WHERE sale_order_id IS NULL AND COALESCE(order_status, '') NOT IN %s
        RETURNING order_number
    """, (_CANCEL,))
    legacy = [r[0] for r in cr.fetchall()]
    if legacy:
        _logger.info("Idefix migration: %d eski kayıt otomatik aktarımdan hariç tutuldu: %s",
                     len(legacy), ', '.join(legacy[:20]))

    # 3) Eski kod iptalleri tanımadığı için Idefix'te kapanmış ama Odoo siparişi açık kalan eski kayıtlar
    #    (otomatik iptal yalnızca son 30 günü kapsar) — elle kontrol için işaretlenir.
    cutoff = fields.Datetime.now() - timedelta(days=30)
    old_open = Order.search([
        ('order_status', 'in', list(_CANCEL)),
        ('sale_order_id.state', 'not in', ['cancel', 'done']),
        ('order_date', '<', cutoff),
    ])
    for rec in old_open:
        rec.error_message = (f"Idefix'te '{rec.order_status_display}' ancak Odoo siparişi "
                             f"{rec.sale_order_id.name} açık (eski kayıt, otomatik iptal edilmedi); elle kontrol edin.")
    if old_open:
        _logger.warning("Idefix migration: %d eski kapanmış sevkiyatın Odoo siparişi açık: %s",
                        len(old_open), ', '.join(old_open.mapped('order_number')[:20]))

    # 4) Mağaza ayarları: platform anlaşmalı kargoda takip no gönderimi zararlı — kapatılır;
    #    iade gün aralığı 30'a çıkar. Cron kaydı artık noupdate: aralık mağaza ayarından yeniden uygulanır.
    stores = env['idefix.store'].with_context(active_test=False).search([])
    stores.write({'auto_send_cargo': False})
    stores.filtered(lambda s: (s.return_day_range or 0) < 30).write({'return_day_range': 30})
    if stores:
        stores[:1]._sync_cron_settings()

    # 5) Eski 'payment-agreements' denemesinden kalan finans kayıtları (servis Idefix'te yok) silinir,
    #    son 60 günün sevkiyatlarından finansal özet üretilir.
    Settlement = env['idefix.settlement']
    stale = Settlement.search([('idefix_order_id', '=', False)])
    if stale:
        _logger.info("Idefix migration: %d eski finans kaydı silindi", len(stale))
        stale.unlink()
    since = fields.Datetime.now() - timedelta(days=60)
    for store in stores:
        Order._rebuild_settlements(store, since)
