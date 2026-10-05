import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    """Terzi modülü MSSQL bağlantı ayarları — Nebim ERP fatura view'ına bağlanır."""
    _inherit = 'res.config.settings'

    # ── MSSQL Bağlantı Ayarları ──
    tailor_mssql_server = fields.Char(
        string='SQL Server Adresi',
        config_parameter='ugurlar_tailor.mssql_server',
        help='Nebim SQL Server IP veya hostname (ör: 192.168.0.100)',
    )
    tailor_mssql_port = fields.Integer(
        string='SQL Port',
        config_parameter='ugurlar_tailor.mssql_port',
        default=1433,
    )
    tailor_mssql_database = fields.Char(
        string='SQL Veritabanı',
        config_parameter='ugurlar_tailor.mssql_database',
        help='Nebim veritabanı adı',
    )
    tailor_mssql_user = fields.Char(
        string='SQL Kullanıcı',
        config_parameter='ugurlar_tailor.mssql_user',
        groups='base.group_system',
    )
    tailor_mssql_password = fields.Char(
        string='SQL Şifre',
        config_parameter='ugurlar_tailor.mssql_password',
        groups='base.group_system',
    )
    tailor_mssql_view_name = fields.Char(
        string='View Adı',
        config_parameter='ugurlar_tailor.mssql_view_name',
        default='vw_TerziFaturalar',
        help='Nebim ERP\'deki fatura view adı (ör: vw_TerziFaturalar)',
    )

    # ── Sipariş / Bildirim ──
    tailor_default_days = fields.Integer(
        string='Varsayılan Teslim Süresi (gün)', config_parameter='ugurlar_tailor.default_days', default=3,
    )
    tailor_sms_ready_enabled = fields.Boolean(
        string='Hazır Olunca SMS Gönder', config_parameter='ugurlar_tailor.sms_ready_enabled',
        help='Sipariş "Hazır" olunca müşteri cep telefonuna SMS (SMS modülü / Turatel) gönderilir',
    )
    tailor_sms_reminder_enabled = fields.Boolean(
        string='Teslim Alınmayanlara Hatırlatma', config_parameter='ugurlar_tailor.sms_reminder_enabled',
    )
    tailor_sms_reminder_days = fields.Integer(
        string='Kaç gün sonra', config_parameter='ugurlar_tailor.sms_reminder_days', default=3,
    )
    tailor_sms_reminder_max = fields.Integer(
        string='En fazla hatırlatma', config_parameter='ugurlar_tailor.sms_reminder_max', default=2,
    )

    # ── Reyon Ayarları ──
    reyon_manager_ids = fields.Many2many(
        related='company_id.reyon_manager_ids',
        readonly=False,
        string='Reyon Yöneticileri'
    )
