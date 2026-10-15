import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # Finansal senkron cron'u canlıda Ağustos 2026'dan beri pasifti (Odoo üst üste hata veren cron'u
    # kapatır; kayıt noupdate olduğu için yükseltme de açmıyordu). Yeniden açılır, saatlik çalışır.
    cr.execute("""
        UPDATE ir_cron
           SET active = TRUE, interval_number = 1, interval_type = 'hours',
               nextcall = (now() AT TIME ZONE 'UTC') + interval '5 minutes',
               failure_count = 0, first_failure_date = NULL
         WHERE id = (SELECT res_id FROM ir_model_data
                      WHERE module = 'trendyol_integration' AND name = 'cron_trendyol_sync_financials')
    """)
    _logger.info("Trendyol: finansal senkron cron'u yeniden açıldı (saatlik): %s", cr.rowcount)
