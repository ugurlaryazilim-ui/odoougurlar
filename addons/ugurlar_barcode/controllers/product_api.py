"""Ürün Stok Arama API — product_search endpoint."""
import logging

from odoo import http
from odoo.http import request

from .base_api import BarcodeApiBase

_logger = logging.getLogger(__name__)


class ProductApiController(BarcodeApiBase):
    """Ürün stok arama API'si."""

    @http.route('/ugurlar_barcode/api/product_search', type='jsonrpc', auth='user')
    def product_search(self, barcode='', search_type='barcode', **kw):
        """Ürün ara → stok + raf + varyant bilgisi döndür.
        search_type: 'barcode' → sadece o varyant
                     'code'    → ana ürün kodu ile TÜM varyantlar
                     'name'    → isim eşleşen TÜM ürünlerin varyantları
        """
        if not barcode:
            return {'error': 'Arama terimi giriniz'}

        query = barcode.strip()
        Product = request.env['product.product'].sudo()
        Template = request.env['product.template'].sudo()
        product = None
        templates = Template
        show_variants = False

        # ─── BARKOD ARAMASI ────────────────────────
        if search_type == 'barcode':
            product = Product.search([('barcode', '=', query)], limit=1)
            if not product:
                product = Product.search([('nebim_barcode', 'like', query)], limit=1)
                if product and query not in (product.nebim_barcode or '').split(','):
                    product = Product.browse()
            if not product:
                product = Product.search([('default_code', '=', query)], limit=1)
            if product:
                templates = product.product_tmpl_id
                show_variants = False

        # ─── ÜRÜN KODU ARAMASI ─────────────────────
        elif search_type == 'code':
            tmpl = Template.search([('nebim_code', '=', query)], limit=1)
            if not tmpl:
                tmpl = Template.search([('default_code', '=', query)], limit=1)
            if not tmpl:
                var = Product.search([('nebim_variant_code', '=', query)], limit=1)
                if var:
                    tmpl = var.product_tmpl_id
            if not tmpl:
                tmpl = Template.search([
                    '|', ('nebim_code', 'ilike', query),
                    ('default_code', 'ilike', query),
                ], limit=1)
            if tmpl:
                templates = tmpl
                product = tmpl.product_variant_ids[:1]
                show_variants = True

        # ─── ÜRÜN ADI ARAMASI ──────────────────────
        elif search_type == 'name':
            tmpls = Template.search([('name', 'ilike', query)], limit=10)
            if tmpls:
                templates = tmpls
                product = tmpls[0].product_variant_ids[:1]
                show_variants = True

        # Fallback
        if not product:
            product = Product.search([
                '|', '|',
                ('default_code', '=', query),
                ('barcode', '=', query),
                ('name', 'ilike', query),
            ], limit=1)
            if product:
                templates = product.product_tmpl_id
                show_variants = (search_type != 'barcode')

        if not product:
            return {'error': f'Ürün bulunamadı: {query}'}

        # ─── VARYANT TABLOSU ──────────────────────
        variants_data = []
        if show_variants:
            all_variants = Product.browse()
            for tmpl in templates:
                all_variants |= tmpl.product_variant_ids
        else:
            all_variants = product

        _marka_cache = {}

        # Batch stok sorgusu (hem varyant toplamları hem lokasyon detayları)
        variant_ids = all_variants.ids
        stock_map = {}
        Quant = request.env['stock.quant'].sudo()

        if variant_ids:
            quant_data = Quant.read_group(
                domain=[
                    ('product_id', 'in', variant_ids),
                    ('location_id.usage', '=', 'internal'),
                    ('quantity', '>', 0),
                ],
                fields=['product_id', 'quantity:sum'],
                groupby=['product_id'],
            )
            for qd in quant_data:
                pid = qd['product_id'][0]
                stock_map[pid] = qd['quantity']

        # Batch prefetch: tüm varyantların attribute value'larını önceden yükle
        all_variants.mapped('product_template_attribute_value_ids.attribute_id')

        for var in all_variants:
            color = ''
            size = ''
            for ptav in var.product_template_attribute_value_ids:
                attr_name = ptav.attribute_id.name
                if attr_name == 'Renk':
                    color = ptav.name
                elif attr_name == 'Beden':
                    size = ptav.name

            variants_data.append({
                'id': var.id,
                'code': var.product_tmpl_id.nebim_code or var.default_code or '',
                'barcode': var.barcode or '',
                'color': color,
                'size': size,
                'stock': stock_map.get(var.id, 0),
                'price': var.list_price,
                'marka': self._get_marka(var.product_tmpl_id, _marka_cache),
            })

        # Beden sıralama
        def sort_key(v):
            try:
                return (v['code'], v['color'], int(v['size']))
            except (ValueError, TypeError):
                return (v['code'], v['color'], v['size'])
        variants_data.sort(key=sort_key)

        # ─── STOK BİLGİLERİ (seçili varyant için lokasyon detayları) ──
        # read_group'tan toplam stok zaten stock_map'te var, sadece lokasyon detayı lazım
        quants = Quant.search([
            ('product_id', '=', product.id),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ])

        stock_locations = []
        total_stock = stock_map.get(product.id, 0)
        for q in quants:
            stock_locations.append({
                'location': q.location_id.complete_name,
                'location_barcode': q.location_id.barcode or '',
                'quantity': q.quantity,
            })

        # ─── ÜRÜN NİTELİKLERİ ─────────────────────
        main_template = templates[0] if templates else product.product_tmpl_id
        hamur_order = [
            'Tedarikçi', 'Reyon', 'Cinsiyet', 'Ürün Grubu',
            'Sezon/Yıl', 'Marka', 'Menşei', 'Yaka', 'Materyal',
            'Kalıp', 'Desen', 'Boy', 'Kol Bilgisi', 'Paça Boyu',
            'Bel Bilgisi', 'Kumaş Türü', 'Yaş Grubu',
        ]
        attr_data = {}
        for line in main_template.attribute_line_ids:
            attr_name = line.attribute_id.name
            if line.attribute_id.create_variant == 'no_variant':
                values = ', '.join(line.value_ids.mapped('name'))
                if values:
                    attr_data[attr_name] = values

        product_attrs = {}
        for key in hamur_order:
            if key in attr_data:
                product_attrs[key] = attr_data[key]
        for key, val in attr_data.items():
            if key not in product_attrs:
                product_attrs[key] = val

        total_all_variants_stock = sum(v['stock'] for v in variants_data) if variants_data else total_stock

        # LOG
        request.env['ugurlar.barcode.operation'].sudo().create({
            'operation_type': 'search',
            'barcode': query,
            'product_id': product.id,
            'state': 'done',
        })

        return {
            'product': {
                'id': product.id,
                'name': main_template.name,
                'barcode': product.barcode or '',
                'default_code': main_template.default_code or '',
                'nebim_code': main_template.nebim_code or '',
                'list_price': product.list_price,
                'image_url': f'/web/image/product.product/{product.id}/image_128',
                'category': main_template.categ_id.name if main_template.categ_id else '',
            },
            'total_stock': total_stock,
            'total_all_variants_stock': total_all_variants_stock,
            'locations': stock_locations,
            'variants': variants_data,
            'attributes': product_attrs,
            'variant_count': len(variants_data),
            'show_variants': show_variants,
            'search_type': search_type,
        }
