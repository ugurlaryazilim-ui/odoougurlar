import base64
import gzip
import hashlib
import hmac
import json
import logging
import re

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# Power BI URL'lerindeki ?token= değeri her istekte werkzeug erişim log'una yazılıyordu.
# URL ve anahtar değişmesin diye (Power BI raporları bunlara bağlı) yalnız log satırı maskelenir.
_TOKEN_RE = re.compile(r'([?&]token=)[^&\s"]+')


class _MaskTokenFilter(logging.Filter):
    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:
            return True
        if 'token=' in message:
            record.msg = _TOKEN_RE.sub(r'\1***', message)
            record.args = ()
        return True


_werkzeug_logger = logging.getLogger('werkzeug')
if not any(type(f).__name__ == '_MaskTokenFilter' for f in _werkzeug_logger.filters):
    _werkzeug_logger.addFilter(_MaskTokenFilter())

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

# Liste ucu sayfalama: `limit` verilmezse (eski Power BI raporları) tüm liste döner.
# NEDEN: varsayılanı kısıtlamak mevcut raporları sessizce eksik veriyle bırakır (KK-5 geri uyum).
# Rapor sorguları limit/offset'e geçirildikten sonra ayar ile varsayılan sayfa boyutu açılabilir.
LIMIT_PARAM = 'ugurlar_images.powerbi_default_limit'
MAX_LIMIT = 10000

# Aynı süzgeç liste sorgusunda ve ETag/toplam sorgusunda kullanılır (sapmasın diye tek yerde).
# NEDEN: yalnız görseli olan (varyant ya da şablon) aktif ürünler listelenir.
_LIST_FROM_WHERE = """
    FROM product_product pp
    JOIN product_template pt ON pt.id = pp.product_tmpl_id
    WHERE pp.active = true
      AND (
        EXISTS (
            SELECT 1 FROM ir_attachment ia
            WHERE ia.res_model = 'product.product'
              AND ia.res_field = 'image_variant_1920'
              AND ia.res_id = pp.id
        )
        OR EXISTS (
            SELECT 1 FROM ir_attachment ia
            WHERE ia.res_model = 'product.template'
              AND ia.res_field = 'image_1920'
              AND ia.res_id = pt.id
        )
      )
"""


def _etag_matches(etag):
    """If-None-Match başlığı etag ile eşleşiyor mu (tırnaklı, W/ ve eski tırnaksız biçimleri kabul eder)."""
    header = request.httprequest.headers.get('If-None-Match', '')
    candidates = {
        part.strip().removeprefix('W/').strip('"') for part in header.split(',')
    }
    return etag in candidates


