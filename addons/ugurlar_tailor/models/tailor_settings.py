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
