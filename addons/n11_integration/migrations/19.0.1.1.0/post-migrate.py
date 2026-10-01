import logging
from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Order = env['n11.order']

    # 1) Mevcut kayıtlar: sipariş tarihi (eskiden senkron anı yazılıyordu), paket / kalem bilgileri,
    #    fatura tipi ve VKN. Odoo siparişlerine dokunulmaz.
    date_fixed = refreshed = 0
    for rec in Order.search([('raw_data', '!=', False)]):
        try:
            with cr.savepoint():
                pkgs = rec._get_packages()
                if not pkgs:
                    continue
                vals = {}
                order_date = Order._n11_order_date(pkgs.values())
                if order_date and rec.order_date != order_date:
                    vals['order_date'] = order_date
                    date_fixed += 1
                header = Order._order_header_vals(rec.store_id, rec.order_number, pkgs, order_date)
                for key in ('invoice_type', 'tax_number', 'tax_office'):
                    if header.get(key) and rec[key] != header[key]:
                        vals[key] = header[key]
                if vals:
                    rec.write(vals)
                rec._apply_packages(pkgs)
                refreshed += 1
        except Exception as e:
            _logger.warning("N11 migration: %s güncellenemedi: %s", rec.order_number, e)
    _logger.info("N11 migration: %d sipariş yenilendi, %d sipariş tarihi düzeltildi", refreshed, date_fixed)

    # 2) Eski senkron yalnızca son 1 günün siparişlerine bakıyordu; kaçırılmış iptal / kargo / teslim
    #    durumlarını yakalamak için ilk senkron son 15 günün değişikliklerini tarasın.
    #    (Odoo'da olmayan eski siparişler yeniden açılmaz.)
    catch_up = fields.Datetime.now() - timedelta(days=15)
    cr.execute("UPDATE n11_store SET last_sync = %s WHERE active AND (last_sync IS NULL OR last_sync > %s)",
               (catch_up, catch_up))

    # 3) Cron kaydı artık noupdate: aralığı mağaza ayarından yeniden uygula
    stores = env['n11.store'].search([], limit=1)
    if stores:
        stores._update_cron_interval()
