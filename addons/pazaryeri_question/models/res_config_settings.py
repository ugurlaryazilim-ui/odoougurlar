from odoo import fields, models


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
        string='Otomatik Senkronizasyon',
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
