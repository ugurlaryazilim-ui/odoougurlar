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

    Güvenlik: API token ile korunur (Ayarlar → Resimler → Power BI API Anahtarı)
    """

    def _validate_token(self, token):
        """API token doğrulaması yapar."""
        if not token:
            return False
        stored_token = request.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_images.powerbi_api_key', ''
        )
        if not stored_token:
            return False
        return hmac.compare_digest(str(token), str(stored_token))

    def _json_error(self, message, status=403):
        """Standart JSON hata yanıtı."""
        return Response(
            json.dumps({'status': 'error', 'message': message}),
            status=status,
            content_type='application/json',
        )

    # =================================================================
    #  Endpoint 1: Ürün Listesi (JSON) — Hafif, sadece SQL
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
        Performans için doğrudan SQL kullanır — görsel binary yüklemez.
        """
        if not self._validate_token(token):
            return self._json_error('Geçersiz veya eksik API anahtarı.', 403)

        size = size or DEFAULT_SIZE
        if size not in VALID_SIZES:
            return self._json_error(
                'Geçersiz boyut. Gecerli: 128, 256, 512, 1024, 1920', 400
            )

        base_url = request.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', ''
        )

        try:
            # Doğrudan SQL — sadece görseli olan ürünleri getir
            # ir_attachment tablosundan varyant veya şablon görseli kontrolü
            request.env.cr.execute("""
                SELECT
                    pp.id AS product_id,
                    pp.product_tmpl_id AS template_id,
                    pp.barcode,
                    pp.default_code,
                    pt.name->>'en_US' AS template_name
                FROM product_product pp
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE pp.active = true
                  AND (
                    -- Varyantın kendi görseli var mı?
                    EXISTS (
                        SELECT 1 FROM ir_attachment ia
                        WHERE ia.res_model = 'product.product'
                          AND ia.res_field = 'image_variant_1920'
                          AND ia.res_id = pp.id
                    )
                    OR
                    -- Şablonun görseli var mı?
                    EXISTS (
                        SELECT 1 FROM ir_attachment ia
                        WHERE ia.res_model = 'product.template'
                          AND ia.res_field = 'image_1920'
                          AND ia.res_id = pt.id
                    )
                  )
                ORDER BY pp.id
            """)
            rows = request.env.cr.dictfetchall()

            data = []
            for row in rows:
                barcode = row.get('barcode') or ''
                product_id = row['product_id']

                # Görsel URL oluştur
                if barcode:
                    image_url = (
                        '%s/api/powerbi/image/%s?token=%s&size=%s'
                        % (base_url, barcode, token, size)
                    )
                else:
                    image_url = (
                        '%s/api/powerbi/image-by-id/%s?token=%s&size=%s'
                        % (base_url, product_id, token, size)
                    )

                data.append({
                    'product_id': product_id,
                    'template_id': row.get('template_id') or 0,
                    'barcode': barcode,
                    'default_code': row.get('default_code') or '',
                    'template_name': row.get('template_name') or '',
                    'image_url': image_url,
                })

            return Response(
                json.dumps(data, ensure_ascii=False),
                status=200,
                content_type='application/json; charset=utf-8',
                headers={'Access-Control-Allow-Origin': '*'},
            )

        except Exception as e:
            _logger.exception("Power BI urun listesi hatasi")
            return self._json_error('Sunucu hatasi: %s' % str(e), 500)

    # =================================================================
    #  Endpoint 2: Tek Görsel (Barkod ile)
    # =================================================================

    @http.route(
        '/api/powerbi/image/<string:barcode>',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def powerbi_image_by_barcode(self, barcode, token=None, size=None, **kwargs):
        """Barkod ile ürün görselini binary olarak döndürür."""
        if not self._validate_token(token):
            return self._json_error('Gecersiz API anahtari.', 403)

        size = size or DEFAULT_SIZE
        if size not in VALID_SIZES:
            return self._json_error('Gecersiz boyut.', 400)

        image_field = VALID_SIZES[size]

        try:
            product = request.env['product.product'].sudo().search([
                ('barcode', '=', barcode),
                ('active', '=', True),
            ], limit=1)

            if not product:
                return self._json_error('Urun bulunamadi: %s' % barcode, 404)

            image_data = product[image_field]
            if not image_data:
                return self._json_error('Gorsel yok: %s' % barcode, 404)

            return self._serve_image(image_data, barcode)

        except Exception as e:
            _logger.exception("Power BI gorsel hatasi (barkod: %s)", barcode)
            return self._json_error('Hata: %s' % str(e), 500)

    # =================================================================
    #  Endpoint 3: Tek Görsel (ID ile)
    # =================================================================

    @http.route(
        '/api/powerbi/image-by-id/<int:product_id>',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def powerbi_image_by_id(self, product_id, token=None, size=None, **kwargs):
        """Ürün ID ile görselini binary olarak döndürür."""
        if not self._validate_token(token):
            return self._json_error('Gecersiz API anahtari.', 403)

        size = size or DEFAULT_SIZE
        if size not in VALID_SIZES:
            return self._json_error('Gecersiz boyut.', 400)

        image_field = VALID_SIZES[size]

        try:
            product = request.env['product.product'].sudo().browse(product_id)
            if not product.exists() or not product.active:
                return self._json_error('Urun bulunamadi: %s' % product_id, 404)

            image_data = product[image_field]
            if not image_data:
                return self._json_error('Gorsel yok: %s' % product_id, 404)

            return self._serve_image(image_data, str(product_id))

        except Exception as e:
            _logger.exception("Power BI gorsel hatasi (ID: %s)", product_id)
            return self._json_error('Hata: %s' % str(e), 500)

    # =================================================================
    #  Yardımcı: Görseli HTTP Response olarak döndür
    # =================================================================

    def _serve_image(self, image_base64, identifier):
        """Base64 görsel verisini binary HTTP yanıtı olarak döndürür."""
        try:
            image_bytes = base64.b64decode(image_base64)
        except Exception:
            return self._json_error('Gorsel cozumlenemedi.', 500)

        # Content-Type tespiti
        content_type = 'image/png'
        if image_bytes[:2] == b'\xff\xd8':
            content_type = 'image/jpeg'
        elif image_bytes[:4] == b'RIFF':
            content_type = 'image/webp'

        # ETag — cache doğrulama
        etag = hashlib.md5(image_bytes).hexdigest()

        if_none_match = request.httprequest.headers.get('If-None-Match', '')
        if if_none_match == etag:
            return Response(status=304)

        return Response(
            image_bytes,
            status=200,
            headers={
                'Content-Type': content_type,
                'Cache-Control': 'public, max-age=%d' % CACHE_MAX_AGE,
                'ETag': etag,
                'Access-Control-Allow-Origin': '*',
            },
        )
