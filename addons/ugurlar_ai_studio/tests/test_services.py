"""Servis katmanı testleri (veritabanı gerektirmez).

Çalıştırma: odoo-bin -d <db> -u ugurlar_ai_studio --test-enable --test-tags /ugurlar_ai_studio
"""
import base64
import io
from unittest.mock import patch

from odoo.tests import BaseCase, tagged

from ..services import category_constants as cc
from ..services import fal_provider as fal_provider_module
from ..services.fal_error_handler import parse_fal_error
from ..services.fal_provider import FalProvider
from ..services.garment_analyzer import build_generation_prompt
from ..services.garment_preprocessor import inpaint_security_tags, preprocess_garment_image
from ..services.quality_checker import compute_quality_score, delta_e_ciede2000

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    np = Image = ImageDraw = None


def _jpeg_b64(img):
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=95)
    return base64.b64encode(buf.getvalue()).decode()


@tagged('post_install', '-at_install', 'ugurlar_ai_studio')
class TestGarmentClassifier(BaseCase):

    def test_garment_words_win_over_accessory_words(self):
        cases = {
            'Kemerli Elbise': 'one_piece',       # 'kemer' aksesuar değil
            'Bot Paça Jean': 'bottoms',          # 'bot' ayakkabı değil
            'Salaş Gömlek': 'tops',              # 'sal' şal değil
            'Şal Yaka Ceket': 'tops',
            'Baggy Jean': 'bottoms',             # 'bag' çanta değil
            'Kemerli Pantolon': 'bottoms',
            'Atletik Kesim Pantolon': 'bottoms',
        }
        for text, expected in cases.items():
            self.assertEqual(cc.classify_garment_text(text)[0], expected, text)

    def test_accessories_and_shoes(self):
        cases = {
            'Deri Çanta': 'bags',
            'Sırt Çantası': 'bags',
            'Topuklu Ayakkabı': 'shoes',
            'Kadın Bot': 'shoes',
            'Çizmeler': 'shoes',
            'Siyah Kemer': 'accessories',
            'Kolye': 'accessories',
        }
        for text, expected in cases.items():
            self.assertEqual(cc.classify_garment_text(text)[0], expected, text)

    def test_turkish_uppercase(self):
        self.assertEqual(cc.classify_garment_text('ELBİSE')[0], 'one_piece')
        self.assertEqual(cc.classify_garment_text('AYAKKABI')[0], 'shoes')
        self.assertEqual(cc.classify_garment_text('Elbiseler')[0], 'one_piece')

    def test_no_match(self):
        self.assertEqual(cc.classify_garment_text('Hediye Kartı'), (None, None))


@tagged('post_install', '-at_install', 'ugurlar_ai_studio')
class TestPromptBuilder(BaseCase):

    def _build(self, analysis, photo_type='front', **kw):
        return build_generation_prompt(analysis, {}, kw.pop('locks', []), kw.pop('extra', ''),
                                       photo_type=photo_type, provider_type='fal', **kw)['positive']

    def test_dress_prompt_is_english_and_positive(self):
        p = self._build({'garmentType': 'Triko Elbise', 'clothingCategory': 'dress',
                         'primaryColor': 'Siyah', 'fabricType': 'Triko', 'garmentLength': 'midi'})
        self.assertIn('black knit dress', p)
        self.assertNotIn('Siyah', p)
        self.assertNotIn('knit knit', p)
        self.assertNotIn('Figure', p)
        self.assertLessEqual(p.lower().count('trousers'), 1, 'istenmeyen nesne tekrar edilmemeli')
        self.assertLessEqual(len(p.split()), 110)

    def test_jumpsuit_does_not_get_bare_legs(self):
        p = self._build({'garmentType': 'Tulum', 'clothingCategory': 'dress', 'garmentLength': 'maxi'})
        self.assertIn('jumpsuit', p)
        self.assertNotIn('bare legs', p.lower())

    def test_scene_replaces_studio(self):
        locks = ['Hasselblad editorial photography, seamless white cyclorama studio.']
        p = self._build({'garmentType': 'Elbise', 'clothingCategory': 'dress'},
                        locks=locks, scene_prompt='Sunlit Paris street.')
        self.assertIn('Sunlit Paris street.', p)
        self.assertNotIn('white studio', p.lower())
        self.assertNotIn('cyclorama', p.lower())

    def test_back_view_mentions_front_reference_only_when_sent(self):
        analysis = {'garmentType': 'Bluz', 'clothingCategory': 'tops'}
        self.assertIn('Image 3', self._build(analysis, 'back', has_front_ref=True))
        self.assertNotIn('Image 3', self._build(analysis, 'back', has_front_ref=False))

    def test_all_templates_format(self):
        for (sub_type, photo_type) in cc.SEEDREAM_TEMPLATES:
            category = {'dress': 'dress', 'jumpsuit': 'dress', 'bottoms': 'bottoms'}.get(sub_type, 'tops')
            name = {'jumpsuit': 'Tulum', 'skirt': 'Etek', 'shorts': 'Şort'}.get(sub_type, 'Ürün')
            p = self._build({'garmentType': name, 'clothingCategory': category}, photo_type)
            self.assertNotIn('{', p, (sub_type, photo_type))


