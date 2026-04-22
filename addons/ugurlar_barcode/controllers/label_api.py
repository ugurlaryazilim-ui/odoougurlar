"""Etiket API — label_data, template CRUD."""
import json
import logging

from odoo import http
from odoo.http import request

from .base_api import BarcodeApiBase

_logger = logging.getLogger(__name__)


class LabelApiController(BarcodeApiBase):
    """Etiket yazdırma ve şablon yönetim API'leri."""

    # ─── ETİKET VERİSİ (ürün bilgileri) ───────────────
    @http.route('/ugurlar_barcode/api/label_data', type='jsonrpc', auth='user')
    def label_data(self, barcodes=None, **kw):
        """Barkodlardan ürün bilgilerini çek (tüm alanlar)."""
        if not barcodes:
            return {'error': 'Barkod listesi gerekli'}

        results = []
        for bc in barcodes:
            bc = bc.strip()
            product = self._find_product(bc)
            if product:
                tmpl = product.product_tmpl_id

                # TÜM nitelikleri topla (template + varyant seviyesi)
                attrs = {}

                # 1. Template seviyesindeki tüm attribute line'lardan değerleri al
                for line in tmpl.attribute_line_ids:
                    attr_name = line.attribute_id.name
                    # Bu varyantın spesifik değerini bul
                    variant_vals = product.product_template_variant_value_ids.filtered(
                        lambda v: v.attribute_id.id == line.attribute_id.id
                    )
                    if variant_vals:
                        # Varyant-spesifik değer (Renk, Beden gibi)
                        attrs[attr_name] = ', '.join(variant_vals.mapped('name'))
                    elif len(line.value_ids) == 1:
                        # Tek değerli attribute (Reyon, Cinsiyet, Menşei gibi)
                        attrs[attr_name] = line.value_ids[0].name
                    elif line.value_ids:
                        # Birden fazla değer varsa hepsini göster
                        attrs[attr_name] = ', '.join(line.value_ids.mapped('name'))

                results.append({
                    'id': product.id,
                    'name': product.name,
                    'barcode': product.barcode or bc,
                    'default_code': product.default_code or '',
                    'nebim_code': tmpl.nebim_code or '',
                    'nebim_variant_code': product.nebim_variant_code or '',
                    'nebim_color_code': tmpl.nebim_color_code or '',
                    'list_price': product.list_price,
                    'standard_price': product.standard_price,
                    'category': product.categ_id.name if product.categ_id else '',
                    'marka': self._get_marka(tmpl),
                    'weight': product.weight or 0,
                    'volume': product.volume or 0,
                    'uom': product.uom_id.name if product.uom_id else 'Adet',
                    'attributes': attrs,
                    'description': (product.description_sale or '')[:200],
                })

                request.env['ugurlar.barcode.operation'].sudo().create({
                    'operation_type': 'label',
                    'barcode': bc,
                    'product_id': product.id,
                    'state': 'done',
                })
            else:
                results.append({
                    'barcode': bc,
                    'error': 'Ürün bulunamadı',
                })

        return {
            'labels': results,
            'total': len(results),
            'found': len([r for r in results if 'id' in r]),
        }

    # ─── ŞABLON LİSTELE ──────────────────────────────
    @http.route('/ugurlar_barcode/api/label_template_list', type='jsonrpc', auth='user')
    def label_template_list(self, **kw):
        """Kayıtlı etiket şablonlarını listele."""
        templates = request.env['ugurlar.label.template'].sudo().search([])
        result = []
        for t in templates:
            result.append({
                'id': t.id,
                'name': t.name,
                'width_mm': t.width_mm,
                'height_mm': t.height_mm,
                'is_default': t.is_default,
                'elements': json.loads(t.elements_json or '[]'),
                'user_name': t.user_id.name or '',
            })
        return {'templates': result, 'total': len(result)}

    # ─── ŞABLON KAYDET ────────────────────────────────
    @http.route('/ugurlar_barcode/api/label_template_save', type='jsonrpc', auth='user')
    def label_template_save(self, template_id=0, name='', width_mm=60, height_mm=40,
                            elements=None, is_default=False, **kw):
        """Şablon kaydet veya güncelle."""
        if not name:
            return {'error': 'Şablon adı gerekli'}

        Template = request.env['ugurlar.label.template'].sudo()
        elements_json = json.dumps(elements or [], ensure_ascii=False)

        if is_default:
            Template.search([('is_default', '=', True)]).write({'is_default': False})

        if template_id:
            tmpl = Template.browse(int(template_id))
            if tmpl.exists():
                tmpl.write({
                    'name': name,
                    'width_mm': float(width_mm),
                    'height_mm': float(height_mm),
                    'elements_json': elements_json,
                    'is_default': is_default,
                })
                return {'success': True, 'id': tmpl.id, 'message': 'Şablon güncellendi'}

        tmpl = Template.create({
            'name': name,
            'width_mm': float(width_mm),
            'height_mm': float(height_mm),
            'elements_json': elements_json,
            'is_default': is_default,
        })
        return {'success': True, 'id': tmpl.id, 'message': 'Şablon oluşturuldu'}

    # ─── ŞABLON SİL ──────────────────────────────────
    @http.route('/ugurlar_barcode/api/label_template_delete', type='jsonrpc', auth='user')
    def label_template_delete(self, template_id=0, **kw):
        """Şablon sil."""
        if not template_id:
            return {'error': 'Şablon ID gerekli'}
        Template = request.env['ugurlar.label.template'].sudo()
        tmpl = Template.browse(int(template_id))
        if tmpl.exists():
            tmpl.unlink()
            return {'success': True}
        return {'error': 'Şablon bulunamadı'}
