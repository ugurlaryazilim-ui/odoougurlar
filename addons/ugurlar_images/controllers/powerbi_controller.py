import base64
import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# Desteklenen görsel boyutları — Odoo'nun standart image field'ları
VALID_SIZES = {
    '128': 'image_128',
    '256': 'image_256',
    '512': 'image_512',
    '1024': 'image_1024',
    '1920': 'image_1920',
}

# Varsayılan boyut
DEFAULT_SIZE = '512'

# Cache süresi (saniye) — 1 saat
CACHE_MAX_AGE = 3600


class PowerBIController(http.Controller):
    """
    Power BI entegrasyonu için public controller.

    Üç endpoint sunar:
    1. /api/powerbi/products  → Tüm varyantların JSON listesi (barkod + görsel URL)
    2. /api/powerbi/image/<barcode> → Tek bir varyantın görselini binary olarak döndürür
    3. /api/powerbi/image-by-id/<id> → ID ile görsel

    Güvenlik: API token ile korunur (Ayarlar → Resimler → Power BI API Anahtarı)
    """

    # =================================================================
    #  Yardımcı Metodlar
    # =================================================================

    def _validate_token(self, token):
        """API token doğrulaması yapar."""
        if not token:
            return False
        stored_token = request.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_images.powerbi_api_key', ''
        )
        if not stored_token:
            _logger.warning(
                "Power BI API anahtarı tanımlanmamış. "
                "Ayarlar → Resimler → Power BI bölümünden oluşturun."
            )
            return False
        # Sabit zamanlı karşılaştırma (timing attack koruması)
        return hmac.compare_digest(str(token), str(stored_token))

    def _json_error(self, message, status=403):
        """Standart JSON hata yanıtı."""
        body = json.dumps({
            'status': 'error',
            'message': message,
        })
        return Response(
            body,
            status=status,
            content_type='application/json',
        )

    def _get_base_url(self):
        """Odoo base URL'ini döndürür."""
        return request.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', ''
        )

    # =================================================================
    #  Endpoint 1: Ürün Listesi (JSON)
    # =================================================================

    @http.route(
        '/api/powerbi/products',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def powerbi_product_list(self, token=None, size=None, **kwargs):
        """
        Power BI için tüm varyantların listesini JSON olarak döndürür.

        Görsellerin binary verisini YÜKLEMEZ — sadece URL döndürür.
        Böylece binlerce ürün olsa bile hızlı çalışır.
        """
        # Token doğrulama
        if not self._validate_token(token):
            return self._json_error('Geçersiz veya eksik API anahtarı.', 403)

        size = size or DEFAULT_SIZE
        if size not in VALID_SIZES:
            return self._json_error(
                f"Geçersiz boyut: {size}. "
                f"Geçerli değerler: {', '.join(sorted(VALID_SIZES.keys()))}",
                400,
            )

        base_url = self._get_base_url()

        try:
            # SQL ile hızlı sorgu — image binary yüklemeden sadece meta veri çek
            # image_variant_1920 alanının boş olup olmadığını kontrol etmek için
            # ir_attachment tablosunu kontrol ediyoruz ama daha basit yol:
            # product.product tablosundan sadece gerekli alanları read() ile çek
            products = request.env['product.product'].sudo().search_read(
                domain=[('active', '=', True)],
                fields=[
                    'id',
                    'barcode',
                    'default_code',
                    'display_name',
                    'product_tmpl_id',
                ],
                order='id asc',
            )

            # Template isimlerini toplu çek (N+1 önleme)
            tmpl_ids = list(set(
                p['product_tmpl_id'][0]
                for p in products
                if p.get('product_tmpl_id')
            ))
            tmpl_names = {}
            if tmpl_ids:
                templates = request.env['product.template'].sudo().search_read(
                    domain=[('id', 'in', tmpl_ids)],
                    fields=['id', 'name'],
                )
                tmpl_names = {t['id']: t['name'] for t in templates}

            # Varyant özelliklerini toplu çek
            product_ids = [p['id'] for p in products]
            variant_attrs_map = {}
            if product_ids:
                pp_records = request.env['product.product'].sudo().browse(product_ids)
                # Batch prefetch ile performans
                for pp in pp_records:
                    try:
                        attrs = []
                        for ptav in pp.product_template_attribute_value_ids:
                            attrs.append(
                                f"{ptav.attribute_id.name}: {ptav.name}"
                            )
                        variant_attrs_map[pp.id] = ', '.join(attrs)
                    except Exception:
                        variant_attrs_map[pp.id] = ''

            data = []
            for product in products:
                barcode = product.get('barcode') or ''
                default_code = product.get('default_code') or ''
                product_id = product['id']

                tmpl_id = (
                    product['product_tmpl_id'][0]
                    if product.get('product_tmpl_id')
                    else False
                )
                tmpl_name = tmpl_names.get(tmpl_id, '') if tmpl_id else ''

                # Görsel URL — barkod varsa barkod ile, yoksa ID ile
                if barcode:
                    image_url = (
                        f"{base_url}/api/powerbi/image/{barcode}"
                        f"?token={token}&size={size}"
                    )
                else:
                    image_url = (
                        f"{base_url}/api/powerbi/image-by-id/{product_id}"
                        f"?token={token}&size={size}"
                    )

                data.append({
                    'product_id': product_id,
                    'template_id': tmpl_id or 0,
                    'barcode': barcode,
                    'default_code': default_code,
                    'product_name': product.get('display_name') or '',
                    'template_name': tmpl_name,
                    'variant_attributes': variant_attrs_map.get(product_id, ''),
                    'image_url': image_url,
                })

            response_body = json.dumps(data, ensure_ascii=False)
            return Response(
                response_body,
                status=200,
                content_type='application/json; charset=utf-8',
                headers={
                    'Access-Control-Allow-Origin': '*',
                },
            )
        except Exception as e:
            _logger.exception("Power BI ürün listesi hatası")
            return self._json_error(f"Sunucu hatası: {str(e)}", 500)

    # =================================================================
    #  Endpoint 2: Tek Görsel (Binary — Barkod ile)
    # =================================================================

    @http.route(
        '/api/powerbi/image/<string:barcode>',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def powerbi_image_by_barcode(self, barcode, token=None, size=None, **kwargs):
        """
        Barkod ile ürün görselini binary olarak döndürür.
        """
        if not self._validate_token(token):
            return self._json_error('Geçersiz veya eksik API anahtarı.', 403)

        size = size or DEFAULT_SIZE
        if size not in VALID_SIZES:
            return self._json_error(
                f"Geçersiz boyut: {size}. "
                f"Geçerli değerler: {', '.join(sorted(VALID_SIZES.keys()))}",
                400,
            )

        image_field = VALID_SIZES[size]

        try:
            # Ürünü barkod ile bul
            product = request.env['product.product'].sudo().search([
                ('barcode', '=', barcode),
                ('active', '=', True),
            ], limit=1)

            if not product:
                return self._json_error(f"Ürün bulunamadı: {barcode}", 404)

            image_data = product[image_field]
            if not image_data:
                return self._json_error(
                    f"Bu ürünün görseli yok: {barcode}", 404
                )

            return self._serve_image(image_data, barcode)
        except Exception as e:
            _logger.exception("Power BI görsel hatası (barkod: %s)", barcode)
            return self._json_error(f"Sunucu hatası: {str(e)}", 500)

    # =================================================================
    #  Endpoint 3: Tek Görsel (Binary — ID ile)
    # =================================================================

    @http.route(
        '/api/powerbi/image-by-id/<int:product_id>',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def powerbi_image_by_id(self, product_id, token=None, size=None, **kwargs):
        """
        Ürün ID ile görselini binary olarak döndürür.
        Barkodu olmayan ürünler için kullanılır.
        """
        if not self._validate_token(token):
            return self._json_error('Geçersiz veya eksik API anahtarı.', 403)

        size = size or DEFAULT_SIZE
        if size not in VALID_SIZES:
            return self._json_error(
                f"Geçersiz boyut: {size}. "
                f"Geçerli değerler: {', '.join(sorted(VALID_SIZES.keys()))}",
                400,
            )

        image_field = VALID_SIZES[size]

        try:
            product = request.env['product.product'].sudo().browse(product_id)
            if not product.exists() or not product.active:
                return self._json_error(
                    f"Ürün bulunamadı: ID {product_id}", 404
                )

            image_data = product[image_field]
            if not image_data:
                return self._json_error(
                    f"Bu ürünün görseli yok: ID {product_id}", 404
                )

            return self._serve_image(image_data, str(product_id))
        except Exception as e:
            _logger.exception(
                "Power BI görsel hatası (ID: %s)", product_id
            )
            return self._json_error(f"Sunucu hatası: {str(e)}", 500)

    # =================================================================
    #  Yardımcı: Görseli HTTP Response olarak döndür
    # =================================================================

    def _serve_image(self, image_base64, identifier):
        """
        Base64 encoded görsel verisini binary HTTP yanıtı olarak döndürür.
        ETag ve Cache-Control header'ları ekler.
        """
        try:
            image_bytes = base64.b64decode(image_base64)
        except Exception:
            return self._json_error("Görsel verisi çözümlenemedi.", 500)

        # Content-Type tespiti (ilk byte'lardan)
        content_type = 'image/png'
        if image_bytes[:2] == b'\xff\xd8':
            content_type = 'image/jpeg'
        elif image_bytes[:4] == b'\x89PNG':
            content_type = 'image/png'
        elif image_bytes[:4] == b'RIFF':
            content_type = 'image/webp'

        # ETag — görselin hash'i (cache doğrulama için)
        etag = hashlib.md5(image_bytes).hexdigest()

        # Client tarafı cache kontrolü
        if_none_match = request.httprequest.headers.get('If-None-Match', '')
        if if_none_match == etag:
            return Response(status=304)

        headers = {
            'Content-Type': content_type,
            'Cache-Control': f'public, max-age={CACHE_MAX_AGE}',
            'ETag': etag,
            'Access-Control-Allow-Origin': '*',
            'Content-Disposition': f'inline; filename="{identifier}.jpg"',
        }

        return Response(image_bytes, status=200, headers=headers)