@tagged('post_install', '-at_install', 'ugurlar_ai_studio')
class TestSeedreamArguments(BaseCase):

    def _call(self, **kwargs):
        captured = {}

        def fake_subscribe(endpoint, arguments=None, **kw):
            captured['endpoint'] = endpoint
            captured['arguments'] = arguments
            captured['on_enqueue'] = kw.get('on_enqueue')
            return {'images': [{'url': 'https://example.com/out.jpg'}]}

        provider = FalProvider('test-key')
        with patch.object(fal_provider_module, 'fal_client') as fc:
            fc.subscribe.side_effect = fake_subscribe
            result = provider.virtual_tryon('MODEL', 'GARMENT', model_name='seedream/v5/pro/edit',
                                            prompt='p', negative_prompt='neg', seed=123, **kwargs)
        return captured, result

    def test_only_schema_parameters_are_sent(self):
        captured, _result = self._call(photo_type='front')
        args = captured['arguments']
        for unsupported in ('seed', 'negative_prompt', 'aspect_ratio', 'resolution', 'limit_generations'):
            self.assertNotIn(unsupported, args)
        self.assertEqual(args['image_size'], FalProvider.SEEDREAM_IMAGE_SIZES['hd'])

    def test_model_is_first_reference(self):
        captured, _result = self._call(photo_type='back', front_output_url='FRONT')
        self.assertEqual(captured['arguments']['image_urls'], ['MODEL', 'GARMENT', 'FRONT'])

    def test_cost_matches_fal_pricing(self):
        _captured, result = self._call(photo_type='back', front_output_url='FRONT')
        self.assertAlmostEqual(result['cost'], 0.135 + 2 * 0.0045, places=4)
        _captured, result = self._call(photo_type='front',
                                       image_size=FalProvider.SEEDREAM_IMAGE_SIZES['standard'])
        self.assertAlmostEqual(result['cost'], 0.0675 + 0.0045, places=4)

    def test_on_enqueue_receives_request_id_and_endpoint(self):
        seen = []
        captured, _result = self._call(photo_type='front', on_enqueue=lambda rid, app: seen.append((rid, app)))
        captured['on_enqueue']('req-1')
        self.assertEqual(seen, [('req-1', 'bytedance/seedream/v5/pro/edit')])


@tagged('post_install', '-at_install', 'ugurlar_ai_studio')
class TestImagePipeline(BaseCase):

    def test_preprocess_preserves_garment_color(self):
        red = Image.new('RGB', (1200, 1600), (200, 30, 40))
        out = preprocess_garment_image(_jpeg_b64(red))
        img = Image.open(io.BytesIO(base64.b64decode(out['image_base64']))).convert('RGB')
        mean = np.array(img).reshape(-1, 3).mean(0)
        self.assertGreater(mean[0], 150, 'kırmızı kanal korunmalı (gray-world griye çekiyordu)')
        self.assertLess(mean[1], 80)

    def test_inpaint_skips_low_confidence_and_huge_boxes(self):
        arr = np.full((1000, 1000, 3), 255, np.uint8)
        arr[100:150, 100:150] = 0
        arr[200:250, 200:250] = 0
        tags = [
            {'box_2d': [100, 100, 150, 150], 'confidence': 0.95},
            {'box_2d': [200, 200, 250, 250], 'confidence': 0.3},
            {'box_2d': [0, 0, 600, 600], 'confidence': 0.99},
        ]
        res = inpaint_security_tags(arr.copy(), tags)
        self.assertEqual(res[125, 125].tolist(), [255, 255, 255])
        self.assertEqual(res[225, 225].tolist(), [0, 0, 0])

    def test_ciede2000_reference_value(self):
        # Sharma et al. (2005) test verisi
        self.assertAlmostEqual(delta_e_ciede2000((50, 2.6772, -79.7751), (50, 0, -82.7485)), 2.0425, places=3)

    def test_quality_score_ranks_color_shift(self):
        orig = Image.new('RGB', (800, 1200), 'white')
        ImageDraw.Draw(orig).rectangle([200, 200, 600, 1000], fill=(200, 30, 40))

        def generated(color):
            g = Image.new('RGB', (1664, 2496), 'white')
            ImageDraw.Draw(g).rectangle([500, 600, 1100, 1900], fill=color)
            return g

        good = compute_quality_score(_jpeg_b64(orig), _jpeg_b64(generated((198, 32, 42))))
        bad = compute_quality_score(_jpeg_b64(orig), _jpeg_b64(generated((40, 60, 160))))
        self.assertGreater(good['score'], bad['score'] + 20)
        flagged = compute_quality_score(_jpeg_b64(orig), _jpeg_b64(generated((198, 32, 42))),
                                        visual_qc={'issues': ['Elbise altında pantolon var']})
        self.assertFalse(flagged['is_acceptable'])


@tagged('post_install', '-at_install', 'ugurlar_ai_studio')
class TestFalErrors(BaseCase):

    def test_parse_returns_retry_hint(self):
        parsed = parse_fal_error(Exception('Connection reset by peer'))
        self.assertIn('is_retryable', parsed)
        self.assertIn('error_type', parsed)
        self.assertTrue(parsed['message'])
