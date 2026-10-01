"""Servis katmanı testleri (veritabanı gerektirmez).

Çalıştırma: odoo-bin -d <db> -u ugurlar_ai_studio --test-enable --test-tags /ugurlar_ai_studio
"""
import base64
import io
from unittest.mock import patch

from odoo.tests import BaseCase, TransactionCase, tagged

from ..services import category_constants as cc
from ..services import fal_provider as fal_provider_module
from ..services.fal_error_handler import parse_fal_error
from ..services.fal_provider import FalProvider
from ..services import garment_analyzer as analyzer_module
from ..services.garment_analyzer import build_generation_prompt, detect_image_tags
from ..services.garment_preprocessor import (
    crop_to_content, inpaint_security_tags, preprocess_garment_image, tag_box_to_pixels,
)
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

    def test_prompt_sub_type_handles_turkish_uppercase(self):
        # 'ELBİSE'.lower() birleşik noktalı i üretir; elbise algılanmazsa manken pantolonlu kalır
        from ..services.garment_analyzer import _detect_sub_type
        self.assertEqual(_detect_sub_type('', 'ELBİSE NOCTURNE'), 'dress')
        self.assertEqual(_detect_sub_type('dress', 'TULUM'), 'jumpsuit')
        self.assertEqual(_detect_sub_type('', 'MİNİ ETEK'), 'skirt')

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
        self.assertLessEqual(len(p.split()), 125)

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

    def test_every_view_asks_for_clean_product(self):
        # negative_prompt desteklenmiyor: etiket kuralı pozitif cümleyle HER şablonda olmalı
        for (sub_type, photo_type) in cc.SEEDREAM_TEMPLATES:
            category = {'dress': 'dress', 'jumpsuit': 'dress', 'bottoms': 'bottoms'}.get(sub_type, 'tops')
            p = self._build({'garmentType': 'Ürün', 'clothingCategory': category}, photo_type)
            self.assertIn('nothing added', p, (sub_type, photo_type))
            # Nesne adı olumsuzlansa bile model onu çizer: etiket kelimeleri geçmemeli
            for word in ('tag', 'label', 'patch'):
                self.assertNotIn(word, p.lower(), (sub_type, photo_type, word))

    def test_back_view_takes_design_from_back_photo(self):
        p = self._build({'garmentType': 'Bluz', 'clothingCategory': 'tops'}, 'back')
        self.assertIn('back design only from Image 2', p)

    def test_no_turkish_leaks_into_prompt(self):
        analysis = {'garmentType': 'Çiçekli Şifon Elbise', 'garmentTypeEn': 'floral chiffon dress',
                    'clothingCategory': 'dress', 'primaryColor': 'Kırmızı', 'primaryColorEn': 'red',
                    'fabricType': 'Şifon', 'fabricTypeEn': 'chiffon', 'collarType': 'Kayık Yaka',
                    'collarTypeEn': 'boat', 'garmentLength': 'midi'}
        for view in ('front', 'back', 'side'):
            p = self._build(analysis, view)
            self.assertFalse(set(p) & set('çğıöşüÇĞİÖŞÜ'), (view, p))

    def test_unknown_turkish_words_do_not_leak(self):
        p = self._build({'garmentType': 'Gömlek', 'clothingCategory': 'tops',
                         'collarType': 'Gömlek Yakası', 'hasGraphic': True,
                         'graphicDescriptionEn': 'small logo on chest.'})
        self.assertNotIn('Yakası', p)
        self.assertNotIn('collar neckline', p)
        self.assertNotIn('..', p)

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
        with patch.object(FalProvider, 'run_queued',
                          lambda self, endpoint, arguments, on_enqueue=None, **kw:
                          fake_subscribe(endpoint, arguments=arguments,
                                         on_enqueue=(lambda rid: on_enqueue(rid, endpoint)) if on_enqueue else None)):
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

    def test_candidates_use_num_images_and_are_billed(self):
        captured, result = self._call(photo_type='front', num_samples=3)
        self.assertEqual(captured['arguments']['num_images'], 3)
        # fake_subscribe tek görsel döndürür; maliyet dönen görsel sayısına göre
        self.assertAlmostEqual(result['cost'], 0.135 + 0.0045, places=4)

    def test_queue_timeout_does_not_cancel_the_paid_job(self):
        # fal_client.subscribe(client_timeout) süre dolunca işi iptal eder; biz etmemeliyiz
        from ..services.fal_provider import FalQueueTimeout

        class Handle:
            request_id = 'req-9'

            def status(self):
                return object()  # hiç tamamlanmıyor

        seen = []
        with patch.object(fal_provider_module, 'fal_client') as fc:
            fc.submit.return_value = Handle()
            fc.Completed = type('Completed', (), {})
            with self.assertRaises(FalQueueTimeout):
                FalProvider('k').run_queued('app', {}, on_enqueue=lambda r, a: seen.append(r),
                                            timeout=0, poll_interval=0)
        self.assertEqual(seen, ['req-9'])
        fc.cancel.assert_not_called()

    def test_on_enqueue_receives_request_id_and_endpoint(self):
        seen = []
        captured, _result = self._call(photo_type='front', on_enqueue=lambda rid, app: seen.append((rid, app)))
        captured['on_enqueue']('req-1')
        self.assertEqual(seen, [('req-1', 'bytedance/seedream/v5/pro/edit')])


