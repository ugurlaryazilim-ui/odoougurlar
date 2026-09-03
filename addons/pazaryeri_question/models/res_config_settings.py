from datetime import timedelta
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ─── Müşteri Soruları Ayarları ───────────────────────
    pq_show_hidden_customer_name = fields.Boolean(
        string='Gizli Müşteri Adını Göster',
        config_parameter='pazaryeri_question.show_hidden_customer_name',
        default=True,
        help='Trendyol\'da showUserName=false olan müşteriler için "Gizli Müşteri" gösterilsin mi?',
    )
    pq_auto_sync_enabled = fields.Boolean(
        string='Soru Otomatik Sync',
        config_parameter='pazaryeri_question.auto_sync_enabled',
        default=True,
        help='Cron ile otomatik soru senkronizasyonu açık/kapalı',
    )
    pq_sync_interval = fields.Integer(
        string='Sync Aralığı (dakika)',
        config_parameter='pazaryeri_question.sync_interval',
        default=30,
        help='Otomatik senkronizasyon aralığı (dakika)',
    )
    pq_answer_min_chars = fields.Integer(
        string='Min. Cevap Karakter',
        config_parameter='pazaryeri_question.answer_min_chars',
        default=10,
        help='Cevap için minimum karakter sayısı',
    )
    pq_answer_max_chars = fields.Integer(
        string='Max. Cevap Karakter',
        config_parameter='pazaryeri_question.answer_max_chars',
        default=2000,
        help='Cevap için maksimum karakter sayısı',
    )

    # ─── Bildirim ────────────────────────────────────────
    pq_notification_user_ids = fields.Many2many(
        related='company_id.pq_notification_user_ids',
        readonly=False,
        string='Müşteri Temsilcileri',
        help='Yeni pazaryeri sorusu geldiğinde bildirim alacak kullanıcılar',
    )

    def set_values(self):
        """Ayarlar kaydedildiğinde cron job'u da güncelle."""
        super().set_values()
        cron = self.env.ref('pazaryeri_question.cron_sync_marketplace_questions', raise_if_not_found=False)
        if cron:
            interval = max(self.pq_sync_interval or 5, 1)
            now = fields.Datetime.now()
            cron.sudo().write({
                'interval_number': interval,
                'interval_type': 'minutes',
                'active': self.pq_auto_sync_enabled,
                'nextcall': now + timedelta(minutes=interval),
            })
