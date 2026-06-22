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
    substitute_product_id = fields.Many2one(
        'product.product',
        string='İkame Ürün (Paket)',
        help='Pazaryerinden bu ürün sipariş edildiğinde, '
             'sipariş satırına bu ürün yazılır.',
    )
    substituted_by_ids = fields.One2many(
        'product.product', 'substitute_product_id',
        string='Bu Ürünü İkame Edenler',
        help='Hangi ürünler sipariş edildiğinde bu ürün yazılıyor?',
    )

    # ------------------------------------------------------------------
    #  Merkezi ürün arama — tüm pazaryerleri bu metodu kullanır
    # ------------------------------------------------------------------
    @api.model
    def find_by_marketplace_barcode(self, code):
        """Barkod/SKU ile ürün bul + ikame desteği.

        Arama sırası:
            1. barcode (tam eşleşme)
            2. nebim_barcode (tam → ilike)
            3. default_code (tam eşleşme)

        Bulunan üründe ``substitute_product_id`` varsa ikame ürünü döndürür.
        """
        if not code:
            return self.browse()

        code = str(code).strip()

        # 1. barcode
        product = self.search([('barcode', '=', code)], limit=1)
        # 2. nebim_barcode
        if not product and 'nebim_barcode' in self._fields:
            product = self.search([('nebim_barcode', '=', code)], limit=1)
            if not product:
                product = self.search([('nebim_barcode', 'ilike', code)], limit=1)
        # 3. default_code
        if not product:
            product = self.search([('default_code', '=', code)], limit=1)

        # 4. İkame kontrolü
        if product and product.substitute_product_id:
            _logger.info(
                "Paket ikame: %s (%s) → %s (%s)",
                product.display_name, code,
                product.substitute_product_id.display_name,
                product.substitute_product_id.barcode,
            )
            return product.substitute_product_id

        return product or self.browse()

    @api.model
    def batch_find_by_marketplace_barcodes(self, codes):
        """Toplu barkod arama — {code: product} dict döndürür.

        Her pazaryerinin batch lookup'ı yerine bu metod kullanılır.
        """
        result = {}
        for code in codes:
            if code and code not in result:
                result[code] = self.find_by_marketplace_barcode(code)
        return result
