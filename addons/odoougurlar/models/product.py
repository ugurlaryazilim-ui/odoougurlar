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
    substitute_product_id = fields.Many2one(
        'product.product',
        string='İkame Ürün (Paket)',
        related='product_variant_ids.substitute_product_id',
        readonly=False,
    )


class ProductProduct(models.Model):
    _inherit = 'product.product'

    nebim_variant_code = fields.Char(
        string='Nebim Varyant Kodu',
        index=True,
        help='Nebim ItemDim1Code/ItemDim2Code birleşim kodu',
    )
    # NEDEN: tek barkodlu kayıtlarda `nebim_barcode = x` ve ORM aramaları için btree.
    nebim_barcode = fields.Char(
        string='Nebim Barkod',
        index='btree_not_null',
        help='Nebim tarafından atanan barkod (virgülle birleşik liste olabilir)',
    )
    # DIKKAT: Sorgulardaki ifade bu indeksteki ifadeyle BİREBİR aynı olmalı
    # (`string_to_array(replace(nebim_barcode, ' ', ''), ',')`), yoksa planner indeksi kullanmaz
    # ve her okutma/senkron ürün tablosunu baştan sona tarar. Sorgu `&&` / `@>` kullanır
    # (`x = ANY(ifade)` GIN ile çalışmaz). Yeni stored alan değil; yükseltme yalnız indeks kurar.
    _nebim_barcode_list_idx = models.Index(
        "USING gin ((string_to_array(replace(nebim_barcode, ' ', ''), ',')))")
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
    def _search_nebim_barcodes(self, codes):
        """nebim_barcode listesinde ``codes``'tan biri TAM eşleşen ürünler (ORM sırasıyla).

        Tek barkodlu kayıt da bir "listedir"; ayrı `=` sorgusu gerekmez. Yalnız id'ler SQL'le
        (GIN ifade indeksiyle) bulunur, aktiflik/sıra ORM aramasına bırakılır.
        """
        # DIKKAT: ifade `_nebim_barcode_list_idx` ile birebir aynı olmalı (bkz. alan açıklaması).
        self.env.cr.execute("""
            SELECT id FROM product_product
            WHERE string_to_array(replace(nebim_barcode, ' ', ''), ',') && %s::text[]
        """, [list(codes)])
        return self.search([('id', 'in', [row[0] for row in self.env.cr.fetchall()])])

    @api.model
    def _normalized_code_matches(self, codes):
        """Tire/boşluk/slash temizlenmiş, büyük-küçük harf duyarsız eşleşme: {kod: product_id}.

        Amazon SKU: 001t2-0003000634-30 ↔ Odoo: 001T2-0003-0006-34/30. Tam tarama yapar (ifade
        indeksi yok); bu yüzden yalnız önceki adımlarda bulunamayan kodlar için ve TEK sorguyla çağrılır.
        """
        by_clean = {}
        for code in codes:
            clean = code.replace('-', '').replace(' ', '').replace('/', '').lower()
            if clean:
                by_clean.setdefault(clean, []).append(code)
        if not by_clean:
            return {}

        def norm(col):
            return "LOWER(REPLACE(REPLACE(REPLACE(%s, '-', ''), ' ', ''), '/', ''))" % col

        self.env.cr.execute("""
            SELECT id, %s, %s, %s FROM product_product
            WHERE active = True AND (%s = ANY(%%(c)s) OR %s = ANY(%%(c)s) OR %s = ANY(%%(c)s))
            ORDER BY id
        """ % ((norm('default_code'), norm('barcode'), norm('nebim_barcode')) * 2),
            {'c': list(by_clean)})
        matches = {}
        for pid, *values in self.env.cr.fetchall():
            for value in values:
                for code in by_clean.get(value, ()):
                    matches.setdefault(code, pid)
        return matches

    @api.model
    def find_by_marketplace_barcode(self, code):
        """Barkod/SKU ile ürün bul + ikame desteği (tek kod için toplu aramanın kısayolu)."""
        if not code:
            return self.browse()
        return self.batch_find_by_marketplace_barcodes([code])[code]

    @api.model
    def batch_find_by_marketplace_barcodes(self, codes):
        """Toplu barkod arama — {code: product} dict döndürür (bulunamayan için boş kayıt).

        Arama sırası (kod başına, ilk bulunan kazanır):
            1. barcode (tam eşleşme)
            2. nebim_barcode (tek değer ya da virgüllü listede tam eşleşme)
            3. default_code (tam eşleşme)
            3b. tire/boşluk/slash temizlenmiş, harf duyarsız eşleşme
        Bulunan üründe ``substitute_product_id`` varsa ikame ürünü döndürür.
        Her adım tüm kodlar için TEK sorgudur (eskiden kod başına 3-4 tam tarama).
        """
        keys = {code: str(code).strip() for code in codes if code}
        pending = set(keys.values())
        found = {}  # temizlenmiş kod → product.product

        def collect(products, values_of):
            for product in products:
                for value in values_of(product):
                    if value in pending and value not in found:
                        found[value] = product
            pending.difference_update(found)

        collect(self.search([('barcode', 'in', list(pending))]), lambda p: [p.barcode])
        if pending:
            collect(self._search_nebim_barcodes(pending),
                    lambda p: p.nebim_barcode.replace(' ', '').split(','))
        if pending:
            collect(self.search([('default_code', 'in', list(pending))]), lambda p: [p.default_code])
        if pending:
            for code, pid in self._normalized_code_matches(pending).items():
                found[code] = self.browse(pid)
                _logger.info("Normalize eşleşme (tire/slash/case): %s → %s", code, pid)

        result = {}
        for code, key in keys.items():
            product = found.get(key, self.browse())
            if product.substitute_product_id:
                _logger.info(
                    "Paket ikame: %s (%s) → %s (%s)",
                    product.display_name, code,
                    product.substitute_product_id.display_name,
                    product.substitute_product_id.barcode,
                )
                product = product.substitute_product_id
            result[code] = product
        return result