@tagged('post_install', '-at_install', 'ugurlar_ai_studio')
class TestSeedreamV4Arguments(BaseCase):
    """Seedream v4 Edit: seed alır/döndürür; ön görünüm seed'i arka/yan çekimlere aktarılır."""

    def _call(self, **kwargs):
        captured = {}

        def fake_run(self, endpoint, arguments, on_enqueue=None, **kw):
            captured['endpoint'] = endpoint
            captured['arguments'] = arguments
            return {'images': [{'url': 'https://example.com/out.jpg'}], 'seed': 746406749}

        with patch.object(FalProvider, 'run_queued', fake_run):
            result = FalProvider('test-key').virtual_tryon(
                'MODEL', 'GARMENT', model_name='seedream/v4/edit', prompt='p', **kwargs)
        return captured, result

    def test_endpoint_and_seed_are_sent(self):
        captured, result = self._call(photo_type='back', front_output_url='FRONT', seed=123)
        args = captured['arguments']
        self.assertEqual(captured['endpoint'], 'fal-ai/bytedance/seedream/v4/edit')
        self.assertEqual(args['seed'], 123)
        self.assertEqual(args['image_urls'], ['MODEL', 'GARMENT', 'FRONT'])
        self.assertEqual(args['max_images'], 1)
        self.assertNotIn('output_format', args)  # v4 şemasında yok
        self.assertEqual(result['seed'], 746406749)

    def test_front_without_seed(self):
        captured, _result = self._call(photo_type='front', seed=False)
        self.assertNotIn('seed', captured['arguments'])
        self.assertEqual(captured['arguments']['image_urls'], ['MODEL', 'GARMENT'])

    def test_cost_per_image(self):
        _captured, result = self._call(photo_type='front')
        self.assertAlmostEqual(result['cost'], 0.03, places=4)



@tagged('post_install', '-at_install', 'ugurlar_ai_studio')
class TestTryonSettings(TransactionCase):

    def test_single_candidate_and_model_setting(self):
        from ..models.ai_studio_session import _get_candidate_count, _get_tryon_model
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('ugurlar_ai_studio.candidate_count', '4')
        self.assertEqual(_get_candidate_count(self.env, 'front', 'fal'), 1)
        params.set_param('ugurlar_ai_studio.tryon_model', 'seedream_v4')
        self.assertEqual(_get_tryon_model(self.env), 'seedream/v4/edit')
        params.set_param('ugurlar_ai_studio.tryon_model', 'seedream_v5_pro')
        self.assertEqual(_get_tryon_model(self.env), 'seedream/v5/pro/edit')