class PowerBIController(http.Controller):
    """
    Power BI entegrasyonu için public controller.

    Güvenlik: API token ile korunur (Ayarlar → Resimler → Power BI API Anahtarı)
    """

    def _validate_token(self, token):
        """API token doğrulaması yapar. Power BI kapalıysa erişimi engeller."""
        if not token:
            return False
        # Power BI entegrasyonu aktif mi? (Varsayılan: aktif — sadece açıkça kapatılırsa engelle)
        enabled = request.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_images.powerbi_enabled', 'True'
        )
        if enabled in ('False', 'false', '0'):
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
    def powerbi_product_list(self, token=None, size=None, limit=None, offset=None, **kwargs):
        """
        Power BI için varyantların listesini JSON dizisi olarak döndürür.

        `limit`/`offset` verilirse sayfalı döner (X-Total-Count, X-Next-Offset başlıkları);
        verilmezse eski davranış: tüm liste. Doğrudan SQL kullanır — görsel binary yüklemez.
        """
        if not self._validate_token(token):
            return self._json_error('Geçersiz veya eksik API anahtarı.', 403)

        size = size or DEFAULT_SIZE
        if size not in VALID_SIZES:
            return self._json_error(
                'Geçersiz boyut. Gecerli: 128, 256, 512, 1024, 1920', 400
            )

        try:
            params = request.env['ir.config_parameter'].sudo()
            if limit is None:
                limit = params.get_param(LIMIT_PARAM, '0')
            limit = int(limit)
            offset = int(offset or 0)
            if limit < 0 or offset < 0:
                raise ValueError
        except (TypeError, ValueError):
            return self._json_error('Geçersiz limit/offset.', 400)
        limit = min(limit, MAX_LIMIT)
        base_url = params.get_param('web.base.url', '')

        try:
            cr = request.env.cr
            # NEDEN: ETag, JSON üretilmeden önce ucuz bir toplamla hesaplanır; değişmediyse 304
            # ağır sorgu + 18 MB serileştirme + gzip hiç yapılmaz.
            cr.execute(
                "SELECT COUNT(*), MAX(GREATEST(pp.write_date, pt.write_date))"
                + _LIST_FROM_WHERE
            )
            total, last_write = cr.fetchone()
            etag = hashlib.md5(
                ('%s|%s|%s|%s|%s|%s|%s' % (
                    total, last_write, size, limit, offset, base_url,
                    hashlib.sha256(str(token).encode()).hexdigest(),
                )).encode()
            ).hexdigest()
            headers = {
                'Content-Type': 'application/json; charset=utf-8',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'public, max-age=300',
                'ETag': '"%s"' % etag,
                'Vary': 'Accept-Encoding',
                'X-Total-Count': str(total),
            }
            if _etag_matches(etag):
                return Response(status=304, headers={
                    k: v for k, v in headers.items() if k != 'Content-Type'
                })

            sql = ("""
                SELECT
                    pp.id AS product_id,
                    pp.product_tmpl_id AS template_id,
                    pp.barcode,
                    pp.default_code,
                    COALESCE(pt.name->>'tr_TR', pt.name->>'en_US', pt.name->>'tr') AS template_name
                """ + _LIST_FROM_WHERE + " ORDER BY pp.id")
            sql_params = []
            if limit:
                sql += " LIMIT %s OFFSET %s"
                sql_params = [limit, offset]
                next_offset = offset + limit
                headers['X-Next-Offset'] = str(next_offset) if next_offset < total else ''
            elif offset:
                sql += " OFFSET %s"
                sql_params = [offset]
            cr.execute(sql, sql_params)
            rows = cr.dictfetchall()

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

            # Kompakt ayraç: aynı veri, daha az bayt (JSON ayrıştırıcıları için fark yok).
            json_bytes = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')

            # İstemci gzip destekliyorsa anında sıkıştır (18MB -> ~2MB)
            if 'gzip' in request.httprequest.headers.get('Accept-Encoding', ''):
                json_bytes = gzip.compress(json_bytes, compresslevel=5)
                headers['Content-Encoding'] = 'gzip'
            headers['Content-Length'] = str(len(json_bytes))
            return Response(json_bytes, status=200, headers=headers)

        except Exception:
            _logger.exception("Power BI urun listesi hatasi")
            return self._json_error('Sunucu hatasi.', 500)

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

        try:
            product = request.env['product.product'].sudo().search([
                ('barcode', '=', barcode),
                ('active', '=', True),
            ], limit=1)

            if not product:
                return self._json_error('Urun bulunamadi: %s' % barcode, 404)

            return self._image_response(product, size, barcode)

        except Exception:
            _logger.exception("Power BI gorsel hatasi (barkod: %s)", barcode)
            return self._json_error('Sunucu hatasi.', 500)

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

        try:
            product = request.env['product.product'].sudo().browse(product_id)
            if not product.exists() or not product.active:
                return self._json_error('Urun bulunamadi: %s' % product_id, 404)

            return self._image_response(product, size, str(product_id))

        except Exception:
            _logger.exception("Power BI gorsel hatasi (ID: %s)", product_id)
            return self._json_error('Sunucu hatasi.', 500)

    # =================================================================
    #  Yardımcılar: Görseli HTTP Response olarak döndür
    # =================================================================

    def _image_response(self, product, size, identifier):
        """Görseli önce depolanmış boyut ek dosyasından akıtır; yoksa eski base64 yoluna düşer."""
        attachment = self._find_image_attachment(product, size)
        if attachment:
            stream = attachment._to_http_stream()
            if stream.type in ('data', 'path') and stream.size:
                # NEDEN: ETag = ek dosya checksum'ı; Stream.get_response If-None-Match
                # eşleşirse gövdeyi okumadan 304 döner. Dosya diskten akıtılır, base64 yok.
                if not (stream.mimetype or '').startswith('image/'):
                    stream.mimetype = 'image/png'
                stream.max_age = CACHE_MAX_AGE
                response = stream.get_response()
                response.headers['Cache-Control'] = 'public, max-age=%d' % CACHE_MAX_AGE
                response.headers['Access-Control-Allow-Origin'] = '*'
                return response

        # Boyut ek dosyası yoksa (ör. eski kayıt) alan değerinden okunur — eski davranış.
        image_data = product[VALID_SIZES[size]]
        if not image_data:
            return self._json_error('Gorsel yok: %s' % identifier, 404)
        return self._serve_image(image_data, identifier)

    def _find_image_attachment(self, product, size):
        """Ürün için `size` boyutundaki depolanmış görselin ek dosyası.

        Odoo sırası: varyantın kendi görseli, yoksa şablonunki
        (image_<size> hesaplanan alanı ile aynı kural).
        """
        attachments = request.env['ir.attachment'].sudo()
        attachment = attachments.search([
            ('res_model', '=', 'product.product'),
            ('res_id', '=', product.id),
            ('res_field', '=', 'image_variant_%s' % size),
        ], limit=1)
        if not attachment:
            attachment = attachments.search([
                ('res_model', '=', 'product.template'),
                ('res_id', '=', product.product_tmpl_id.id),
                ('res_field', '=', 'image_%s' % size),
            ], limit=1)
        return attachment

    def _serve_image(self, image_base64, identifier):
        """Base64 görsel verisini binary HTTP yanıtı olarak döndürür (yalnız yedek yol)."""
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
        if _etag_matches(etag):
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

