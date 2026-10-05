"""Teslim tarihi alanı eklenmeden önce açılmış siparişlere söz verilen tarih ata.

Boş kalırsa eski siparişler hiç "Geciken" sayılmıyordu. Tarih = oluşturma + varsayılan gün.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'ugurlar_tailor.default_days'")
    row = cr.fetchone()
    try:
        days = int(row[0]) if row and row[0] else 3
    except ValueError:
        days = 3
    cr.execute("""
        UPDATE ugurlar_tailor_order
           SET promised_date = (create_date AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Istanbul')::date + %s
         WHERE promised_date IS NULL AND create_date IS NOT NULL
    """, (days,))
    _logger.info('Terzi: %s eski siparişe teslim tarihi atandı (+%s gün)', cr.rowcount, days)