@tagged('post_install', '-at_install', 'ugurlar_ai_studio')
class TestTagDetection(BaseCase):

    def test_gemini_gets_real_mime_type(self):
        webp = io.BytesIO()
        Image.new('RGB', (10, 10)).save(webp, 'WEBP')
        mime, _data = analyzer_module._prepare_gemini_image(base64.b64encode(webp.getvalue()).decode())
        self.assertEqual(mime, 'image/webp')

    def test_invalid_boxes_are_dropped(self):
        fake = {'securityTags': [
            {'box_2d': [100, 100, 150, 150], 'label': 'alarm_tag', 'confidence': 0.9},
            {'box_2d': [1, 2], 'label': 'price_tag'},
            'garbage',
        ]}
        with patch.object(analyzer_module, '_gemini_json', return_value=fake) as gj:
            tags = detect_image_tags(None, 'IMG', gemini_api_key='k')
        self.assertEqual(len(tags), 1)
        self.assertTrue(gj.call_args.kwargs['deterministic'], 'tespit deterministik olmalı')

    def test_schema_rejection_retries_without_schema(self):
        class Resp:
            def __init__(self, code, payload=None):
                self.status_code, self._payload = code, payload

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise Exception('HTTP %s' % self.status_code)

            def json(self):
                return self._payload

        ok = Resp(200, {'candidates': [{'content': {'parts': [{'text': '{"securityTags": []}'}]}}]})
        calls = []

        def fake_post(url, json=None, **kw):
            calls.append('responseSchema' in json['generationConfig'])
            return Resp(400) if len(calls) == 1 else ok

        with patch.object(analyzer_module, '_prepare_gemini_image', return_value=('image/jpeg', 'AAAA')),                 patch.object(analyzer_module.requests, 'post', side_effect=fake_post):
            result = analyzer_module._gemini_json('k', 'p', 'IMG', schema={'type': 'OBJECT'})
        self.assertEqual(result, {'securityTags': []})
        self.assertEqual(calls, [True, False])


