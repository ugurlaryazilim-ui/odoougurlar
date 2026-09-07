import hashlib
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

    İki endpoint sunar:
    1. /api/powerbi/products  → Tüm varyantların JSON listesi (barkod + görsel URL)
    2. /api/powerbi/image/<barcode> → Tek bir varyantın görselini binary olarak döndürür

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
            _logger.warning("Power BI API anahtarı tanımlanmamış. Ayarlar → Resimler → Power BI bölümünden oluşturun.")
            return False
        # Sabit zamanlı karşılaştırma (timing attack koruması)
        return hmac_compare(token, stored_token)

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
        return request.env['ir.config_parameter'].sudo().get_param('web.base.url', '')

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

        Parametreler:
            token (str): API anahtarı (zorunlu)
            size  (str): Görsel boyutu — 128, 256, 512, 1024, 1920 (varsayılan: 512)

        Döndürür:
            JSON array:
            [
                {
                    "product_id": 12345,
                    "barcode": "8691234560001",
                    "default_code": "ABC-001",
                    "product_name": "Ürün Adı",
                    "template_name": "Şablon Adı",
                    "variant_attributes": "Kırmızı / M",
                    "has_image": true,
                    "image_url": "https://odoo.sirket.com/api/powerbi/image/8691234560001?token=XXX&size=512"
                },
                ...
            ]
        """
        # Token doğrulama
        if not self._validate_token(token):
            return self._json_error('Geçersiz veya eksik API anahtarı.', 403)

        size = size or DEFAULT_SIZE
        if size not in VALID_SIZES:
            return self._json_error(
                f"Geçersiz boyut: {size}. Geçerli değerler: {', '.join(sorted(VALID_SIZES.keys()))}",
                400,
            )

        base_url = self._get_base_url()
        image_field = VALID_SIZES[size]

        # Tüm aktif ürün varyantlarını çek
        products = request.env['product.product'].sudo().search([
            ('active', '=', True),
        ])

        data = []
        for product in products:
            barcode = product.barcode or ''
            default_code = product.default_code or ''

            # Görsel var mı kontrolü
            has_image = bool(product[image_field])

            # Barkod veya ID bazlı görsel URL
            if barcode:
                image_url = f"{base_url}/api/powerbi/image/{barcode}?token={token}&size={size}"
            else:
                # Barkodu olmayan ürünler için ID bazlı URL
                image_url = f"{base_url}/api/powerbi/image-by-id/{product.id}?token={token}&size={size}"

            # Varyant özellik metni (ör: "Kırmızı / M")
            variant_attrs = ', '.join(
                product.product_template_attribute_value_ids.mapped(
                    lambda v: f"{v.attribute_id.name}: {v.name}"
                )
            ) if product.product_template_attribute_value_ids else ''

            data.append({
                'product_id': product.id,
                'template_id': product.product_tmpl_id.id,
                'barcode': barcode,
                'default_code': default_code,
                'product_name': product.display_name or '',
                'template_name': product.product_tmpl_id.name or '',
                'variant_attributes': variant_attrs,
                'has_image': has_image,
                'image_url': image_url if has_image else '',
            })

        response_body = json.dumps(data, ensure_ascii=False, indent=2)
        return Response(
            response_body,
            status=200,
            content_type='application/json; charset=utf-8',
            headers={
                'Access-Control-Allow-Origin': '*',
            },
        )

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

        Parametreler:
            barcode (str): Ürün barkodu (URL path)
            token   (str): API anahtarı (zorunlu)
            size    (str): Görsel boyutu — 128, 256, 512, 1024, 1920 (varsayılan: 512)

        Döndürür:
            image/png veya image/jpeg binary yanıt
        """
        if not self._validate_token(token):
            return self._json_error('Geçersiz veya eksik API anahtarı.', 403)

        size = size or DEFAULT_SIZE
        if size not in VALID_SIZES:
            return self._json_error(
                f"Geçersiz boyut: {size}. Geçerli değerler: {', '.join(sorted(VALID_SIZES.keys()))}",
                400,
            )

        image_field = VALID_SIZES[size]

        # Ürünü barkod ile bul
        product = request.env['product.product'].sudo().search([
            ('barcode', '=', barcode),
            ('active', '=', True),
        ], limit=1)

        if not product:
            return self._json_error(f"Ürün bulunamadı: {barcode}", 404)

        image_data = product[image_field]
        if not image_data:
            return self._json_error(f"Bu ürünün görseli yok: {barcode}", 404)

        return self._serve_image(image_data, barcode)

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

        Parametreler:
            product_id (int): product.product ID (URL path)
            token      (str): API anahtarı (zorunlu)
            size       (str): Görsel boyutu (varsayılan: 512)
        """
        if not self._validate_token(token):
            return self._json_error('Geçersiz veya eksik API anahtarı.', 403)

        size = size or DEFAULT_SIZE
        if size not in VALID_SIZES:
            return self._json_error(
                f"Geçersiz boyut: {size}. Geçerli değerler: {', '.join(sorted(VALID_SIZES.keys()))}",
                400,
            )

        image_field = VALID_SIZES[size]

        product = request.env['product.product'].sudo().browse(product_id)
        if not product.exists() or not product.active:
            return self._json_error(f"Ürün bulunamadı: ID {product_id}", 404)

        image_data = product[image_field]
        if not image_data:
            return self._json_error(f"Bu ürünün görseli yok: ID {product_id}", 404)

        return self._serve_image(image_data, str(product_id))

    # =================================================================
    #  Yardımcı: Görseli HTTP Response olarak döndür
    # =================================================================

    def _serve_image(self, image_base64, identifier):
        """
        Base64 encoded görsel verisini binary HTTP yanıtı olarak döndürür.
        ETag ve Cache-Control header'ları ekler.
        """
        import base64

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


def hmac_compare(a, b):
    """
    Sabit zamanlı string karşılaştırma.
    Timing attack'lere karşı koruma sağlar.
    """
    import hmac
    return hmac.compare_digest(str(a), str(b))
