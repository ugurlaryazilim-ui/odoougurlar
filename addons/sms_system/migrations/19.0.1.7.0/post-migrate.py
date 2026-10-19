import logging

_logger = logging.getLogger(__name__)

STUCK_PREFIX = 'Gönderim yarıda kesildi%'

# Eski kodun (19.0.1.6.0) iletilip iletilmediği belirsiz durumlar için yazdığı 'error' metinleri. Yeni kod bunları
# 'uncertain' yazar; eski kayıtlar 'error' kalırsa "Hatalıları Yeniden Gönder" ve _cron_retry_failed onları
# mükerrer gönderir (Ö-1). ConnectTimeout bağlantı kurulamadığını gösterir (kesin gitmedi) ve listede yok.
# ConnectionError eski kodda nedeni ayırmadığı için ihtiyatla belirsiz sayılır.
LEGACY_UNCERTAIN_ERRORS = tuple(
    'Turatel sunucusuna ulaşılamadı: %s' % name
    for name in ('ReadTimeout', 'ConnectionError', 'ChunkedEncodingError', 'ContentDecodingError',
                 'TooManyRedirects')
)
# Eski HTTP metni: 'Turatel HTTP 503 döndü'. Yeni metin '...döndü; iletilip iletilmediği belirsiz.' eşleşmez.
LEGACY_HTTP_ERROR = 'Turatel HTTP % döndü'
# Eski kod başlık eksik hatasını retry_count MAX olmadan yazıyordu; başlık girilince cron gönderirdi (KK-A22).
LEGACY_NO_ORIGINATOR = 'Mesaj başlığı (Originator) ayarlanmamış.'
MAX_RETRY = 3


def migrate(cr, version):
    """Yalnız veri: eski kodun 'hata' yazdığı, iletilmiş olabilecek kayıtları 'belirsiz' yap.

    - Eski sürüm 15 dk'dan uzun 'gönderiliyor'da kalan kampanya kayıtlarını `error` yapıyordu.
    - ReadTimeout, kopan bağlantı ve HTTP 200 dışı yanıtlarda da (tekli ve kampanya) `error` yazıyordu.
    Bu kayıtlar Turatel'e gitmiş olabilir; belirsiz kayıt hiçbir yolla yeniden gönderilmez (retry_count = 3).
    Başlık eksik eski kayıtların otomatik yeniden denemesi kapatılır. İdempotent; hiçbir ayara (ir.config_parameter) dokunmaz.
    """
    cr.execute("""
        UPDATE sms_system_message
           SET state = 'uncertain', retry_count = %s
         WHERE campaign_id IS NOT NULL
           AND state = 'error'
           AND error LIKE %s
    """, (MAX_RETRY, STUCK_PREFIX))
    _logger.info('sms_system: %s takılı kampanya kaydı belirsiz yapıldı', cr.rowcount)

    cr.execute("""
        UPDATE sms_system_message
           SET state = 'uncertain', retry_count = %s
         WHERE state = 'error'
           AND (error IN %s OR error LIKE %s)
    """, (MAX_RETRY, LEGACY_UNCERTAIN_ERRORS, LEGACY_HTTP_ERROR))
    _logger.info('sms_system: %s eski zaman aşımı/bağlantı/HTTP hatalı kayıt belirsiz yapıldı', cr.rowcount)

    cr.execute("""
        UPDATE sms_system_message
           SET retry_count = %s
         WHERE state = 'error'
           AND error = %s
           AND retry_count < %s
    """, (MAX_RETRY, LEGACY_NO_ORIGINATOR, MAX_RETRY))
    _logger.info('sms_system: %s eski başlık eksik kaydının otomatik yeniden denemesi kapatıldı', cr.rowcount)