@tagged('post_install', '-at_install', 'ugurlar_ai_studio')
class TestTagErasing(BaseCase):

    def test_box_filtering(self):
        self.assertIsNone(tag_box_to_pixels({'box_2d': [100, 100, 150, 150], 'label': 'design_label'}, 1000, 1000))
        self.assertIsNone(tag_box_to_pixels({'box_2d': [100, 100, 150, 150], 'confidence': 0.2}, 1000, 1000))
        self.assertIsNone(tag_box_to_pixels({'box_2d': [0, 0, 700, 700], 'confidence': 0.9}, 1000, 1000))
        rect = tag_box_to_pixels({'box_2d': [100, 200, 150, 260], 'label': 'alarm_tag', 'confidence': 0.9}, 1000, 1000)
        x1, y1, x2, y2 = rect
        self.assertTrue(x1 < 200 and y1 < 100 and x2 > 260 and y2 > 150, 'kutu dolgulu olmalı')

    def test_crop_to_content(self):
        img = Image.new('RGB', (1000, 1600), 'white')
        ImageDraw.Draw(img).rectangle([400, 600, 600, 1000], fill=(60, 30, 20))
        out = Image.open(io.BytesIO(base64.b64decode(crop_to_content(_jpeg_b64(img)))))
        self.assertLess(out.size[0], 400)
        self.assertLess(out.size[1], 600)

    def test_erase_regions_sends_matching_mask(self):
        uploads = []

        def fake_upload(data, content_type, file_name=None):
            uploads.append(Image.open(io.BytesIO(data)))
            return 'https://cdn/%d' % len(uploads)

        class FakeResp:
            # Silme modeli çıktısı: tamamen beyaz (hangi bölgenin yapıştırıldığı görülsün)
            buf = io.BytesIO()
            Image.new('RGB', (800, 1200), (255, 255, 255)).save(buf, 'PNG')
            content = buf.getvalue()

        img = Image.new('RGB', (800, 1200), (60, 30, 20))
        with patch.object(fal_provider_module, 'fal_client') as fc,                 patch('requests.get', return_value=FakeResp()):
            fc.upload.side_effect = fake_upload
            fc.subscribe.return_value = {'images': [{'url': 'https://out'}]}
            data, cost = FalProvider('k').erase_regions(
                _jpeg_b64(img), [{'box_2d': [100, 100, 150, 200], 'label': 'alarm_tag', 'confidence': 0.9}])
            args = fc.subscribe.call_args.kwargs['arguments']
        self.assertGreater(cost, 0)
        result = Image.open(io.BytesIO(data)).convert('RGB')
        self.assertEqual(result.size, (800, 1200), 'çözünürlük korunmalı')
        self.assertGreater(result.getpixel((120, 150))[1], 200, 'maske bölgesi silme çıktısından gelir')
        self.assertLess(result.getpixel((700, 1100))[1], 60, 'maske dışı orijinal kalır')
        image, mask = uploads
        self.assertEqual(image.size, mask.size, 'FLUX Fill görsel ve maskenin aynı boyutta olmasını ister')
        self.assertEqual(mask.getpixel((120, 150)), 255, 'etiket bölgesi beyaz (doldurulacak)')
        self.assertEqual(mask.getpixel((700, 1100)), 0)
        self.assertEqual(args['mask_url'], 'https://cdn/2')

    def test_erase_falls_back_to_flux_with_object_free_prompt(self):
        calls = []

        def fake_subscribe(app, arguments=None, **kw):
            calls.append((app, arguments))
            if app == FalProvider.ERASE_APP:
                raise Exception('bria down')
            return {'images': [{'url': 'https://out'}]}

        class FakeResp:
            buf = io.BytesIO()
            Image.new('RGB', (400, 600)).save(buf, 'PNG')
            content = buf.getvalue()

        with patch.object(fal_provider_module, 'fal_client') as fc,                 patch('requests.get', return_value=FakeResp()):
            fc.upload.return_value = 'https://cdn/x'
            fc.subscribe.side_effect = fake_subscribe
            data, _cost = FalProvider('k').erase_regions(
                _jpeg_b64(Image.new('RGB', (400, 600))),
                [{'box_2d': [100, 100, 150, 200], 'label': 'alarm_tag', 'confidence': 0.9}])
        self.assertTrue(data)
        self.assertEqual([c[0] for c in calls], [FalProvider.ERASE_APP, FalProvider.FILL_APP])
        self.assertNotIn('prompt', calls[0][1], 'Bria istemsiz çalışmalı')
        fill_prompt = calls[1][1]['prompt'].lower()
        for word in ('tag', 'label', 'pin', 'plastic'):
            self.assertNotIn(word, fill_prompt)

    def test_visual_qc_sends_reference_and_returns_boxes(self):
        fake = {'defects': ['added_label'], 'boxes': [{'code': 'added_label', 'box_2d': [400, 450, 430, 500]}]}
        with patch.object(analyzer_module, '_gemini_json', return_value=fake) as gj:
            res = analyzer_module.visual_quality_check('k', 'RESULT', garment_hint='pantolon',
                                                       reference_image='REF')
        self.assertEqual(gj.call_args.kwargs['extra_images'], ['REF'])
        self.assertEqual(res['codes'], ['added_label'])
        self.assertEqual(len(res['boxes']), 1)

    def test_erase_regions_skips_design_labels(self):
        with patch.object(fal_provider_module, 'fal_client') as fc:
            data, cost = FalProvider('k').erase_regions(
                _jpeg_b64(Image.new('RGB', (100, 100))), [{'box_2d': [10, 10, 20, 20], 'label': 'design_label'}])
        self.assertIsNone(data)
        fc.subscribe.assert_not_called()


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
