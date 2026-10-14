import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)

_NEBIM_PARTNER_COLUMNS = (
    ('nebim_customer_code', 'VARCHAR'),
    ('nebim_customer_sent', 'BOOLEAN DEFAULT FALSE'),
    ('nebim_address_id', 'VARCHAR'),
)


def _ensure_nebim_columns(cr):
    """Eksik Nebim sütunlarını ekler (modül -u edilmeden web arayüzü çökmesin).

    ALTER TABLE, IF NOT EXISTS olsa da res_partner'ı ACCESS EXCLUSIVE kilitler: her registry
    yüklemesinde (her worker, her modül yükseltmesi) çalışınca cron'ların tuttuğu kilitte zaman
    aşımına düşüp transaction'ı bozuyordu. Önce katalogdan bakılır; sütunlar varsa ALTER yapılmaz.
    """
    cr.execute("""
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'res_partner' AND table_schema = current_schema()
           AND column_name IN %s
    """, (tuple(c for c, _t in _NEBIM_PARTNER_COLUMNS),))
    existing = {row[0] for row in cr.fetchall()}
    missing = [(c, t) for c, t in _NEBIM_PARTNER_COLUMNS if c not in existing]
    if not missing:
        return
    # Savepoint: kilit zaman aşımı registry yüklemesinin geri kalanını bozmasın
    with cr.savepoint():
        for column, col_type in missing:
            cr.execute('ALTER TABLE res_partner ADD COLUMN IF NOT EXISTS "%s" %s' % (column, col_type))


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _auto_init(self):
        _ensure_nebim_columns(self.env.cr)
        return super()._auto_init()

    def _register_hook(self):
        res = super()._register_hook()
        try:
            _ensure_nebim_columns(self.env.cr)
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
