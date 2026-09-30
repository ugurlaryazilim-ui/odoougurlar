import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # 1) Trendyol orderDate GMT+3 epoch gelir; eski kayıtlar UTC sanılıp 3 saat ileri yazılmıştı.
    #    Satış siparişlerinin tarihine dokunulmaz (Nebim'e giden belgeler değişmesin).
    cr.execute("""
        UPDATE trendyol_order
           SET order_date = order_date - interval '3 hours'
         WHERE order_date IS NOT NULL
    """)
    _logger.info("trendyol_integration: %s siparişin tarihi düzeltildi (-3 saat)", cr.rowcount)

    # 2) Trendyol sipariş servisleri en fazla 14 günlük aralık kabul eder
    cr.execute("UPDATE trendyol_store SET order_day_range = 14 WHERE order_day_range > 14")

    # 3) Türkçe harf sadeleştirme hatası yüzünden "Diğer"e düşen finans kayıtları
    #    (Satış, Ödeme, Kusurlu/Yanlış/Eksik Ürün Faturası vb.) yeniden sınıflandırılır
    env = api.Environment(cr, SUPERUSER_ID, {})
    Settlement = env['trendyol.settlement']
    records = Settlement.search([('source', 'in', ['settlements', 'otherfinancials'])])
    changed = 0
    by_type = {}
    for rec in records:
        new_type = Settlement._classify_transaction_type(rec.transaction_type_raw, rec.description)
        if new_type != rec.transaction_type:
            by_type.setdefault(new_type, []).append(rec.id)
            changed += 1
    for new_type, ids in by_type.items():
        Settlement.browse(ids).write({'transaction_type': new_type})
    _logger.info("trendyol_integration: %s finans kaydı yeniden sınıflandırıldı %s",
                 changed, {k: len(v) for k, v in by_type.items()})

    # Sipariş özetleri (hakediş, ceza, stopaj, net) tüm geçmiş için yeniden hesaplanır
    for store in env['trendyol.store'].with_context(active_test=False).search([]):
        Settlement._update_order_financial_summary(store)
