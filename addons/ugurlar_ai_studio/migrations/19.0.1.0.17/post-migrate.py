import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Kaldırılan 'saving' kuyruğu cron'unu sil (cron.xml noupdate=1 olduğu için
    Odoo güncellemede kendisi silmez; kalırsa var olmayan metodu çağırıp hata verir)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref('ugurlar_ai_studio.cron_save_sessions', raise_if_not_found=False)
    if cron:
        cron.unlink()
        _logger.info('ugurlar_ai_studio: cron_save_sessions kaldırıldı')
