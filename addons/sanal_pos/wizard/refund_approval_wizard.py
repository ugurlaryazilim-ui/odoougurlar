# -*- coding: utf-8 -*-
"""İade Onay Geçişi (tasarım §3.3, §6; KK-15, KK-16, KK-17). Yalnız Sanal POS Yöneticisi.

Paratika iadeyi finans onayına bırakır (QUERYTRANSACTION ``IP``...), eski sürüm ise REFUND
``00`` yanıtını "İade edildi" sayardı. Bu sihirbaz mevcut "İade edildi" satırlarını Paratika'daki
gerçek durumla karşılaştırır (``action_compare``: salt okunur, iş verisi yazmaz) ve yönetici
onayıyla onaylı OLMAYANLARI "Onay bekliyor"a çevirir (``action_apply``).

# NEDEN: migrate içinde dış API yok; geçiş yönetici düğmesiyle (bkz. KARARLAR K-12). Migrate
# betiği Paratika'ya sorgu atarsa deploy'u kilitler/zaman aşımına uğratır ve sonucu görülemez.

Karar kuralı toleranssızdır (bkz. ``sanal.pos.payment._refund_match_decisive``): bir "Başarılı"
satırı yalnız işlem no (``ref``) ile bire bir eşleşen Paratika işlemi onaylı DEĞİLSE çevrilir.
Tutar/zamana dayalı (ref'siz) eşleşme, önceki bir denemenin işlemini yakalayabilir; parayı geri
alınabilir göstermek çift iadeye yol açar. Belirsizse satır dokunulmaz ve rapora "Atlanacak"
yazılır (elle incelenir). Tek satırın yanlış çevrilmesi yeniden "Onay bekliyor"dan "Başarılı"ya
dönebilir (normal senkron AP'yi görünce satırı tamamlar); yanlış "Reddedildi" geri dönmez.
"""
import logging
import time

from markupsafe import Markup

from odoo import fields, models
from odoo.exceptions import UserError

from ..models.sanal_pos_payment import PAYMENT_STATES, REFUND_RECOMPUTE_STATES
from ..tools import format_try

_logger = logging.getLogger(__name__)

ICP_KEY = 'sanal_pos.refund_approval_migration_at'
# Her aday için bir Paratika çağrısı yapılır; HTTP isteği süre sınırına takılmasın diye çağrılar
# bu bütçeyle sınırlanır. Kalanlar raporlanır ve işlem tekrar çalıştırılabilir (idempotent).
TIME_BUDGET = 60            # saniye
BUSY_REASON = 'devam eden işlem var'
MULTI_REASON = 'aynı ödemede birden fazla dönüşecek satır'
AMBIGUOUS_REASON = 'belirsiz eşleşme, elle inceleyin'
NOT_FOUND_REASON = "Paratika'da eşleşen iade işlemi bulunamadı, elle inceleyin"
QUERY_REASON = 'sorgu hatası'
BUDGET_REASON = 'süre sınırı, sorgulanmadı; işlemi tekrar çalıştırın'
STATE_LABELS = {'pending_approval': 'Onay bekliyor', 'done': 'Başarılı', 'rejected': 'Reddedildi'}


