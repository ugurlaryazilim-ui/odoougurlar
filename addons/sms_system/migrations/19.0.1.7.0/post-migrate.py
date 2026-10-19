import logging

_logger = logging.getLogger(__name__)

STUCK_PREFIX = 'Gönderim yarıda kesildi%'


def migrate(cr, version):
    """Yalnız veri: eski kodun 'hata' yazdığı takılı kampanya kayıtlarını 'belirsiz' yap.

    Eski sürüm 15 dk'dan uzun 'gönderiliyor'da kalan kampanya kayıtlarını `error` yapıyordu; bu kayıtlar
    Turatel'e gitmiş olabilir ve "Hatalıları Yeniden Gönder" onları mükerrer gönderirdi. Belirsiz kayıt
    hiçbir yolla yeniden gönderilmez (retry_count = 3). İdempotent; başka hiçbir kayda ya da ayara dokunmaz.
    """
    cr.execute("""
        UPDATE sms_system_message
           SET state = 'uncertain', retry_count = 3
         WHERE campaign_id IS NOT NULL
           AND state = 'error'
           AND error LIKE %s
    """, (STUCK_PREFIX,))
    _logger.info('sms_system: %s takılı kampanya kaydı belirsiz yapıldı', cr.rowcount)
