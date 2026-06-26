import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ------------------------------------------------------------------
    #  Ek Özellikler — Ayarlar
    # ------------------------------------------------------------------
    show_sku_on_product_page = fields.Boolean(
        string='SKU Ürün Sayfasında Göster',
        config_parameter='ek_ozellikler.show_sku',
        help='E-ticaret ürün detay sayfasında SKU (İç Referans) bilgisini gösterir.',
    )
    show_barcode_on_product_page = fields.Boolean(
        string='Barkod Ürün Sayfasında Göster',
        config_parameter='ek_ozellikler.show_barcode',
        help='E-ticaret ürün detay sayfasında barkod bilgisini gösterir.',
    )
