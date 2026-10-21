# -*- coding: utf-8 -*-
"""TODO-18: Power BI uçları — stream + checksum ETag, 304, sayfalı liste, eski URL uyumu."""
import base64
import io
import json
from unittest.mock import patch

from PIL import Image

from odoo.tests import HttpCase, tagged

from odoo.addons.ugurlar_images.controllers.powerbi_controller import PowerBIController

TOKEN = 'test-powerbi-token'


def _png_b64(color):
    buf = io.BytesIO()
    Image.new('RGB', (800, 800), color).save(buf, 'PNG')
    return base64.b64encode(buf.getvalue())


@tagged('post_install', '-at_install', 'ugurlar_images')
class TestPowerBI(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env['ir.config_parameter'].sudo()
        params.set_param('ugurlar_images.powerbi_api_key', TOKEN)
        params.set_param('ugurlar_images.powerbi_enabled', 'True')
        params.set_param('ugurlar_images.powerbi_default_limit', '0')
        # NEDEN: toplu create'te görsel yalnız ilk şablona yazılıyor; tek tek oluşturulur.
        cls.products = cls.env['product.product']
        for i, color in enumerate(('red', 'green', 'blue')):
            cls.products |= cls.env['product.product'].create({
                'name': 'PBI Test %s' % i, 'barcode': 'PBITEST%s' % i,
                'image_1920': _png_b64(color),
            })
        cls.env.flush_all()

    def _get(self, path, **kw):
        headers = kw.pop('headers', None)
        sep = '&' if '?' in path else '?'
        return self.url_open('%s%stoken=%s' % (path, sep, TOKEN), headers=headers, **kw)

    # --- Yetki (davranış değişmemeli) ---------------------------------

    def test_token_olmadan_403(self):
        self.assertEqual(self.url_open('/api/powerbi/products').status_code, 403)
        self.assertEqual(self.url_open('/api/powerbi/image/PBITEST0').status_code, 403)
        self.assertEqual(
            self.url_open('/api/powerbi/image/PBITEST0?token=yanlis').status_code, 403)

    def test_ascii_disi_token_403(self):
        # G3: ASCII dışı token TypeError → 500 vermemeli
        self.assertEqual(self.url_open('/api/powerbi/products?token=ğüş').status_code, 403)

    def test_kapali_iken_403(self):
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_images.powerbi_enabled', 'False')
        self.assertEqual(self._get('/api/powerbi/products').status_code, 403)
        self.assertEqual(self._get('/api/powerbi/image/PBITEST0').status_code, 403)

    # --- Görsel: stream + checksum ETag -------------------------------

    def test_gorsel_200_sonra_304_stream(self):
        with patch.object(PowerBIController, '_serve_image') as base64_yolu:
            response = self._get('/api/powerbi/image/PBITEST0')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers['Content-Type'].startswith('image/'))
            self.assertTrue(response.content)
            etag = response.headers['ETag']
            # Tek varyantlı üründe görsel şablon ekinde durur.
            checksum = self.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'product.template'),
                ('res_id', '=', self.products[0].product_tmpl_id.id),
                ('res_field', '=', 'image_512'),
            ], limit=1).checksum
            self.assertTrue(checksum)
            self.assertEqual(etag.strip('"'), checksum)

            again = self._get('/api/powerbi/image/PBITEST0', headers={'If-None-Match': etag})
            self.assertEqual(again.status_code, 304)
            self.assertFalse(again.content)
            self.assertEqual(
                self._get('/api/powerbi/image/PBITEST0',
                          headers={'If-None-Match': 'W/' + etag}).status_code, 304)
            other = self._get('/api/powerbi/image/PBITEST0', headers={'If-None-Match': '"baska"'})
            self.assertEqual(other.status_code, 200)
            base64_yolu.assert_not_called()

    def test_gorsel_id_ve_boyut(self):
        pid = self.products[1].id
        small = self._get('/api/powerbi/image-by-id/%s' % pid)
        large = self._get('/api/powerbi/image-by-id/%s?size=1920' % pid)
        self.assertEqual((small.status_code, large.status_code), (200, 200))
        self.assertNotEqual(small.headers['ETag'], large.headers['ETag'])
        # Varsayılan küçük varyant (512): 800x800 kaynaktan küçük
        with Image.open(io.BytesIO(small.content)) as img:
            self.assertLessEqual(max(img.size), 512)
        with Image.open(io.BytesIO(large.content)) as img:
            self.assertEqual(img.size, (800, 800))

    def test_gorsel_hatalari(self):
        self.assertEqual(self._get('/api/powerbi/image/YOKBARKOD').status_code, 404)
        self.assertEqual(self._get('/api/powerbi/image/PBITEST0?size=999').status_code, 400)
        self.assertEqual(self._get('/api/powerbi/image-by-id/999999999').status_code, 404)

    def test_eksik_boyut_eki_base64_yedege_duser(self):
        self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'product.product'),
            ('res_id', '=', self.products[2].id),
            ('res_field', '=', 'image_variant_512'),
        ]).unlink()
        self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'product.template'),
            ('res_id', '=', self.products[2].product_tmpl_id.id),
            ('res_field', '=', 'image_512'),
        ]).unlink()
        self.env.flush_all()
        self.env.invalidate_all()
        response = self._get('/api/powerbi/image/PBITEST2')
        self.assertEqual(response.status_code, 404)  # yedek yol çökmeden 'görsel yok' döner

    # --- Liste: sayfalama + ETag --------------------------------------

    def test_liste_eski_url_tum_liste_dizi(self):
        response = self._get('/api/powerbi/products')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIsInstance(data, list)
        barcodes = {row['barcode'] for row in data}
        self.assertTrue({'PBITEST0', 'PBITEST1', 'PBITEST2'} <= barcodes)
        row = next(r for r in data if r['barcode'] == 'PBITEST0')
        self.assertEqual(
            set(row), {'product_id', 'template_id', 'barcode', 'default_code',
                       'template_name', 'image_url'})
        self.assertIn('/api/powerbi/image/PBITEST0?token=%s&size=512' % TOKEN, row['image_url'])
        self.assertEqual(int(response.headers['X-Total-Count']), len(data))
        self.assertNotIn('X-Next-Offset', response.headers)

    def test_liste_sayfalama(self):
        full = json.loads(self._get('/api/powerbi/products').content)
        self.assertGreaterEqual(len(full), 3)
        first = self._get('/api/powerbi/products?limit=2&offset=0')
        second = self._get('/api/powerbi/products?limit=2&offset=2')
        self.assertEqual(json.loads(first.content), full[0:2])
        self.assertEqual(json.loads(second.content), full[2:4])
        self.assertEqual(int(first.headers['X-Total-Count']), len(full))
        self.assertEqual(first.headers['X-Next-Offset'], '2')
        last = self._get('/api/powerbi/products?limit=%s&offset=%s' % (len(full), 0))
        self.assertEqual(last.headers['X-Next-Offset'], '')
        self.assertEqual(self._get('/api/powerbi/products?limit=abc').status_code, 400)
        self.assertEqual(self._get('/api/powerbi/products?limit=-1').status_code, 400)

    def test_liste_varsayilan_limit_ayari(self):
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_images.powerbi_default_limit', '1')
        response = self._get('/api/powerbi/products')
        self.assertEqual(len(json.loads(response.content)), 1)
        # Açık limit ayarı ezer
        self.assertGreaterEqual(len(json.loads(self._get('/api/powerbi/products?limit=3').content)), 3)

    def test_liste_etag_304_ve_degisimde_200(self):
        response = self._get('/api/powerbi/products')
        etag = response.headers['ETag']
        again = self._get('/api/powerbi/products', headers={'If-None-Match': etag})
        self.assertEqual(again.status_code, 304)
        self.assertFalse(again.content)
        self.assertEqual(again.headers['ETag'], etag)
        # Eski tırnaksız biçim de eşleşir
        self.assertEqual(
            self._get('/api/powerbi/products',
                      headers={'If-None-Match': etag.strip('"')}).status_code, 304)
        # Sayfa parametresi farklı → farklı ETag
        paged = self._get('/api/powerbi/products?limit=1')
        self.assertNotEqual(paged.headers['ETag'], etag)

        self.products[0].default_code = 'PBI-DEGISTI'
        self.env.flush_all()
        # NEDEN: test tek transaction'da koşar, now() sabittir; gerçekte her yazma farklı
        # işlemde yeni write_date alır. Farkı elle simüle ediyoruz.
        self.env.cr.execute(
            "UPDATE product_product SET write_date = write_date + interval '1 hour' WHERE id = %s",
            [self.products[0].id])
        changed = self._get('/api/powerbi/products', headers={'If-None-Match': etag})
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(changed.headers['ETag'], etag)

    def test_liste_gzip(self):
        response = self.url_open(
            '/api/powerbi/products?token=%s&limit=1' % TOKEN,
            headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)  # requests gzip'i açar
        self.assertEqual(response.headers.get('Content-Encoding'), 'gzip')
