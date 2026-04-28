import logging
from collections import defaultdict

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# ─── Module-Level Cache ───────────────────────────────────────────────
# Odoo AbstractModel proxy nesneleri instance attribute tutmaz,
# bu yüzden cache modül seviyesinde saklanır.
_CACHE = {
    'loaded': False,
    'attrs': {},         # name → attribute record
    'vals': {},          # (attr_id, val_name) → value record
    'lines': {},         # (tmpl_id, attr_id) → line record
    'categs': {},        # name → category record
    'taxes': {},         # (type_use, amount) → tax record
    'tax_groups': {},    # name → tax_group record
    'barcodes': set(),   # tüm mevcut barkodlar
}


class ProductProcessor(models.AbstractModel):
    """
    Nebim → Odoo ürün processor.
    Performans: Modül-seviyesi cache ile batch başına ~5 sorgu/ürün.
    """
    _name = 'odoougurlar.product.processor'
    _description = 'Nebim Ürün Processor'

    PRODUCT_ATT_MAP = {
        'ProductAtt01Desc': 'Tedarikçi',
        'ProductAtt02Desc': 'Reyon',
        'ProductAtt03Desc': 'Cinsiyet',
        'ProductAtt04Desc': 'Ürün Grubu',
        'ProductAtt05Desc': 'Sezon/Yıl',
        'ProductAtt06Desc': 'Marka',
        'ProductAtt07Desc': 'Yaka',
        'ProductAtt08Desc': 'Materyal',
        'ProductAtt09Desc': 'Kalıp',
        'ProductAtt10Desc': 'Desen',
        'ProductAtt11Desc': 'Boy',
        'ProductAtt12Desc': 'Kol Bilgisi',
        'ProductAtt13Desc': 'Paça Boyu',
        'ProductAtt14Desc': 'Bel Bilgisi',
        'ProductAtt15Desc': 'Kumaş Türü',
        'ProductAtt16Desc': 'Menşei',
        'ProductAtt17Desc': 'Yaş Grubu',
        'ProductAtt18Desc': 'Renk Detay',
        'ProductAtt19Desc': 'Cep Tipi',
        'ProductAtt20Desc': 'Web Color',
    }

    # =================================================================
    #  Cache
    # =================================================================
    @api.private
    def _init_cache(self):
        """Batch başında 1 kez çağrılır — tüm lookup'ları _CACHE'e yükler."""
        global _CACHE
        _logger.info("Cache yükleniyor...")

        _CACHE['attrs'] = {}
        for attr in self.env['product.attribute'].sudo().search([]):
            _CACHE['attrs'][attr.name] = attr

        _CACHE['vals'] = {}
        for val in self.env['product.attribute.value'].sudo().search([]):
            _CACHE['vals'][(val.attribute_id.id, val.name)] = val

        _CACHE['categs'] = {}
        for cat in self.env['product.category'].sudo().search([]):
            _CACHE['categs'][cat.name] = cat

        _CACHE['taxes'] = {}
        company_id = self.env.company.id
        for tax in self.env['account.tax'].sudo().search([
            ('company_id', '=', company_id),
        ]):
            _CACHE['taxes'][(tax.type_tax_use, tax.amount)] = tax

        _CACHE['tax_groups'] = {}
        for tg in self.env['account.tax.group'].sudo().search([]):
            _CACHE['tax_groups'][tg.name] = tg

        _CACHE['barcodes'] = set()
        self.env.cr.execute(
            "SELECT barcode FROM product_product WHERE barcode IS NOT NULL"
        )
        _CACHE['barcodes'] = {r[0] for r in self.env.cr.fetchall()}

        _CACHE['lines'] = {}
        _CACHE['loaded'] = True

        _logger.info(
            "Cache yüklendi: %d attr, %d val, %d categ, %d tax, %d barcode",
            len(_CACHE['attrs']), len(_CACHE['vals']),
            len(_CACHE['categs']), len(_CACHE['taxes']),
            len(_CACHE['barcodes']),
        )

    @api.private
    def _ensure_cache(self):
        """Cache yoksa oluştur (test butonu için)."""
        if not _CACHE.get('loaded'):
            self._init_cache()

    # =================================================================
    #  Ana İşlem
    # =================================================================
    def process_products(self, nebim_items, attributes=None):
        """Nebim ürün listesini işler (test butonu)."""
        self._ensure_cache()
        stats = {'processed': 0, 'created': 0, 'updated': 0, 'failed': 0}

        grouped = defaultdict(list)
        for item in nebim_items:
            code = (item.get('ItemCode') or '').strip()
            if code:
                grouped[code].append(item)
            else:
                stats['failed'] += 1

        _logger.info("Nebim'den %d satır → %d benzersiz ürün grubu",
                     len(nebim_items), len(grouped))

        for item_code, variants in grouped.items():
            stats['processed'] += 1
            try:
                with self.env.cr.savepoint():
                    result = self._process_product_group(item_code, variants)
                    if result == 'created':
                        stats['created'] += 1
                    elif result == 'updated':
                        stats['updated'] += 1
            except Exception as e:
                stats['failed'] += 1
                _logger.error("Ürün işleme hatası [%s]: %s", item_code, str(e))

        return stats

    @api.private
    def _process_product_group(self, item_code, variants):
        """Bir ItemCode → 1 template + N varyant."""
        self._ensure_cache()

        ProductTemplate = self.env['product.template'].sudo()

        first = variants[0]
        product_name = (
            first.get('ItemDescription')
            or first.get('ItemName')
            or first.get('Description')
            or item_code
        )

        prices = [float(v.get('Price', 0) or v.get('RetailPrice', 0) or 0) for v in variants]
        list_price = max(prices) if prices else 0.0

        template = ProductTemplate.search([('nebim_code', '=', item_code)], limit=1)
        if not template:
            template = ProductTemplate.search([('default_code', '=', item_code)], limit=1)

        template_vals = {
            'name': product_name,
            'default_code': item_code,
            'nebim_code': item_code,
            'nebim_synced': True,
            'nebim_last_sync': fields.Datetime.now(),
            'type': 'consu',
            'is_storable': True,
        }
        if list_price > 0:
            template_vals['list_price'] = list_price

        # İç Notlar — ItemNotes_Text → description
        notes_text = (first.get('ItemNotes_Text') or '').strip()
        if notes_text:
            template_vals['description'] = notes_text

        # Kategori — cache
        category_name = (first.get('ProductAtt04Desc') or '').strip()
        if category_name:
            categ = self._cached_category(category_name)
            if categ:
                template_vals['categ_id'] = categ.id

        # KDV — cache
        vat_rate = first.get('VatRate')
        if vat_rate is not None and float(vat_rate) > 0:
            sale_tax, purchase_tax = self._cached_taxes(float(vat_rate))
            if sale_tax:
                template_vals['taxes_id'] = [(6, 0, [sale_tax.id])]
            if purchase_tax:
                template_vals['supplier_taxes_id'] = [(6, 0, [purchase_tax.id])]

        if template:
            template.write(template_vals)
            result = 'updated'
        else:
            template = ProductTemplate.create(template_vals)
            result = 'created'

        # Renk + Beden
        color_values = set()
        size_values = set()
        for var in variants:
            color = (var.get('ColorDescription') or var.get('ColorCode') or '').strip()
            size = (var.get('ItemDim1Code') or '').strip()
            if color:
                color_values.add(color)
            if size:
                size_values.add(size)

        if color_values:
            self._sync_attribute_line(template, 'Renk', color_values)
        if size_values:
            self._sync_attribute_line(template, 'Beden', size_values)

        # Varyant detayları
        self._map_variant_details(template, variants)

        # ProductAtt nitelikleri
        self._sync_product_attributes(template, first)

        return result

    # =================================================================
    #  ProductAtt Nitelikleri
    # =================================================================
    @api.private
    def _sync_product_attributes(self, template, nebim_item):
        """ProductAtt01-20 → no_variant nitelikler."""
        for json_field, attr_name in self.PRODUCT_ATT_MAP.items():
            value = (nebim_item.get(json_field) or '').strip()
            if not value:
                continue
            self._sync_attribute_line(
                template, attr_name, {value},
                create_variant='no_variant'
            )

    # =================================================================
    #  Attribute Line (Cache'li)
    # =================================================================
    @api.private
    def _sync_attribute_line(self, template, attr_name, values, create_variant='always'):
        """Template'e attribute line ekler/günceller — cache ile 0 sorgu."""
        global _CACHE

        Attribute = self.env['product.attribute'].sudo()
        AttrValue = self.env['product.attribute.value'].sudo()
        AttrLine = self.env['product.template.attribute.line'].sudo()

        # Attribute: cache
        attribute = _CACHE['attrs'].get(attr_name)
        if not attribute:
            attribute = Attribute.create({
                'name': attr_name,
                'display_type': 'radio' if create_variant == 'always' else 'select',
                'create_variant': create_variant,
            })
            _CACHE['attrs'][attr_name] = attribute

        # Values: cache
        value_ids = []
        for val_name in sorted(values):
            if not val_name:
                continue
            cache_key = (attribute.id, val_name)
            attr_val = _CACHE['vals'].get(cache_key)
            if not attr_val:
                attr_val = AttrValue.create({
                    'attribute_id': attribute.id,
                    'name': val_name,
                })
                _CACHE['vals'][cache_key] = attr_val
            value_ids.append(attr_val.id)

        if not value_ids:
            return

        # Line: cache
        line_key = (template.id, attribute.id)
        attr_line = _CACHE['lines'].get(line_key)
        if attr_line is None:
            attr_line = AttrLine.search([
                ('product_tmpl_id', '=', template.id),
                ('attribute_id', '=', attribute.id),
            ], limit=1)
            _CACHE['lines'][line_key] = attr_line or False

        if attr_line:
            existing_ids = set(attr_line.value_ids.ids)
            new_ids = set(value_ids) - existing_ids
            if new_ids:
                all_ids = list(existing_ids | set(value_ids))
                attr_line.write({'value_ids': [(6, 0, all_ids)]})
        else:
            new_line = AttrLine.create({
                'product_tmpl_id': template.id,
                'attribute_id': attribute.id,
                'value_ids': [(6, 0, value_ids)],
            })
            _CACHE['lines'][line_key] = new_line

    # =================================================================
    #  Varyant Detay (Barcode cache'li)
    # =================================================================
    @api.private
    def _map_variant_details(self, template, nebim_variants):
        """Varyantlara ItemSku, Barcode eşler — barcode cache ile 0 sorgu."""
        global _CACHE

        for var in nebim_variants:
            color = (var.get('ColorDescription') or var.get('ColorCode') or '').strip()
            size = (var.get('ItemDim1Code') or '').strip()
            sku = (var.get('ItemSku') or '').strip()
            barcode1 = (var.get('Barcode1') or '').strip()
            barcode2 = (var.get('Barcode2') or '').strip()
            color_code = (var.get('ColorCode') or '').strip()

            barcode = barcode1 if barcode1 else barcode2

            variant = self._find_variant(template, color, size)
            if not variant:
                continue

            update_vals = {}

            if sku:
                update_vals['default_code'] = sku

            # Barcode: cache-based duplicate check (0 sorgu!)
            if barcode and barcode not in _CACHE['barcodes']:
                update_vals['barcode'] = barcode
                _CACHE['barcodes'].add(barcode)

            nebim_barcodes = []
            if barcode1:
                nebim_barcodes.append(barcode1)
            if barcode2 and barcode2 != barcode1:
                nebim_barcodes.append(barcode2)
            if nebim_barcodes:
                update_vals['nebim_barcode'] = ','.join(nebim_barcodes)

            if color_code and size:
                update_vals['nebim_variant_code'] = f"{color_code}-{size}"
            elif color_code:
                update_vals['nebim_variant_code'] = color_code

            if update_vals:
                try:
                    variant.write(update_vals)
                except Exception as e:
                    if 'barcode' in str(e).lower() or 'unique' in str(e).lower():
                        update_vals.pop('barcode', None)
                        if update_vals:
                            variant.write(update_vals)
                    else:
                        raise

    @api.private
    def _find_variant(self, template, color_name, size_name):
        """Renk ve bedene göre doğru varyantı bulur."""
        variants = template.product_variant_ids
        if len(variants) == 1:
            return variants[0]

        for variant in variants:
            variant_attrs = {}
            for ptav in variant.product_template_attribute_value_ids:
                variant_attrs[ptav.attribute_id.name] = ptav.name

            color_match = (not color_name) or variant_attrs.get('Renk') == color_name
            size_match = (not size_name) or variant_attrs.get('Beden') == size_name

            if color_match and size_match:
                return variant
        return None

    # =================================================================
    #  Kategori + Vergi (Cache'li)
    # =================================================================
    @api.private
    def _cached_category(self, category_name):
        """Kategori: cache'den al veya oluştur."""
        global _CACHE
        if not category_name:
            return None
        categ = _CACHE['categs'].get(category_name)
        if not categ:
            categ = self.env['product.category'].sudo().create({'name': category_name})
            _CACHE['categs'][category_name] = categ
        return categ

    @api.private
    def _cached_taxes(self, vat_rate):
        """KDV: cache'den al veya oluştur."""
        global _CACHE
        company = self.env.company
        rate = float(vat_rate)

        sale_tax = _CACHE['taxes'].get(('sale', rate))
        if not sale_tax:
            tg = self._cached_tax_group(rate)
            sale_tax = self.env['account.tax'].sudo().create({
                'name': f"%{int(rate)} KDV (Dahil)",
                'type_tax_use': 'sale',
                'amount_type': 'percent',
                'amount': rate,
                'price_include_override': 'tax_included',
                'tax_group_id': tg.id,
                'company_id': company.id,
            })
            _CACHE['taxes'][('sale', rate)] = sale_tax

        purchase_tax = _CACHE['taxes'].get(('purchase', rate))
        if not purchase_tax:
            tg = self._cached_tax_group(rate)
            purchase_tax = self.env['account.tax'].sudo().create({
                'name': f"%{int(rate)} KDV Alış (Dahil)",
                'type_tax_use': 'purchase',
                'amount_type': 'percent',
                'amount': rate,
                'price_include_override': 'tax_included',
                'tax_group_id': tg.id,
                'company_id': company.id,
            })
            _CACHE['taxes'][('purchase', rate)] = purchase_tax

        return sale_tax, purchase_tax

    @api.private
    def _cached_tax_group(self, rate):
        """Vergi grubu: cache'den al veya oluştur."""
        global _CACHE
        name = f'KDV %{int(rate)}'
        tg = _CACHE['tax_groups'].get(name)
        if not tg:
            for n, r in _CACHE['tax_groups'].items():
                if str(int(rate)) in n:
                    return r
            tg = self.env['account.tax.group'].sudo().create({'name': name})
            _CACHE['tax_groups'][name] = tg
        return tg
