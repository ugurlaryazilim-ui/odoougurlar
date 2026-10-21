import base64
import gc
import io
import os
import tracemalloc
import zipfile
from unittest.mock import patch

from PIL import Image

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

WIZARD_MODULE = 'odoo.addons.ugurlar_images.wizards.bulk_image_wizard'


def _png(color=(200, 10, 10)):
    buf = io.BytesIO()
    Image.new('RGB', (8, 8), color).save(buf, 'PNG')
    return buf.getvalue()


def _zip(files):
    """{ad: bayt} → bellek-içi ZIP baytları."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


@tagged('post_install', '-at_install')
class TestBulkImageWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Attr = cls.env['product.attribute']
        renk = Attr.create({'name': 'Renk', 'value_ids': [(0, 0, {'name': 'Kırmızı'}), (0, 0, {'name': 'Mavi'})]})
        beden = Attr.create({'name': 'Beden', 'value_ids': [(0, 0, {'name': 'S'}), (0, 0, {'name': 'M'})]})
        cls.tmpl = cls.env['product.template'].create({
            'name': 'Test Tişört',
            'attribute_line_ids': [
                (0, 0, {'attribute_id': renk.id, 'value_ids': [(6, 0, renk.value_ids.ids)]}),
                (0, 0, {'attribute_id': beden.id, 'value_ids': [(6, 0, beden.value_ids.ids)]}),
            ],
        })
        # (renk, beden) → varyant; barkodlar B-KS, B-KM, B-MS, B-MM
        cls.variants = {}
        for v in cls.tmpl.product_variant_ids:
            names = v.product_template_attribute_value_ids.mapped('name')
            code = 'B-' + ('K' if 'Kırmızı' in names else 'M') + ('S' if 'S' in names else 'M')
            v.barcode = code
            cls.variants[code] = v
        cls.plain_a = cls.env['product.product'].create({'name': 'Düz A', 'barcode': 'P-A'})
        cls.plain_b = cls.env['product.product'].create({'name': 'Düz B', 'barcode': 'P-B'})

    def _wizard(self, files, name='t.zip'):
        return self.env['ugurlar.bulk.image.wizard'].create({
            'zip_file': base64.b64encode(_zip(files)),
            'zip_filename': name,
        })

    def _import(self, wiz):
        # NEDEN: sihirbaz log'u ayrı cursor'da yazar; test modunda o cursor test transaction'ını
        # paylaşır, aksi halde log gerçekten commit edilir ve test DB'sini kirletir.
        with self.enter_registry_test_mode():
            return wiz.action_import_images()

    def _log(self, name='ZIP Yükleme: t.zip'):
        self.env.invalidate_all()
        return self.env['ugurlar.image.sync.log'].search([('name', '=', name)], limit=1)

    def test_basarili_yukleme_kardeslere_tek_write(self):
        wiz = self._wizard({
            'B-KS_1.png': _png(),
            'B-KS_2.png': _png((1, 2, 3)),
            'P-A_1.png': _png(),
            'bilinmeyen_1.png': _png(),
            'not.txt': b'x',
        })
        writes = []
        Product = self.env.registry['product.product']
        orig_write = Product.write

        def spy(rec, vals):
            if 'image_variant_1920' in vals:
                writes.append(rec.ids)
            return orig_write(rec, vals)

        with patch.object(Product, 'write', spy):
            self._import(wiz)

        # KS ana resmi kırmızı kardeşi KM ile TEK write'ta yazılır; mavi varyantlara dokunulmaz
        ks, km = self.variants['B-KS'], self.variants['B-KM']
        self.assertIn(sorted([ks.id, km.id]), [sorted(w) for w in writes])
        self.assertEqual(len([w for w in writes if ks.id in w]), 1)
        self.assertTrue(ks.image_variant_1920 and km.image_variant_1920)
        self.assertFalse(self.variants['B-MS'].image_variant_1920)
        # ek resim: her iki kırmızı varyanta
        extras = self.env['product.image'].search([('product_variant_id', 'in', [ks.id, km.id])])
        self.assertEqual(len(extras), 2)
        self.assertTrue(self.plain_a.image_variant_1920)

        log = self._log()
        self.assertEqual(log.state, 'done')
        self.assertEqual(log.matched_count, 2)
        self.assertEqual(log.error_count, 1)  # bilinmeyen barkod
        self.assertEqual(log.skipped_count, 1)  # .txt
        self.assertIn('bilinmeyen', wiz.result_message)

    def test_bozuk_gorsel_digerlerini_geri_almaz(self):
        wiz = self._wizard({
            'P-A_1.png': _png(),
            'P-B_1.png': b'bu bir gorsel degil',
            'B-MS_1.png': _png(),
        })
        self._import(wiz)

        self.assertTrue(self.plain_a.image_variant_1920)
        self.assertFalse(self.plain_b.image_variant_1920)  # savepoint ile geri alındı
        self.assertTrue(self.variants['B-MS'].image_variant_1920)
        self.assertTrue(self.variants['B-MM'].image_variant_1920)  # renk kardeşi
        log = self._log()
        self.assertEqual(log.state, 'done')
        self.assertEqual(log.matched_count, 2)
        self.assertEqual(log.error_count, 1)
        self.assertIn('P-B', log.detail_log)

    def test_dosya_sayisi_siniri(self):
        wiz = self._wizard({'P-A_1.png': _png(), 'P-B_1.png': _png()})
        with patch(f'{WIZARD_MODULE}.MAX_ZIP_FILES', 1):
            with self.assertRaises(UserError):
                self._import(wiz)
        self.assertFalse(self.plain_a.image_variant_1920)

    def test_toplam_boyut_siniri_log_kalir(self):
        wiz = self._wizard({'P-A_1.png': _png()})
        # NEDEN: assertRaises savepoint'i geri alır ve log'u da silerdi; log'un ayrı cursor'da
        # yazıldığını doğrulamak için try/except kullanılır (DERSLER: assertRaises).
        try:
            with patch(f'{WIZARD_MODULE}.MAX_ZIP_TOTAL_BYTES', 10):
                self._import(wiz)
            self.fail('UserError bekleniyordu')
        except UserError as e:
            self.assertIn('boyutu', str(e))
        log = self._log()
        self.assertEqual(log.state, 'error')
        self.assertIn('HATA', log.detail_log)

    def test_buyuk_tek_gorsel_atlanir(self):
        wiz = self._wizard({'P-A_1.png': _png(), 'P-B_1.png': _png()})
        with patch(f'{WIZARD_MODULE}.MAX_IMAGE_BYTES', len(_png()) - 1):
            self._import(wiz)
        self.assertFalse(self.plain_a.image_variant_1920)
        self.assertEqual(self._log().skipped_count, 2)

    def _peak_growth(self, n, png):
        """n barkodluk ZIP'i içe aktarırken tracemalloc tepe büyümesini (bayt) döndürür."""
        products = self.env['product.product'].create(
            [{'name': f'Bellek {n}-{i}', 'barcode': f'MEM{n}-{i}'} for i in range(n)])
        wiz = self._wizard({f'MEM{n}-{i}_1.png': png for i in range(n)})
        self.env.flush_all()
        gc.collect()
        tracemalloc.start()
        try:
            base = tracemalloc.get_traced_memory()[0]
            self._import(wiz)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertTrue(all(products.mapped('image_variant_1920')))
        return peak - base

    def test_bellek_barkod_sayisindan_bagimsiz(self):
        # NEDEN: ORM önbelleği barkod başına birikirse (görsel + 1024/512/256/128 yeniden
        # boyutları) tepe bellek barkod sayısıyla doğrusal büyür ve prod'da limit_memory_soft'a çarpar.
        # Gürültü görsel: sıkışmaz ve 1100px → 1024 yeniden boyutu gerçekten üretilir.
        buf = io.BytesIO()
        Image.frombytes('RGB', (1100, 1100), os.urandom(1100 * 1100 * 3)).save(buf, 'PNG')
        png = buf.getvalue()
        small = self._peak_growth(5, png)
        large = self._peak_growth(20, png)
        # 15 fazladan barkod birikseydi fark >= 15 * len(png); bağımsızsa ~0. Eşik: 3 görsel boyutu.
        self.assertLess(large - small, 3 * len(png),
                        f'tepe bellek barkoda bağlı büyüyor: N=5 {small}, N=20 {large}, görsel {len(png)}')

    def test_varlik_kontrolu_icerigi_okumaz(self):
        # B4: "dosya seçildi mi" kontrolü tüm ZIP'i base64 olarak belleğe almamalı
        wiz = self._wizard({'P-A_1.png': _png()})
        self.env.flush_all()
        self.env.invalidate_all()
        Att = type(self.env['ir.attachment'])
        with patch.object(Att, '_compute_datas', autospec=True) as datas, \
                patch.object(type(wiz), '_run_import', side_effect=UserError('dur')), \
                self.assertRaises(UserError):
            self._import(wiz)
        datas.assert_not_called()

    def test_gecersiz_zip(self):
        wiz = self.env['ugurlar.bulk.image.wizard'].create({
            'zip_file': base64.b64encode(b'zip degil'), 'zip_filename': 't.zip'})
        with self.assertRaises(UserError):
            self._import(wiz)
