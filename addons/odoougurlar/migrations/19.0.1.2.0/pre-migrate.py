import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    # Yeni saklanan alan: sütun önceden açılıp SQL ile doldurulur; ORM tüm siparişleri tek tek
    # hesaplamaz (yükseltme uzamaz). Kural _compute_invoice_datetime ile aynı.
    cr.execute("ALTER TABLE sale_order ADD COLUMN IF NOT EXISTS invoice_datetime timestamp")
    cr.execute("""
        UPDATE sale_order so SET invoice_datetime = sub.dt
          FROM (SELECT sol.order_id, MIN(COALESCE(am.nebim_sent_date, am.create_date)) AS dt
                  FROM sale_order_line_invoice_rel rel
                  JOIN sale_order_line sol ON sol.id = rel.order_line_id
                  JOIN account_move_line aml ON aml.id = rel.invoice_line_id
                  JOIN account_move am ON am.id = aml.move_id
                 WHERE am.state = 'posted' AND am.move_type = 'out_invoice'
                 GROUP BY sol.order_id) sub
         WHERE so.id = sub.order_id
    """)
    _logger.info("Satış: %s siparişin fatura tarihi dolduruldu", cr.rowcount)