class SanalPosRefundApprovalWizard(models.TransientModel):
    _name = 'sanal.pos.refund.approval.wizard'
    _description = 'Sanal POS İade Onay Geçişi'

    state = fields.Selection(
        [('draft', 'Hazır'), ('compared', 'Karşılaştırıldı'), ('applied', 'Uygulandı')],
        string='Aşama', required=True, default='draft', readonly=True)
    report_html = fields.Html(string='Rapor', readonly=True)

    # ---------------------------------------------------------------- yardımcılar
    def _check_manager(self, allow_su=False):
        """Yönetici denetimi. sudo ile oluşturulmuş sihirbaz yönetici olmayan kullanıcıda çalışmaz.

        NEDEN: ``allow_su`` yalnız salt okunur karşılaştırma içindir (kod yolu, ör. test/shell);
        RPC sudo üretemez. Uygulama (para durumunu değiştirir) sudo muafiyeti tanımaz (tasarım §6.2).
        """
        self.ensure_one()
        if not (allow_su and self.env.su):
            self.env['sanal.pos.payment']._check_refund_manager()

    def _candidates(self):
        """Eski sürümün "İade edildi" saydığı satırı olan ödemeler (panel ve iptal satırı hariç)."""
        return self.env['sanal.pos.payment'].sudo().search([
            ('state', 'in', REFUND_RECOMPUTE_STATES),
            ('refund_ids', 'any', [('state', '=', 'done'), ('source', '=', 'odoo'),
                                   ('kind', '=', 'refund')]),
        ], order='id')

    @staticmethod
    def _candidate_lines(payment):
        return payment.refund_ids.filtered(
            lambda l: l.state == 'done' and l.source == 'odoo' and l.kind == 'refund').sorted('id')

    def _plan(self, payment, result):
        """Ödemenin aday satırları için planlanan eylem (saf; veri yazmaz).

        Öğe: ``{'line', 'tran', 'paratika', 'action': 'same'|'convert'|'skip', 'note'}``.
        """
        lines = self._candidate_lines(payment)
        if not result.get('ok'):
            return [{'line': l, 'tran': None, 'paratika': QUERY_REASON, 'action': 'skip',
                     'note': QUERY_REASON} for l in lines]
        financial = [t for t in result.get('transactions') or []
                     if t.get('kind') in ('refund', 'void')
                     and payment._to_amount2(t.get('amount')) is not None]
        busy = payment._has_blocking_refund_line(include_done=False)
        plan = []
        for line in lines:
            used = {l.provider_ref for l in payment.refund_ids if l != line and l.provider_ref}
            tran, how = payment._match_refund_transaction(line, financial, used)
            item = {'line': line, 'tran': tran, 'paratika': '', 'action': 'skip', 'note': ''}
            plan.append(item)
            if not tran:
                item['paratika'] = 'belirsiz eşleşme' if how == 'ambiguous' else 'bulunamadı'
                item['note'] = AMBIGUOUS_REASON if how == 'ambiguous' else NOT_FOUND_REASON
                continue
            item['paratika'] = payment._refund_raw_status(tran)
            # DIKKAT: ref'siz eşleşme bir "Başarılı" satırı çevirmeye yetmez (modül açıklaması).
            # Satırın kendi işlem nosu varsa ve sorguda görünmüyorsa, aynı tutarlı başka işlem
            # onun yerine geçmez; zaman da kanıtlanamıyorsa satır elle incelenir.
            strong = tran.get('kind') == line.kind and (how == 'ref' or (
                not line.provider_ref
                and payment._refund_match_decisive(line, tran, how, need_time=True)))
            if not strong:
                item['note'] = AMBIGUOUS_REASON
            elif tran.get('status') == 'approved':
                item['action'] = 'same'
            elif busy:
                item['note'] = BUSY_REASON
            else:
                item['action'] = 'convert'
        converts = [i for i in plan if i['action'] == 'convert']
        if len(converts) > 1:
            # Kısmi benzersiz indeks: ödemede tek "Onay bekliyor" satırı olabilir
            for item in converts:
                item.update(action='skip', note=MULTI_REASON)
        return plan

    def _query_payment(self, payment):
        """Salt okunur Paratika sorgusu; hata raise etmez (sorgu hatası olarak planlanır)."""
        return payment._call_provider_safely('query_status', 'iade onay geçişi sorgusunda')

    # ---------------------------------------------------------------- rapor
    def _report_row(self, payment, item, outcome=None):
        line = item['line']
        when = line.done_at or line.create_date
        if outcome:
            action = outcome
        elif item['action'] == 'same':
            action = 'Değişmez (AP)'
        elif item['action'] == 'convert':
            action = "Onay bekliyor'a alınacak"
        else:
            action = 'Atlanacak: %s' % item['note']
        return {'payment': payment, 'amount': format_try(line.amount),
                'date': payment._format_local(when), 'odoo': STATE_LABELS.get(line.state, line.state),
                'paratika': item['paratika'] or '-', 'action': action, 'kind': item['action']}

    def _applied_row(self, payment, item, skip_note=None):
        """Uygulama sonrası rapor satırı: çevrilen satırın gerçek sonucu, atlananlar 'Atlandı'.

        ``skip_note`` verilirse çevrilecekken yapılamayan satırlar bu sebeple atlanmış gösterilir.
        """
        if skip_note and item['action'] == 'convert':
            item = dict(item, action='skip', note=skip_note)
        if item['action'] == 'convert':
            state = item['line'].state
            outcome = {'pending_approval': "Onay bekliyor'a alındı",
                       'rejected': "Reddedildi'ye alındı (Paratika reddetmiş)"}.get(
                state, 'Durum: %s' % STATE_LABELS.get(state, state))
        elif item['action'] == 'same':
            outcome = 'Değişmez (AP)'
        else:
            outcome = 'Atlandı: %s' % item['note']
        return self._report_row(payment, item, outcome)

    @staticmethod
    def _html_table(headers, rows):
        head = Markup('').join(Markup('<th>%s</th>') % h for h in headers)
        body = Markup('').join(
            Markup('<tr>%s</tr>') % Markup('').join(Markup('<td>%s</td>') % c for c in row)
            for row in rows)
        return Markup('<table class="table table-sm table-bordered"><thead><tr>%s</tr></thead>'
                      '<tbody>%s</tbody></table>') % (head, body)

    def _inconsistent_payments(self):
        """Yeniden hesap kuralının mevcut durumdan farklı sonuç verdiği ödemeler (§6.1 ikinci bölüm)."""
        payments = self.env['sanal.pos.payment'].sudo().search([
            ('state', 'in', REFUND_RECOMPUTE_STATES),
            '|', ('refund_ids', '!=', False), ('state', '!=', 'paid')], order='id')
        return payments.filtered(lambda p: p._expected_refund_state() != p.state)

    def _render_report(self, rows, notes):
        labels = dict(PAYMENT_STATES)
        counts = {kind: sum(1 for r in rows if r['kind'] == kind) for kind in ('same', 'convert', 'skip')}
        headers = ['Talep No', 'Fatura', 'İade tutarı', 'İade tarihi', 'Odoo durumu',
                   'Paratika durumu', 'Planlanan eylem']
        parts = [Markup('<p>%s satır: %s değişmez, %s dönüşecek/dönüştürüldü, %s atlanacak/atlandı.</p>') % (
            len(rows), counts['same'], counts['convert'], counts['skip'])]
        parts += [Markup('<p><strong>%s</strong></p>') % note for note in notes]
        parts.append(self._html_table(headers, [
            (r['payment'].name, r['payment'].invoice_no, r['amount'], r['date'], r['odoo'],
             r['paratika'], r['action']) for r in rows]))
        mismatched = self._inconsistent_payments()
        parts.append(Markup('<h5>Durum tutarsızlıkları (yeniden hesap kuralı)</h5>'))
        if mismatched:
            parts.append(Markup('<p>Bu kayıtlar yalnızca bildirilir; geçiş bunlara dokunmaz.</p>'))
            parts.append(self._html_table(
                ['Talep No', 'Fatura', 'Mevcut durum', 'Beklenen durum'],
                [(p.name, p.invoice_no, labels.get(p.state, p.state),
                  labels.get(p._expected_refund_state(), p._expected_refund_state()))
                 for p in mismatched]))
        else:
            parts.append(Markup('<p>Tutarsız kayıt yok.</p>'))
        return Markup('').join(parts)

    # ---------------------------------------------------------------- karşılaştır (salt okunur)
    def action_compare(self):
        """Paratika'yı sorgular ve planlanan eylemleri raporlar. İş verisi yazmaz, commit etmez."""
        self._check_manager(allow_su=True)
        started = time.monotonic()
        rows, notes, skipped = [], [], 0
        for payment in self._candidates():
            if time.monotonic() - started > TIME_BUDGET:
                skipped += 1
                rows += [self._report_row(payment, {'line': l, 'tran': None, 'paratika': 'sorgulanmadı',
                                             'action': 'skip', 'note': BUDGET_REASON})
                         for l in self._candidate_lines(payment)]
                continue
            rows += [self._report_row(payment, item) for item in self._plan(payment, self._query_payment(payment))]
        if skipped:
            notes.append('%s ödeme süre sınırı nedeniyle sorgulanmadı; Paratika ile Karşılaştır\'ı '
                         'tekrar çalıştırın.' % skipped)
        self.write({'state': 'compared', 'report_html': self._render_report(rows, notes)})
        return self._reopen_action()

    # ---------------------------------------------------------------- uygula (yalnız yönetici)
    def action_apply(self):
        """Onaylı olmayan "Başarılı" satırları "Onay bekliyor"a çevirir; ödeme başına kilit + commit.

        Her ödeme yeniden sorgulanır (önizleme bayatlamış olabilir). Paratika çağrısı kilit
        DIŞINDA yapılır: kilit yalnız kısa DB işi (yeniden doğrulama + yazma) için tutulur.
        İdempotenttir: yalnız hâlâ onaylı olmayan "Başarılı" satırlar etkilenir.
        """
        self._check_manager()
        if self.state != 'compared':
            raise UserError('Önce "Paratika ile Karşılaştır" adımını çalıştırın ve raporu inceleyin.')
        Payment = self.env['sanal.pos.payment'].sudo()
        started = time.monotonic()
        rows, notes, unprocessed = [], [], 0
        for payment in self._candidates():
            if time.monotonic() - started > TIME_BUDGET:
                unprocessed += 1
                continue
            result = self._query_payment(payment)                    # kilit dışında
            plan = self._plan(payment, result)
            if not any(i['action'] == 'convert' for i in plan):
                rows += [self._applied_row(payment, i) for i in plan]
                continue
            rows += self._apply_payment(payment, result)
        self.env['ir.config_parameter'].sudo().set_param(ICP_KEY, fields.Datetime.to_string(
            fields.Datetime.now()))
        Payment._sp_commit()
        if unprocessed:
            notes.append('%s ödeme süre sınırı nedeniyle işlenmedi; Geçişi Uygula\'yı tekrar çalıştırın.'
                         % unprocessed)
        self.write({'state': 'compared' if unprocessed else 'applied',
                    'report_html': self._render_report(rows, notes)})
        return self._reopen_action()

    def _apply_payment(self, payment, result):
        """Tek ödeme: NOWAIT kilit -> yeniden doğrula -> dönüştür -> senkron -> commit."""
        if not payment._try_lock_nowait():
            return [self._applied_row(payment, i, 'kayıt kilitli, başka işlem sürüyor')
                    for i in self._plan(payment, result)]
        try:
            with self.env.cr.savepoint():
                payment.refund_ids.invalidate_recordset()
                payment.invalidate_recordset()
                plan = self._plan(payment, result)           # kilitten sonra yeniden doğrulama
                converts = [i for i in plan if i['action'] == 'convert']
                for item in converts:
                    line = item['line']
                    vals = payment._refund_bind_vals(line, item['tran'])
                    vals.update(state='pending_approval', done_at=False, pending_alert_sent=False)
                    line.write(vals)
                    payment._post_note(
                        "İade onay geçişi: %s iade Paratika'da onaylı görünmüyor; 'Onay bekliyor' "
                        "durumuna alındı (yönetici: %s)." % (format_try(line.amount), self.env.user.name))
                if converts:
                    # Normal senkron kuralları: açık red hemen 'Reddedildi', ödeme durumu yeniden hesaplanır
                    payment._apply_status(result)
        except Exception as exc:  # noqa: BLE001 - tek ödemenin hatası geçişi durdurmasın
            _logger.error('sanal_pos: iade onay geçişi hatası (%s), ödeme id=%s',
                          type(exc).__name__, payment.id)
            payment.refund_ids.invalidate_recordset()
            payment.invalidate_recordset()
            plan = self._plan(payment, result)
            rows = [self._applied_row(payment, i, 'işlem hatası, günlüğe bakın')
                    for i in plan]
        else:
            rows = [self._applied_row(payment, item) for item in plan]
        # NEDEN: ödeme başına commit; kilit bırakılır ve bir sonraki ödemenin Paratika çağrısı
        # açık kilit tutmaz. savepoint bloğunun DIŞINDA (commit savepoint'i düşürür).
        payment._sp_commit()
        return rows

    def _reopen_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'İade Onay Geçişi',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'dialog_size': 'extra-large'},
        }
