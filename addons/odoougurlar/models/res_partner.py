import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _auto_init(self):
        # Modül güncellemesi (-u) henüz yapılmamışsa web arayüzünün çökmesini engellemek için sütunları DB'ye doğrudan ekle
        self.env.cr.execute("""
            ALTER TABLE res_partner ADD COLUMN IF NOT EXISTS nebim_customer_code VARCHAR;
            ALTER TABLE res_partner ADD COLUMN IF NOT EXISTS nebim_customer_sent BOOLEAN DEFAULT FALSE;
            ALTER TABLE res_partner ADD COLUMN IF NOT EXISTS nebim_address_id VARCHAR;
        """)
        return super()._auto_init()

    def _register_hook(self):
        res = super()._register_hook()
        try:
            self.env.cr.execute("""
                ALTER TABLE res_partner ADD COLUMN IF NOT EXISTS nebim_customer_code VARCHAR;
                ALTER TABLE res_partner ADD COLUMN IF NOT EXISTS nebim_customer_sent BOOLEAN DEFAULT FALSE;
                ALTER TABLE res_partner ADD COLUMN IF NOT EXISTS nebim_address_id VARCHAR;
            """)
        except Exception as e:
            _logger.warning("res_partner sütun kontrol hatası: %s", e)
        return res

    nebim_customer_code = fields.Char(
        string='Nebim Cari Kodu',
        index=True,
        copy=False,
        help='Nebim V3 sistemindeki Cari Kodu (CurrAccCode)',
    )
    nebim_customer_sent = fields.Boolean(
        string='Nebim Cari Açıldı',
        default=False,
        copy=False,
        help='Bu cari Nebim ile senkronize edildi mi?',
    )
    nebim_address_id = fields.Char(
        string='Nebim Adres ID',
        copy=False,
        help='Nebim PostalAddress ID',
    )
