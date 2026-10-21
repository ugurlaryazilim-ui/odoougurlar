import logging
from collections import defaultdict

from odoo import models, fields, api
from odoo.tools import float_compare

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
    'barcodes': set(),   # mevcut barkodlar (kısıtlı yüklemede yalnız partidekiler)
    'sync_ids': set(),   # nebim_last_sync'i toplu güncellenecek template id'leri
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
    @api.model
    def _batch_names(self, rows):
        """Partideki satırların ihtiyaç duyacağı (değer adı, kategori adı, barkod) kümeleri.

        # DIKKAT: strip/yedek alan mantığı _process_product_group / _map_variant_details ile
        # birebir aynı olmalı; farklı olursa kısıtlı cache'te kayıt "yok" görünür ve
        # mükerrer nitelik değeri / kategori oluşur.
        """
        val_names, categ_names, barcodes = set(), set(), set()
        for row in rows:
            color = (row.get('ColorDescription') or row.get('ColorCode') or '').strip()
            size = (row.get('ItemDim1Code') or '').strip()
            val_names.update(n for n in (color, size) if n)
            for json_field in self.PRODUCT_ATT_MAP:
                value = (row.get(json_field) or '').strip()
                if value:
                    val_names.add(value)
            categ = (row.get('ProductAtt04Desc') or '').strip()
            if categ:
                categ_names.add(categ)
            barcodes.update(
                b for b in ((row.get('Barcode1') or '').strip(), (row.get('Barcode2') or '').strip()) if b)
        return val_names, categ_names, barcodes

    @api.private
    def _init_cache(self, rows=None):
        """Batch başında 1 kez çağrılır — lookup'ları _CACHE'e yükler.

        rows verilirse (kuyruk partisi) nitelik değeri, kategori ve barkod cache'i yalnız
        partideki adlarla sınırlı yüklenir; her 200'lük partide tüm tablolar yeniden
        okunmaz. rows verilmezse (test butonları) eski gibi tam yükleme yapılır.
        """
        global _CACHE
        _logger.info("Cache yükleniyor (%s)...", 'kısıtlı' if rows is not None else 'tam')

        restricted = rows is not None
        if restricted:
            val_names, categ_names, batch_barcodes = self._batch_names(rows)

        _CACHE['attrs'] = {}
        for attr in self.env['product.attribute'].sudo().search([]):
            _CACHE['attrs'][attr.name] = attr

        _CACHE['vals'] = {}
        val_domain = [('name', 'in', list(val_names))] if restricted else []
        if not restricted or val_names:
            for val in self.env['product.attribute.value'].sudo().search(val_domain):
                _CACHE['vals'][(val.attribute_id.id, val.name)] = val

        _CACHE['categs'] = {}
        categ_domain = [('name', 'in', list(categ_names))] if restricted else []
        if not restricted or categ_names:
            for cat in self.env['product.category'].sudo().search(categ_domain):
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
        if restricted:
            # Yalnız partideki barkodlar: tüm product_product.barcode'u Python'a çekmek yerine
            # indeksli ANY() sorgusu.
            if batch_barcodes:
                self.env.cr.execute(
                    "SELECT barcode FROM product_product WHERE barcode = ANY(%s)",
                    [list(batch_barcodes)],
                )
                _CACHE['barcodes'] = {r[0] for r in self.env.cr.fetchall()}
        else:
            self.env.cr.execute(
                "SELECT barcode FROM product_product WHERE barcode IS NOT NULL"
            )
            _CACHE['barcodes'] = {r[0] for r in self.env.cr.fetchall()}

        _CACHE['lines'] = {}
        _CACHE['sync_ids'] = set()
        _CACHE['restricted'] = restricted

        # Alan koruma ayarları (AI / Manuel başlık, açıklama, fiyat, kategori koruması)
        ICP = self.env['ir.config_parameter'].sudo()
        p_name = ICP.get_param('odoougurlar.nebim_prevent_name_update', 'True')
        p_desc = ICP.get_param('odoougurlar.nebim_prevent_description_update', 'True')
        p_price = ICP.get_param('odoougurlar.nebim_prevent_price_update', 'False')
        p_categ = ICP.get_param('odoougurlar.nebim_prevent_category_update', 'False')

        _CACHE['prevent_name'] = str(p_name).lower() in ('true', '1')
        _CACHE['prevent_desc'] = str(p_desc).lower() in ('true', '1')
        _CACHE['prevent_price'] = str(p_price).lower() in ('true', '1')
        _CACHE['prevent_categ'] = str(p_categ).lower() in ('true', '1')
        # Maliyet: Nebim Price2 (KDV dahil) varyantın standard_price alanına aynen yazılır
        _CACHE['update_cost'] = str(
            ICP.get_param('odoougurlar.nebim_sync_cost_enabled', 'False')).lower() in ('true', '1')

        _CACHE['loaded'] = True

        _logger.info(
            "Cache yüklendi: %d attr, %d val, %d categ, %d tax, %d barcode | Koruma: name=%s, desc=%s, price=%s, categ=%s | Maliyet: %s",
            len(_CACHE['attrs']), len(_CACHE['vals']),
            len(_CACHE['categs']), len(_CACHE['taxes']),
            len(_CACHE['barcodes']),
            _CACHE['prevent_name'], _CACHE['prevent_desc'], _CACHE['prevent_price'], _CACHE['prevent_categ'],
            _CACHE['update_cost'],
        )

    @api.private
    def _ensure_cache(self):
        """Cache yoksa oluştur (test butonu için)."""
        if not _CACHE.get('loaded'):
            self._init_cache()

    @api.private
    def _reset_cache(self):
        """Kısıtlı (parti) cache'i bırak: sonraki çağıran tam cache'i yeniden yükler.

        # DIKKAT: kısıtlı cache'te yalnız partideki adlar var; kuyruk dışı bir çağıran
        # (dashboard test butonları) onu görürse mevcut değer/kategori "yok" sanıp mükerrer
        # oluşturur. Kuyruk partisi bitince mutlaka çağrılır.
        """
        _CACHE['loaded'] = False
        _CACHE['restricted'] = False
        _CACHE['sync_ids'] = set()

    # =================================================================
    #  Karşılaştırmalı yazma + toplu nebim_last_sync
    # =================================================================
    @api.model
    def _changed_vals(self, record, vals):
        """vals içinden kayıttaki mevcut değerden gerçekten farklı olanları döndürür.

        NEDEN: Her senkronda karşılaştırmasız write, değişmeyen ürünlerde bile UPDATE,
        stored compute ve default_code inverse'ünü (varyantlara) tetikliyordu.
        """
        changed = {}
        for fname, new in vals.items():
            field = record._fields[fname]
            if field.type == 'many2many':
                # Yalnız tek (6, 0, ids) komutu kullanılıyor: küme karşılaştırması
                if set(record[fname].ids) != set(new[0][2]):
                    changed[fname] = new
            elif field.type == 'many2one':
                if record[fname].id != new:
                    changed[fname] = new
            elif field.type == 'float':
                # list_price vb.: Ürün Fiyatı ondalık hassasiyetiyle karşılaştır (0.001 farkı değişiklik değil)
                digits = self.env['decimal.precision'].precision_get('Product Price')
                if float_compare(record[fname] or 0.0, new or 0.0, precision_digits=digits) != 0:
                    changed[fname] = new
            elif field.type in ('char', 'text', 'html', 'selection'):
                # False/'' aynı sayılır; html için alanın kendi sanitize'ı uygulanır
                current = str(record[fname] or '')
                incoming = str(field.convert_to_cache(new, record) or '')
                if current != incoming:
                    changed[fname] = new
            elif record[fname] != new:
                changed[fname] = new
        return changed

    @api.private
    def _flush_last_sync(self):
        """Biriken template'lerin nebim_last_sync'ini tek SQL UPDATE ile yazar.

        NEDEN: nebim_last_sync her senkronda değiştiği için template.write içinde olursa
        her ürün için kesin UPDATE + write_date/mail tracking + compute tetikler. Burada
        ORM'siz yazılır; write_date'e de dokunulmaz (böylece write_date'e bakan pazaryeri/
        senkron kodları yalnız gerçekten değişen ürünleri görür).
        """
        ids = list(_CACHE.get('sync_ids') or ())
        _CACHE['sync_ids'] = set()
        if not ids:
            return
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "UPDATE product_template SET nebim_last_sync = %s WHERE id = ANY(%s)",
                    [fields.Datetime.now(), ids],
                )
            self.env['product.template'].browse(ids).invalidate_recordset(['nebim_last_sync'])
        except Exception as e:
            # Bilgi amaçlı alan: yazılamaması ürün senkronunu düşürmemeli
            _logger.warning("nebim_last_sync toplu güncellenemedi: %s", e)

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
                    result = self._process_product_group(
                        item_code, variants, defer_last_sync=True)
                    if result == 'created':
                        stats['created'] += 1
                    elif result == 'updated':
                        stats['updated'] += 1
            except Exception as e:
                stats['failed'] += 1
                _logger.error("Ürün işleme hatası [%s]: %s", item_code, str(e))

        self._flush_last_sync()
        return stats

    @api.private
    def _process_product_group(self, item_code, variants, defer_last_sync=False):
        """Bir ItemCode → 1 template + N varyant.

        defer_last_sync=True: nebim_last_sync güncellemesi çağıranın `_flush_last_sync`
        çağrısına bırakılır (kuyruk partisi başına tek UPDATE). False: hemen yazılır.
        """
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
            # ─── Alan Koruma Kontrolleri (Var Olan Ürün Güncellemesi) ───
            # Ayarlarda koruma işaretli ise Odoo'daki başlık / açıklama / fiyat / kategori korunur
            if _CACHE.get('prevent_name', True):
                template_vals.pop('name', None)
            if _CACHE.get('prevent_desc', True):
                template_vals.pop('description', None)
            if _CACHE.get('prevent_price', False):
                template_vals.pop('list_price', None)
            if _CACHE.get('prevent_categ', False):
                template_vals.pop('categ_id', None)

            # NEDEN: varyanta ItemSku geliyorsa varyant eşlemesi (_map_variant_details) iç
            # referansı belirler (tek varyantta template.default_code = varyant SKU'su). Template'e
            # ItemCode yazmak her senkronda inverse ile varyantı ItemCode'a çekip sonra SKU'ya
            # geri döndürüyordu (karşılaştırma hep "değişti" derdi). SKU yoksa ItemCode yazılır.
            if any((v.get('ItemSku') or '').strip() for v in variants):
                template_vals.pop('default_code', None)

            changed = self._changed_vals(template, template_vals)
            if changed:
                template.write(changed)
            result = 'updated'
        else:
            # Yeni ürün: İlk kez oluşturulurken tüm alanlar Nebim'den atanır
            template_vals['nebim_last_sync'] = fields.Datetime.now()
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

        # Grup başarıyla bittikten sonra işaretlenir (savepoint geri alınan grup işaretlenmez).
        # Yeni ürünün nebim_last_sync'i create ile yazıldı; yalnız mevcutlar toplu güncellenir.
        if result == 'updated':
            _CACHE['sync_ids'].add(template.id)
            if not defer_last_sync:
                self._flush_last_sync()

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

            # Yalnız değişenler yazılır (default_code değişimi template'e compute/inverse
            # tetiklediği için değişmeyende write hiç yapılmaz).
            update_vals = self._changed_vals(variant, update_vals)

            # Maliyet (Price2, KDV dahil): 0/boş gelirse mevcut maliyet ezilmez
            if _CACHE.get('update_cost'):
                cost = self._nebim_cost(var)
                if cost and round(variant.standard_price, 2) != cost:
                    update_vals['standard_price'] = cost

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

    @api.model
    def _nebim_cost(self, row):
        """Nebim satırındaki Price2 (KDV dahil maliyet); geçersiz / 0 ise None."""
        try:
            cost = round(float(row.get('Price2') or 0), 2)
        except (TypeError, ValueError):
            return None
        return cost if cost > 0 else None

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
