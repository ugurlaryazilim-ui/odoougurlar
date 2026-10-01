import logging

_logger = logging.getLogger(__name__)

# Akış (stream) senkronu 30.09.2026 ~16:20 (TR) itibarıyla lastModified aralığını +3 saat
# kaydırılmış gönderiyordu: pencere hep ileride kaldığı için hiç paket gelmedi ama last_sync
# ilerledi. Kaçan siparişler / durum değişiklikleri ilk turda alınsın diye geri sarılır.
_REWIND_TO = '2026-09-30 13:00:00'  # UTC (TR 16:00)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "UPDATE trendyol_store SET last_sync = %s "
        "WHERE active AND (last_sync IS NULL OR last_sync > %s) RETURNING name",
        (_REWIND_TO, _REWIND_TO))
    names = [r[0] for r in cr.fetchall()]
    _logger.info("Trendyol: last_sync %s UTC'ye geri alındı (kaçan siparişler için): %s",
                 _REWIND_TO, ', '.join(names) or '-')
