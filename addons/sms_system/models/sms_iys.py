import logging
import time
from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.smartadm import SmartAdmClient, SmartAdmError

_logger = logging.getLogger(__name__)

SESSION_TTL = timedelta(minutes=13)   # SmartADM oturumu 15 dk; biraz önce yenile
REQUEST_GAP = 0.15                    # istekler arası bekleme (≈400/dk; hesap sınırı 1000/dk)
GUARD_MIN = 20                        # hata oranı koruması en az bu kadar istekten sonra devreye girer
GUARD_RATIO = 0.5                     # "kişi yok" oranı bunu aşarsa toplu sorgu durur (SmartADM %60 hata = 24 saat blok)
GUARD_PAUSE = timedelta(hours=6)
FRESH = timedelta(hours=24)           # ticari gönderimden önce izin bundan eskiyse yeniden sorgulanır
REPORT_WINDOW = timedelta(days=7)


class SmsSystemIys(models.AbstractModel):
    """İYS (SmartADM) işlemleri: ayarlar, oturum önbelleği, sorgu/senkron."""
    _name = 'sms.system.iys'
    _description = 'SMS İYS Servisi'

    @api.model
    def _icp(self):
        return self.env['ir.config_parameter'].sudo()

    @api.model
    def _enabled(self):
        return self._icp().get_param('sms_system.iys_enabled') == 'True'

    @api.model
    def _client(self):
        icp = self._icp()
        session_id = None
        at = icp.get_param('sms_system.iys_session_at')
        if at and fields.Datetime.now() - fields.Datetime.to_datetime(at) < SESSION_TTL:
            session_id = icp.get_param('sms_system.iys_session') or None

        def remember(sid):
            icp.set_param('sms_system.iys_session', sid)
            icp.set_param('sms_system.iys_session_at', fields.Datetime.to_string(fields.Datetime.now()))

        return SmartAdmClient(
            icp.get_param('sms_system.iys_customer_code', ''), icp.get_param('sms_system.iys_username', ''),
            icp.get_param('sms_system.iys_password', ''), url=icp.get_param('sms_system.iys_url') or None,
            store=icp.get_param('sms_system.iys_store', ''), session_id=session_id, on_session=remember)

    @api.model
    def _paused_until(self):
        value = self._icp().get_param('sms_system.iys_paused_until')
        until = fields.Datetime.to_datetime(value) if value else None
        return until if until and until > fields.Datetime.now() else None

    @api.model
    def test_connection(self):
        client = self._client()
        client.session_id = None
        client.login()
        return True

    # ── Sorgu ──

    @api.model
    def refresh_contacts(self, contacts, deadline=None, guard=True):
        """Kişilerin İYS SMS iznini sorgula ve yaz. Süre dolunca durur.

        Dönen: {'done', 'approved', 'rejected', 'not_found', 'errors', 'stopped': None|'time'|'guard'|'error'}
        guard: "kişi yok" cevapları çoğunluktaysa durdur (SmartADM yüksek hata oranında hesabı 24 saat bloklar).
        """
        stats = {'done': 0, 'approved': 0, 'rejected': 0, 'not_found': 0, 'errors': 0, 'stopped': None}
        if not contacts:
            return stats
        client = self._client()
        for contact in contacts:
            if deadline and time.monotonic() > deadline:
                stats['stopped'] = 'time'
                break
            try:
                res = client.query(contact.mobile)
            except SmartAdmError as e:
                stats['errors'] += 1
                _logger.warning('İYS sorgusu başarısız (%s): %s', contact.id, e)
                if not e.retryable or stats['errors'] >= 3:
                    stats['stopped'] = 'error'
                    stats['error'] = str(e)
                    break
                continue
            stats['done'] += 1
            if not res['found']:
                stats['not_found'] += 1
            elif res['status'] in ('approved', 'rejected'):
                stats[res['status']] += 1
            contact.sudo().write({'iys_status': res['status'], 'iys_checked_at': fields.Datetime.now()})
            if guard and stats['done'] >= GUARD_MIN and stats['not_found'] / stats['done'] > GUARD_RATIO:
                stats['stopped'] = 'guard'
                self._icp().set_param('sms_system.iys_paused_until',
                                      fields.Datetime.to_string(fields.Datetime.now() + GUARD_PAUSE))
                _logger.warning('İYS toplu sorgu durduruldu: %s/%s numara İYS kaydında yok (hesap blok riskine karşı)',
                                stats['not_found'], stats['done'])
                break
            time.sleep(REQUEST_GAP)
        return stats

    # ── Artımlı senkron (/report2) ──

    @api.model
    def sync_report(self, deadline=None):
        """Son senkrondan bugüne izin hareketlerini çek (7 günlük pencereler, tüm sayfalar).

        Numaralar maskeli dönerse eşleştirilemez; o durumda 'masked' sayılır ve rehber sorgu ile güncellenir.
        """
        icp = self._icp()
        now = fields.Datetime.now()
        last = icp.get_param('sms_system.iys_last_report')
        start = fields.Datetime.to_datetime(last) if last else now - REPORT_WINDOW
        stats = {'rows': 0, 'updated': 0, 'masked': 0, 'windows': 0}
        client = self._client()
        Contact = self.env['sms.system.contact'].sudo().with_context(active_test=False)
        # İYS tarihleri Türkiye saati: pencereyi yerel saate çevir
        tz_shift = timedelta(hours=3)
        while start < now:
            end = min(start + REPORT_WINDOW - timedelta(seconds=1), now)
            page, max_page = 0, 0
            while True:
                rows, max_page = client.report2(start + tz_shift, end + tz_shift, page=page)
                for row in rows:
                    stats['rows'] += 1
                    if not row['mobile']:
                        stats['masked'] += 1
                        continue
                    contact = Contact.search([('mobile', '=', row['mobile'])], limit=1)
                    if contact and row['status'] in ('approved', 'rejected'):
                        contact.write({'iys_status': row['status'], 'iys_checked_at': now,
                                       'iys_source': row['source'] or contact.iys_source})
                        stats['updated'] += 1
                page += 1
                if page >= max_page or (deadline and time.monotonic() > deadline):
                    break
            stats['windows'] += 1
            if deadline and time.monotonic() > deadline and page < max_page:
                break  # pencere yarım kaldı; bir sonraki çalışmada aynı pencereden devam
            start = end + timedelta(seconds=1)
            icp.set_param('sms_system.iys_last_report', fields.Datetime.to_string(start))
        return stats

    # ── Cron ──

    @api.model
    def _cron_iys(self):
        """Yarım saatte bir: hiç sorgulanmamış rehber kişilerini sorgula, günde bir artımlı rapor senkronu."""
        if not self._enabled():
            return
        paused = self._paused_until()
        if paused:
            _logger.info('İYS toplu sorgu %s tarihine kadar beklemede', paused)
            return
        deadline = time.monotonic() + 240
        icp = self._icp()
        try:
            last = icp.get_param('sms_system.iys_last_report')
            if not last or fields.Datetime.now() - fields.Datetime.to_datetime(last) > timedelta(hours=20):
                stats = self.sync_report(deadline=deadline)
                _logger.info('İYS rapor senkronu: %s', stats)
            pending = self.env['sms.system.contact'].sudo().search(
                [('iys_checked_at', '=', False), ('opt_out', '=', False)], limit=1500, order='id')
            if pending:
                stats = self.refresh_contacts(pending, deadline=deadline)
                _logger.info('İYS ilk sorgu: %s', stats)
        except SmartAdmError as e:
            _logger.warning('İYS cron hatası: %s', e)
