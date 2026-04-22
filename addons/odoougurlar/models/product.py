import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    nebim_code = fields.Char(
        string='Nebim Ürün Kodu',
        index=True,
        help='Nebim ItemCode alanı ile eşlenen ürün kodu',
    )
    nebim_color_code = fields.Char(
        string='Nebim Renk Kodu',
        help='Nebim ColorCode alanı',
    )
    nebim_last_sync = fields.Datetime(
        string='Son Nebim Senkronizasyonu',
        readonly=True,
        help='Bu ürünün Nebim ile son senkronize edildiği tarih/saat',
    )
    nebim_synced = fields.Boolean(
        string='Nebim Senkronize',
        default=False,
        help='Bu ürün Nebim ile senkronize edildi mi?',
    )


class ProductProduct(models.Model):
    _inherit = 'product.product'

    nebim_variant_code = fields.Char(
        string='Nebim Varyant Kodu',
        index=True,
        help='Nebim ItemDim1Code/ItemDim2Code birleşim kodu',
    )
    nebim_barcode = fields.Char(
        string='Nebim Barkod',
        help='Nebim tarafından atanan barkod',
    )
