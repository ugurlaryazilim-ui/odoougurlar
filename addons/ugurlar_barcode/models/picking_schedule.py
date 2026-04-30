"""Toplama Zamanlaması — Saatli batch oluşturma sistemi."""
import json
import logging
import pytz
from datetime import datetime, timedelta, time as dt_time

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

IST = pytz.timezone('Europe/Istanbul')

_logger = logging.getLogger(__name__)


class PickingSchedule(models.Model):
    _name = 'ugurlar.picking.schedule'
    _description = 'Toplama Zamanlaması'
    _order = 'sequence, id'

    name = fields.Char(string='Plan Adı', required=True, default='Günlük Toplama Planı')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Toplama Deposu', required=True,
        help='Siparişlerin toplandığı ana depo (İNTERNET MAĞAZA DEPO)',
    )
    fallback_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Yedek Depo',
        help='Ana depoda stok yoksa kontrol edilecek depo (HEYKEL MAĞAZA DEPO)',
    )

    schedule_line_ids = fields.One2many(
        'ugurlar.picking.schedule.line', 'schedule_id',
        string='Toplama Saatleri',
    )

    last_batch_date = fields.Date(string='Son Batch Tarihi', readonly=True)
    last_batch_time = fields.Char(string='Son Batch Saati', readonly=True)
    # Her saat dilimi için hangi tarihlerde çalıştığını tutan JSON
    # Örnek: {"09:30": "2026-04-29", "12:30": "2026-04-29"}
    completed_times_json = fields.Text(
        string='Tamamlanan Saatler (JSON)',
        default='{}',
        readonly=True,
        help='Bugün hangi saat dilimleri için batch oluşturulduğunu takip eden JSON alanı',
    )
    batch_tolerance_minutes = fields.Integer(
        string='Batch Tolerans (dk)',
        default=120,
        help='Zamanlanmış saatin üzerinden bu dakikadan fazla geçtiyse batch oluşturulmaz. '
             'Cron sarkmasına karşı güvenlik marjı.',
    )

    def action_create_batch_now(self):
        """Manuel buton: Şimdi toplama listesi oluştur."""
        self.ensure_one()

        # Önce teşhis bilgisi topla
        diag = self._diagnose_picking_status()
        batch = self._create_batch_for_current_window()

        if batch:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking.batch',
                'res_id': batch.id,
                'view_mode': 'form',
                'target': 'current',
            }

        # Detaylı hata mesajı oluştur
        msg = _('Bu zaman diliminde bekleyen sipariş bulunamadı.\n\n')
        msg += _('🔍 TEŞHİS RAPORU:\n')
        msg += _('• Depo: %s\n') % (self.warehouse_id.name or '—')
        msg += _('• Outgoing Picking Type: %s\n') % (diag.get('picking_type_name', 'BULUNAMADI ❌'))
        msg += _('• Toplam Outgoing Picking: %d\n') % diag.get('total_outgoing', 0)
        msg += _('• Uygun (confirmed/waiting/assigned + batch yok): %d\n') % diag.get('eligible', 0)
        msg += _('• Zaten batch\'e atanmış: %d\n') % diag.get('already_batched', 0)
        msg += _('• Done/İptal durumunda: %d\n') % diag.get('done_or_cancel', 0)
        msg += _('• Draft durumunda: %d\n') % diag.get('draft', 0)

        if diag.get('eligible', 0) > 0:
            msg += _('\n⚠️ %d uygun picking bulundu ama stok kontrolünden geçemedi:\n') % diag['eligible']
            msg += _('• Ana depoda stokta: %d\n') % diag.get('stock_available', 0)
            msg += _('• Yedek depoda stokta: %d\n') % diag.get('stock_fallback', 0)
            msg += _('• Stoksuz (unavailable): %d\n') % diag.get('stock_unavailable', 0)

        raise UserError(msg)

    def _diagnose_picking_status(self):
        """Teşhis: Neden batch oluşturulamıyor?"""
        self.ensure_one()
        result = {}

        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', self.warehouse_id.id),
            ('code', '=', 'outgoing'),
        ], limit=1)

        result['picking_type_name'] = picking_type.name if picking_type else 'BULUNAMADI'

        if not picking_type:
            return result

        Picking = self.env['stock.picking'].sudo()

        # Tüm outgoing picking'ler
        all_outgoing = Picking.search([('picking_type_id', '=', picking_type.id)])
        result['total_outgoing'] = len(all_outgoing)

        # State dağılımı
        result['eligible'] = len(all_outgoing.filtered(
            lambda p: p.state in ('confirmed', 'waiting', 'assigned') and not p.batch_id))
        result['already_batched'] = len(all_outgoing.filtered(
            lambda p: p.state in ('confirmed', 'waiting', 'assigned') and p.batch_id))
        result['done_or_cancel'] = len(all_outgoing.filtered(
            lambda p: p.state in ('done', 'cancel')))
        result['draft'] = len(all_outgoing.filtered(
            lambda p: p.state == 'draft'))

        # Uygun picking'lerin stok durumu
        eligible_pickings = all_outgoing.filtered(
            lambda p: p.state in ('confirmed', 'waiting', 'assigned') and not p.batch_id)

        stock_available = 0
        stock_fallback = 0
        stock_unavailable = 0

        for picking in eligible_pickings:
            status = picking._check_availability_status(
                self.warehouse_id, self.fallback_warehouse_id)
            if status == 'available':
                stock_available += 1
            elif status in ('other_warehouse', 'partial'):
                stock_fallback += 1
            else:
                stock_unavailable += 1

        result['stock_available'] = stock_available
        result['stock_fallback'] = stock_fallback
        result['stock_unavailable'] = stock_unavailable

        return result

    # ═══════════════════════════════════════════════════════
    # CRON
    # ═══════════════════════════════════════════════════════

    @api.model
    def _cron_run(self):
        """Cron tarafından çağrılır — aktif zamanlamaları kontrol et."""
        schedules = self.search([('active', '=', True)])
        _logger.info("Toplama zamanlayıcı cron başladı — %d aktif plan", len(schedules))
        for schedule in schedules:
            try:
                schedule._check_and_create_batch()
            except Exception as e:
                _logger.exception("Toplama zamanlayıcı hatası [%s]: %s",
                                  schedule.name, e)

    def _get_completed_times(self, today):
        """Bugün tamamlanan saat dilimlerini JSON'dan oku."""
        self.ensure_one()
        try:
            data = json.loads(self.completed_times_json or '{}')
        except (json.JSONDecodeError, TypeError):
            data = {}
        today_str = str(today)
        return data.get(today_str, {})

    def _mark_time_completed(self, today, time_key):
        """Bir saat dilimini tamamlandı olarak işaretle."""
        self.ensure_one()
        try:
            data = json.loads(self.completed_times_json or '{}')
        except (json.JSONDecodeError, TypeError):
            data = {}
        today_str = str(today)
        if today_str not in data:
            # Eski günleri temizle, sadece bugünü tut
            data = {today_str: {}}
        data[today_str][time_key] = True
        self.sudo().write({
            'completed_times_json': json.dumps(data),
            'last_batch_date': today,
            'last_batch_time': time_key,
        })

    @api.private
    def _check_and_create_batch(self):
        """Saat geldi mi kontrol et, geldiyse batch oluştur."""
        self.ensure_one()
        if not self.schedule_line_ids:
            return

        now = datetime.now(pytz.UTC).astimezone(IST)
        current_time = now.time()
        today = now.date()

        # Bugün tamamlanan saatler
        completed = self._get_completed_times(today)

        # Saatleri sıralı al
        sorted_times = self.schedule_line_ids.sorted(
            key=lambda l: l.hour * 60 + l.minute)

        for line in sorted_times:
            schedule_time = dt_time(line.hour, line.minute)
            time_key = f"{line.hour:02d}:{line.minute:02d}"

            # Şu an bu saatten sonra mıyız?
            if current_time >= schedule_time:
                # Bu saat için bugün batch oluşmuş mu?
                if completed.get(time_key):
                    continue

                # Tolerans kontrolü: çok geç mi?
                time_diff = (
                    current_time.hour * 60 + current_time.minute -
                    schedule_time.hour * 60 - schedule_time.minute
                )
                if time_diff > self.batch_tolerance_minutes:
                    _logger.debug(
                        "Toplama [%s] %s: %d dk geçmiş (tolerans: %d dk), atlanıyor",
                        self.name, time_key, time_diff, self.batch_tolerance_minutes)
                    continue

                _logger.info(
                    "Toplama [%s] %s saati geldi — batch oluşturuluyor...",
                    self.name, time_key)

                # Batch oluştur
                batch = self._create_batch_for_window(line, today, now)
                if batch:
                    self._mark_time_completed(today, time_key)
                    _logger.info(
                        "Toplama batch oluşturuldu: %s — %s [%s]",
                        batch.name, time_key, self.name)
                else:
                    _logger.info(
                        "Toplama [%s] %s: Uygun picking bulunamadı, batch oluşturulmadı",
                        self.name, time_key)

    # ═══════════════════════════════════════════════════════
    # BATCH OLUŞTURMA
    # ═══════════════════════════════════════════════════════

    def _get_time_window(self, target_line):
        """Verilen saat satırı için zaman penceresini hesapla.

        Döndürür: (window_start_dt, window_end_dt, window_label)
        """
        self.ensure_one()
        sorted_lines = self.schedule_line_ids.sorted(
            key=lambda l: l.hour * 60 + l.minute)

        if not sorted_lines:
            return None, None, ''

        target_idx = None
        for i, line in enumerate(sorted_lines):
            if line.id == target_line.id:
                target_idx = i
                break

        if target_idx is None:
            return None, None, ''

        now = datetime.now(pytz.UTC).astimezone(IST)
        today = now.date()

        # Pencere sonu = bu saat
        window_end = datetime.combine(
            today, dt_time(target_line.hour, target_line.minute))

        # Pencere başı = bir önceki saat (veya önceki günün son saati)
        if target_idx == 0:
            # İlk saat → pencere başı = önceki günün son saati + 1 dk
            last_line = sorted_lines[-1]
            prev_dt = datetime.combine(
                today - timedelta(days=1),
                dt_time(last_line.hour, last_line.minute))
            window_start = prev_dt + timedelta(minutes=1)
        else:
            prev_line = sorted_lines[target_idx - 1]
            window_start = datetime.combine(
                today,
                dt_time(prev_line.hour, prev_line.minute)) + timedelta(minutes=1)

        # Pencere etiketi
        start_str = window_start.strftime('%H:%M')
        end_str = window_end.strftime('%H:%M')
        window_label = f"{start_str}-{end_str}"

        return window_start, window_end, window_label

    def _create_batch_for_current_window(self):
        """Manuel buton için — şu anki zaman penceresindeki batch."""
        self.ensure_one()
        now = datetime.now(pytz.UTC).astimezone(IST)
        current_time = now.time()

        sorted_lines = self.schedule_line_ids.sorted(
            key=lambda l: l.hour * 60 + l.minute)

        # Şu anki saate en yakın henüz geçmemiş veya yeni geçmiş pencereyi bul
        target_line = None
        for line in sorted_lines:
            schedule_time = dt_time(line.hour, line.minute)
            if current_time >= schedule_time:
                target_line = line

        if not target_line:
            target_line = sorted_lines[-1] if sorted_lines else None

        if target_line:
            return self._create_batch_for_window(target_line, now.date(), now)
        return None

    def _create_batch_for_window(self, schedule_line, today, now_tz):
        """Belirli bir zaman penceresi icin batch olustur.

        Her zaman diliminde 2 ayri batch olusturulur:
        1) Ana depoda (INTERNET) stoku olanlar
        2) Yedek depoda (HEYKEL) stoku olanlar
        """
        self.ensure_one()

        window_start, window_end, window_label = self._get_time_window(
            schedule_line)
        if not window_start:
            return None

        # UTC'ye cevir (Odoo DB'de UTC saklar)
        window_start_utc = IST.localize(window_start).astimezone(
            pytz.UTC).replace(tzinfo=None)
        window_end_utc = IST.localize(window_end).astimezone(
            pytz.UTC).replace(tzinfo=None)

        # Bu depodan cikis yapacak, henuz batch'e atanmamis picking'ler
        Picking = self.env['stock.picking'].sudo()

        # Deponun outgoing picking type'ini bul
        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', self.warehouse_id.id),
            ('code', '=', 'outgoing'),
        ], limit=1)

        if not picking_type:
            _logger.warning("Depo %s icin outgoing picking type bulunamadi",
                            self.warehouse_id.name)
            return None

        # Batch'e atanmamis, onaylanmis picking'leri al
        # NOT: create_date filtresi YOK — tum bekleyen picking'ler dahil
        # Saat penceresi sadece batch'in NE ZAMAN olusturuldugunu belirler
        domain = [
            ('picking_type_id', '=', picking_type.id),
            ('state', 'in', ['confirmed', 'waiting', 'assigned']),
            ('batch_id', '=', False),
        ]
        pickings = Picking.search(domain)

        _logger.info(
            "Toplama [%s] pencere %s — picking_type: %s (id:%d), "
            "bulunan picking: %d",
            self.name, window_label, picking_type.display_name,
            picking_type.id, len(pickings))

        if not pickings:
            # Detaylı teşhis logu
            all_pickings = Picking.search([
                ('picking_type_id', '=', picking_type.id)])
            state_summary = {}
            for p in all_pickings:
                key = f"{p.state}{'(batch)' if p.batch_id else ''}"
                state_summary[key] = state_summary.get(key, 0) + 1
            _logger.info(
                "Toplama [%s] TEŞHİS — Tüm outgoing picking dağılımı: %s",
                self.name, state_summary)
            return None

        # Stok kontrolu ve gruplama
        primary_pickings = self.env['stock.picking']     # INTERNET DEPO'da var
        fallback_pickings = self.env['stock.picking']    # HEYKEL DEPO'da var
        unavailable_pickings = self.env['stock.picking'] # Hiçbir depoda stok yok

        for picking in pickings:
            status = picking._check_availability_status(
                self.warehouse_id, self.fallback_warehouse_id)

            if status == 'available':
                try:
                    picking.action_assign()
                except Exception:
                    pass
                primary_pickings |= picking
            elif status in ('other_warehouse', 'partial'):
                fallback_pickings |= picking
            else:
                unavailable_pickings |= picking

        _logger.info(
            "Toplama [%s] %s — stok dağılımı: ana=%d, yedek=%d, stoksuz=%d",
            self.name, window_label,
            len(primary_pickings), len(fallback_pickings), len(unavailable_pickings))

        created_batches = []

        # ── BATCH 1: ANA DEPO (INTERNET MAGAZA DEPO) ──
        # Stokta olan + stoksuz olanlar birlikte aynı batch'e eklenir
        # Depocu stok durumunu picking üzerinden görür
        all_primary = primary_pickings | unavailable_pickings
        if all_primary:
            batch_name = self.env['ir.sequence'].next_by_code(
                'ugurlar.picking.batch.route') or 'R00000'

            wh_name = self.warehouse_id.name or 'Ana Depo'
            parts = []
            if primary_pickings:
                parts.append(f'{len(primary_pickings)} stokta')
            if unavailable_pickings:
                parts.append(f'{len(unavailable_pickings)} stoksuz')
            detail = ', '.join(parts)

            batch = self.env['stock.picking.batch'].sudo().create({
                'name': batch_name,
                'picking_type_id': picking_type.id,
                'schedule_time': window_end_utc,
                'time_window': window_label,
                'company_id': self.warehouse_id.company_id.id,
                'source_info': f'{wh_name} - {len(all_primary)} siparis ({detail}) ({window_label})',
            })

            all_primary.write({
                'batch_id': batch.id,
                'batch_schedule_time': window_end_utc,
            })

            _logger.info(
                "Batch %s olusturuldu: %d siparis (%s) — %s (%s)",
                batch_name, len(all_primary), detail, wh_name, window_label)
            created_batches.append(batch)

        # ── BATCH 2: YEDEK DEPO (HEYKEL MAGAZA DEPO) ──
        if fallback_pickings and self.fallback_warehouse_id:
            batch_name = self.env['ir.sequence'].next_by_code(
                'ugurlar.picking.batch.route') or 'R00000'

            fb_name = self.fallback_warehouse_id.name or 'Yedek Depo'
            batch = self.env['stock.picking.batch'].sudo().create({
                'name': batch_name,
                'picking_type_id': picking_type.id,
                'schedule_time': window_end_utc,
                'time_window': window_label,
                'company_id': self.warehouse_id.company_id.id,
                'source_info': f'{fb_name} - {len(fallback_pickings)} siparis ({window_label})',
            })

            fallback_pickings.write({
                'batch_id': batch.id,
                'batch_schedule_time': window_end_utc,
            })

            _logger.info(
                "Batch %s olusturuldu: %d siparis — %s (%s)",
                batch_name, len(fallback_pickings), fb_name, window_label)
            created_batches.append(batch)

        if not created_batches:
            _logger.info(
                "Toplama [%s] %s — hiç picking bulunamadı",
                self.name, window_label)
            return None

        # Ilk batch'i dondur (UI yonlendirmesi icin)
        return created_batches[0]


class PickingScheduleLine(models.Model):
    _name = 'ugurlar.picking.schedule.line'
    _description = 'Toplama Saati'
    _order = 'hour, minute'

    _unique_time = models.Constraint(
        'UNIQUE(schedule_id, hour, minute)',
        'Aynı saat/dakika kombinasyonu zaten mevcut!',
    )

    schedule_id = fields.Many2one(
        'ugurlar.picking.schedule', string='Plan',
        required=True, ondelete='cascade',
    )
    hour = fields.Integer(string='Saat', required=True, default=9)
    minute = fields.Integer(string='Dakika', required=True, default=0)
    display_time = fields.Char(
        string='Saat', compute='_compute_display_time', store=True,
    )

    @api.depends('hour', 'minute')
    def _compute_display_time(self):
        for rec in self:
            rec.display_time = f"{rec.hour:02d}:{rec.minute:02d}"

    @api.constrains('hour', 'minute')
    def _check_time_range(self):
        for rec in self:
            if not (0 <= rec.hour <= 23):
                raise ValidationError(_('Saat 0-23 arasında olmalı'))
            if not (0 <= rec.minute <= 59):
                raise ValidationError(_('Dakika 0-59 arasında olmalı'))
