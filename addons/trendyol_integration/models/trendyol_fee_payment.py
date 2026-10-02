import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

FEE_PAYMENT_STATES = [
    ('pending', 'Bekliyor'),
    ('allocated', 'Dağıtıldı'),
    ('warning', 'Uyarı'),
    ('unmatched', 'Eşleşmedi'),
    ('no_invoice', 'Fatura Yok'),
    ('error', 'Hata'),
]

_NO_INVOICE_RECHECK_DAYS = 45   # fatura yoksa ödeme tarihinden sonra bu kadar gün günde bir yeniden sorgulanır
_ERROR_RETRY_HOURS = 1


class TrendyolFeePayment(models.Model):
    """Ödeme emri bazında hizmet bedeli (Uluslararası / Platform) dağıtım takibi.

    Odoo'daki tüm satış kayıtlarının ödeme numaraları buraya düşer; kuyruk en yeni ödemeden
    eskiye doğru partiler halinde işlenir (geçmişin tamamı, 60 gün sınırı olmadan).
    """
    _name = 'trendyol.fee.payment'
    _description = 'Trendyol Hizmet Bedeli Takibi'
    _order = 'payment_date desc, id desc'
    _rec_name = 'payment_order_id'

    store_id = fields.Many2one('trendyol.store', string='Mağaza', required=True, index=True, ondelete='cascade')
    payment_order_id = fields.Char(string='Ödeme No', required=True, index=True)
    payment_date = fields.Datetime(string='Ödeme Tarihi')
    state = fields.Selection(FEE_PAYMENT_STATES, string='Durum', default='pending', required=True, index=True)
    package_count = fields.Integer(string='Paket')
    invoice_count = fields.Integer(string='Fatura')
    invoice_amount = fields.Float(string='Fatura Tutarı', digits=(12, 2))
    allocated_amount = fields.Float(string='Dağıtılan', digits=(12, 2))
    note = fields.Char(string='Not')
    checked_at = fields.Datetime(string='Son Kontrol')
    check_count = fields.Integer(string='Kontrol Sayısı')

    _store_payment_unique = models.Constraint(
        'unique(store_id, payment_order_id)',
        'Aynı ödeme emri bir mağazada bir kez takip edilir.',
    )

    @api.model
    def _refresh(self, store):
        """Satış ve hizmet bedeli faturalarındaki ödeme numaralarını listeye ekler; yeni / tutarı
        değişmiş fatura gelen ödemeleri yeniden kuyruğa alır."""
        cr = self.env.cr
        cr.execute("""
            INSERT INTO trendyol_fee_payment (store_id, payment_order_id, payment_date, state,
                                              package_count, invoice_count, invoice_amount, allocated_amount,
                                              check_count, create_uid, create_date, write_uid, write_date)
            SELECT %(store)s, s.payment_order_id, MAX(s.payment_date), 'pending', 0, 0, 0, 0, 0,
                   %(uid)s, NOW() AT TIME ZONE 'UTC', %(uid)s, NOW() AT TIME ZONE 'UTC'
              FROM trendyol_settlement s
             WHERE s.store_id = %(store)s AND COALESCE(s.payment_order_id, '') <> ''
               AND ((s.source = 'settlements' AND s.transaction_type = 'sale')
                    OR (s.source = 'otherfinancials' AND s.transaction_type IN ('platform_fee', 'international_fee')))
             GROUP BY s.payment_order_id
            ON CONFLICT (store_id, payment_order_id) DO NOTHING
        """, {'store': store.id, 'uid': self.env.uid})
        added = cr.rowcount
        # Dağıtılmayı bekleyen fatura (yeni gelen / tutarı değişen) → ödeme yeniden kuyruğa
        cr.execute("""
            UPDATE trendyol_fee_payment p SET state = 'pending'
             WHERE p.store_id = %s AND p.state IN ('allocated', 'no_invoice', 'unmatched', 'warning')
               AND EXISTS (SELECT 1 FROM trendyol_settlement f
                            WHERE f.store_id = p.store_id AND f.payment_order_id = p.payment_order_id
                              AND f.source = 'otherfinancials'
                              AND f.transaction_type IN ('platform_fee', 'international_fee')
                              AND COALESCE(f.order_number, '') = '' AND COALESCE(f.shipment_package_id, '') = ''
                              AND COALESCE(f.allocation_state, 'pending') = 'pending'
                              AND (p.checked_at IS NULL OR f.write_date > p.checked_at))
        """, (store.id,))
        if added or cr.rowcount:
            self.invalidate_model()
            _logger.info("Trendyol hizmet bedeli takibi [%s]: %s yeni ödeme, %s ödeme yeniden kuyrukta",
                         store.name, added, cr.rowcount)

    @api.model
    def _queue(self, store, limit, force=False):
        """Sıradaki ödeme numaraları (en yeni ödemeden eskiye)."""
        now = fields.Datetime.now()
        states = ['pending']
        if force:
            states += ['warning', 'unmatched']
        domain = [('store_id', '=', store.id), '|', '|',
                  ('state', 'in', states),
                  '&', '&', ('state', '=', 'no_invoice'),
                  ('payment_date', '>=', now - timedelta(days=_NO_INVOICE_RECHECK_DAYS)),
                  ('checked_at', '<', now - timedelta(days=1)),
                  '&', ('state', '=', 'error'), ('checked_at', '<', now - timedelta(hours=_ERROR_RETRY_HOURS))]
        return self.search(domain, limit=limit).mapped('payment_order_id')

    @api.model
    def _update_state(self, store, payment_order_id, error=None):
        """Ödemenin faturalarına bakarak durumu yazar."""
        Settlement = self.env['trendyol.settlement']
        tracker = self.search([('store_id', '=', store.id), ('payment_order_id', '=', payment_order_id)], limit=1)
        if not tracker:
            tracker = self.create({'store_id': store.id, 'payment_order_id': payment_order_id})
        invoices = Settlement.search(Settlement._fee_invoice_domain(store) +
                                     [('payment_order_id', '=', payment_order_id)])
        rows = Settlement.search([('store_id', '=', store.id), ('source', '=', 'fee_allocation'),
                                  ('payment_order_id', '=', payment_order_id)])
        sales = Settlement.search([('store_id', '=', store.id), ('source', '=', 'settlements'),
                                   ('transaction_type', '=', 'sale'), ('payment_order_id', '=', payment_order_id)])
        vals = {
            'invoice_count': len(invoices),
            'invoice_amount': sum(invoices.mapped('debt')) - sum(invoices.mapped('credit')),
            'allocated_amount': sum(rows.mapped('debt')),
            'package_count': len(set(sales.mapped('shipment_package_id')) - {False, ''}),
            'checked_at': fields.Datetime.now(),
            'check_count': tracker.check_count + 1,
        }
        if sales and not tracker.payment_date:
            dates = [d for d in sales.mapped('payment_date') if d]
            vals['payment_date'] = max(dates) if dates else False
        if error:
            vals.update(state='error', note=str(error)[:250])
        elif not invoices:
            vals.update(state='no_invoice', note='Bu ödemeye hizmet bedeli faturası kesilmemiş (henüz)')
        else:
            states = set(invoices.mapped('allocation_state'))
            for state in ('warning', 'unmatched', 'pending'):
                if state in states:
                    problem = invoices.filtered(lambda r, s=state: r.allocation_state == s)[:1]
                    vals.update(state=state, note=(problem.allocation_note or '')[:250])
                    break
            else:
                vals.update(state='allocated', note=f"{len(invoices)} fatura, {len(rows)} paket satırı")
        tracker.write(vals)
        return tracker

    def action_retry(self):
        """Seçili ödemelerin dağıtımını yeniden dene (uyarı / eşleşmedi / fatura yok dahil)."""
        Settlement = self.env['trendyol.settlement']
        start = fields.Datetime.now()
        for store in self.mapped('store_id'):
            pos = self.filtered(lambda r: r.store_id == store).mapped('payment_order_id')
            Settlement._allocate_service_fees(store.get_api(), store, payment_order_ids=pos)
            Settlement._update_order_financial_summary(store, since=start - timedelta(minutes=1))
        return True

    def action_open_settlements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Ödeme {self.payment_order_id}',
            'res_model': 'trendyol.settlement',
            'view_mode': 'list,form',
            'domain': [('store_id', '=', self.store_id.id), ('payment_order_id', '=', self.payment_order_id)],
        }

    @api.model
    def cron_allocate_fees(self, limit=20):
        """15 dakikada bir: her mağazada sıradaki ödemeleri işler (geçmiş aşamalı tamamlanır)."""
        Settlement = self.env['trendyol.settlement']
        stores = self.env['trendyol.store'].search([('active', '=', True), ('sync_financials', '=', True)])
        for store in stores:
            start = fields.Datetime.now()
            try:
                Settlement._allocate_service_fees(store.get_api(), store, limit=limit)
                Settlement._update_order_financial_summary(store, since=start - timedelta(minutes=1))
                self.env.cr.commit()
            except Exception as e:
                self.env.cr.rollback()
                _logger.exception("Hizmet bedeli cron hatası [%s]: %s", store.name, e)
