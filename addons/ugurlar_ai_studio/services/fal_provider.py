# fal.ai provider implementation.
#
# fal_client SDK kullanir - kuyruk destekli, otomatik retry,
# timeout yonetimi ve yapisal hata ayristirma entegrasyonu ile.

import base64
import logging
import threading
import time


from .ai_provider_base import AIProviderBase

_logger = logging.getLogger(__name__)

try:
    import fal_client
except ImportError:
    fal_client = None
    _logger.warning(
        'fal-client kurulu degil. AI ozellikleri calismayacak. '
        'Kurulum: pip install fal-client'
    )


class FalProvider(AIProviderBase):
    # fal.ai FASHN v1.6 implementasyonu.
    #
    # Tum API cagrilari fal_client.subscribe() ile yapilir:
    # - Kuyruk destekli (otomatik retry, 10 kez)
    # - client_timeout ile zaman asimi kontrolu
    # - on_queue_update ile ilerleme takibi

    ENDPOINTS = {
        'tryon_fashn': 'fal-ai/fashn/tryon/v1.6',
        'tryon_kolors': 'fal-ai/kling/v1-5/kolors-virtual-try-on',
        'bg_remove': 'fal-ai/birefnet',
        'flux_schnell': 'fal-ai/flux/schnell',
        'flux_pro': 'fal-ai/flux-pro/v1.1',
        'nano_banana': 'fal-ai/nano-banana-2/edit',
        'seedream': 'bytedance/seedream/v5/pro/edit',
        'any_llm': 'fal-ai/any-llm',
        'flux_kontext': 'fal-ai/flux-kontext/dev',
    }

    # Endpoint basina tahmini maliyet (USD)
    ESTIMATED_COSTS = {
        'fal-ai/fashn/tryon/v1.6': 0.075,
        'fal-ai/birefnet': 0.002,
        'fal-ai/flux/schnell': 0.003,
        'fal-ai/flux-pro/v1.1': 0.05,
        'fal-ai/nano-banana-2/edit': 0.04,
        'bytedance/seedream/v5/pro/edit': 0.05,
        'fal-ai/any-llm': 0.001,
        'fal-ai/flux-kontext/dev': 0.025,
    }

    # Thread-safety: os.environ mutasyonu tek noktadan kontrol edilir
    _fal_key_lock = threading.Lock()

    def __init__(self, api_key):
        import os
        with FalProvider._fal_key_lock:
            os.environ['FAL_KEY'] = api_key
        self.api_key = api_key

    def _check_client(self):
        if fal_client is None:
            raise ImportError(
                'fal-client paketi kurulu degil. '
                'Kurulum: pip install fal-client'
            )

    def get_estimated_cost(self, endpoint):
        # Endpoint icin tahmini maliyeti dondur (USD).
        return self.ESTIMATED_COSTS.get(endpoint, 0.01)

    def virtual_tryon(self, model_image_url, garment_image_url,
                      category='tops', mode='balanced', **kwargs):
        """Manken uzerine giydirme — thin API client.

        Prompt mantigi garment_analyzer.py'de merkezi olarak olusturulur.
        Bu fonksiyon sadece:
        1. Image URL'leri hazirlar (Figure indexleme)
        2. Detail referans Figure notlarini ekler
        3. fal_client.subscribe() ile API cagrisini yapar
        """
        self._check_client()

        model_name = kwargs.get('model_name') or 'tryon-v1.6'
        endpoint = kwargs.get('endpoint')
        if not endpoint:
            if 'seedream' in model_name:
                endpoint = self.ENDPOINTS['seedream']
            elif 'nano-banana' in model_name:
                endpoint = self.ENDPOINTS['nano_banana']
            elif 'max' in model_name:
                endpoint = 'fal-ai/fashn/tryon-max'
            elif 'v1.6' in model_name or 'v1-6' in model_name:
                endpoint = self.ENDPOINTS['tryon_fashn']
            else:
                endpoint = self.ENDPOINTS['tryon_fashn']

        prompt = kwargs.get('prompt', '')
        negative_prompt = kwargs.get('negative_prompt', '')
        photo_type = kwargs.get('photo_type', 'front')

        if 'nano-banana' in endpoint or 'seedream' in endpoint:
            # ═══ SEEDREAM / NANO-BANANA PATH ═══
            # Image URL'leri hazirla: [Figure 1=garment, Figure 2=model, Figure 3=front_view?, ...]
            image_urls_list = [garment_image_url, model_image_url]

            front_output_url = kwargs.get('front_output_url')
            if front_output_url and photo_type in ('back', 'side'):
                image_urls_list.append(front_output_url)

            detail_urls = kwargs.get('detail_urls') or []
            for du in detail_urls:
                image_urls_list.append(du)

            # Detail figure referanslari prompt'a ekle
            enhanced_prompt = prompt
            if detail_urls:
                detail_start_idx = 4 if front_output_url and photo_type in ('back', 'side') else 3
                for i in range(len(detail_urls)):
                    idx = detail_start_idx + i
                    enhanced_prompt += f" Figure {idx} is a detail texture reference for the garment."
                enhanced_prompt += " Output is full-body photo with Figure 1 garment texture."

            arguments = {
                'prompt': enhanced_prompt,
                'image_urls': image_urls_list,
                'aspect_ratio': '2:3',
                'output_format': 'jpeg',
                'resolution': kwargs.get('resolution', '2k'),
            }

            if 'nano-banana' in endpoint:
                arguments['num_images'] = kwargs.get('num_samples', 1)
                arguments['safety_tolerance'] = '4'
                arguments['limit_generations'] = True
                arguments['enable_watermark'] = False

            # Negatif prompt — garment_analyzer'dan gelir, ek manipulasyon yok
            if negative_prompt:
                arguments['negative_prompt'] = negative_prompt

            if kwargs.get('seed'):
                arguments['seed'] = int(kwargs['seed'])

        else:
            # ═══ FASHN PATH ═══
            fal_category = {
                'tops': 'tops',
                'bottoms': 'bottoms',
                'one_piece': 'one-piece',
                'one-piece': 'one-piece',
                'full-body': 'one-piece',
                'dress': 'one-piece',
                'shoes': 'tops',
                'bags': 'tops',
                'accessories': 'tops',
            }.get(category, 'tops')

            arguments = {
                'model_image': model_image_url,
                'garment_image': garment_image_url,
                'category': fal_category,
                'mode': mode,
                'garment_photo_type': kwargs.get('garment_photo_type', 'flat-lay'),
                'enable_watermark': False,
            }
            if prompt:
                arguments['prompt'] = prompt
            if negative_prompt:
                arguments['negative_prompt'] = negative_prompt

            if kwargs.get('seed'):
                arguments['seed'] = int(kwargs['seed'])

        # ═══ RATE LIMIT RETRY ═══
        import time
        max_retries = 2
        backoff_factor = 4
        result = None
        for attempt in range(max_retries):
            try:
                result = fal_client.subscribe(
                    endpoint,
                    arguments=arguments,
                    client_timeout=180,
                )
                break
            except Exception as e:
                error_str = str(e).lower()
                is_rate_limit = (
                    'rate' in error_str or
                    'limit' in error_str or
                    '429' in error_str or
                    'concurrent' in error_str
                )
                if is_rate_limit and attempt < max_retries - 1:
                    sleep_time = backoff_factor * (2 ** attempt)
                    _logger.warning(
                        "fal.ai Rate Limit asildi. %d saniye beklenip tekrar denenecek (Deneme %d/%d). Hata: %s",
                        sleep_time, attempt + 1, max_retries, e
                    )
                    time.sleep(sleep_time)
                else:
                    raise

        # ═══ SONUÇ PARSE ═══
        image_urls = []
        if isinstance(result, dict):
            if 'images' in result and isinstance(result['images'], list):
                for img in result['images']:
                    if isinstance(img, dict):
                        u = img.get('url', '')
                        if u:
                            image_urls.append(u)
                    elif isinstance(img, str) and img:
                        image_urls.append(img)
            elif 'image' in result and result['image']:
                if isinstance(result['image'], dict):
                    u = result['image'].get('url', '')
                    if u:
                        image_urls.append(u)
                elif isinstance(result['image'], str) and result['image']:
                    image_urls.append(result['image'])

        image_url = image_urls[0] if image_urls else ''
        request_id = result.get('request_id', '') if isinstance(result, dict) else ''

        seed_val = None
        if isinstance(result, dict):
            seed_val = result.get('seed')
        else:
            seed_val = getattr(result, 'seed', None)

        return {
            'image_urls': image_urls,
            'image_url': image_url,
            'cost': self.get_estimated_cost(endpoint) * len(image_urls) if 'nano-banana' in endpoint else self.get_estimated_cost(endpoint),
            'request_id': request_id,
            'seed': seed_val,
        }
    def remove_background(self, image_base64):
        # Arka plan kaldirma - birefnet.
        self._check_client()

        image_url = self.upload_image(image_base64)
        result = fal_client.subscribe(
            self.ENDPOINTS['bg_remove'],
            arguments={'image_url': image_url},
            client_timeout=60,
        )
        output_url = ''
        if isinstance(result, dict):
            img_val = result.get('image')
            if isinstance(img_val, dict):
                output_url = img_val.get('url', '')
            elif isinstance(img_val, str):
                output_url = img_val
        if output_url:
            import requests
            img_data = requests.get(output_url, timeout=60).content
            return base64.b64encode(img_data).decode()
        return image_base64

    def generate_mannequin(self, prompt, **kwargs):
        # AI ile manken fotografi olustur - FLUX schnell.
        self._check_client()

        width = kwargs.get('width', 864)
        height = kwargs.get('height', 1296)

        result = fal_client.subscribe(
            self.ENDPOINTS['flux_schnell'],
            arguments={
                'prompt': prompt,
                'image_size': {'width': width, 'height': height},
                'num_images': 1,
                'enable_watermark': False,
            },
            client_timeout=120,
        )

        image_url = ''
        if isinstance(result, dict):
            imgs = result.get('images', [])
            if imgs and isinstance(imgs, list):
                first = imgs[0]
                if isinstance(first, dict):
                    image_url = first.get('url', '')
                elif isinstance(first, str):
                    image_url = first
        if image_url:
            import requests
            img_data = requests.get(image_url, timeout=60).content
            return base64.b64encode(img_data).decode()
        return None

    def upload_image(self, image_base64, content_type='image/jpeg'):
        # Gorseli fal CDN'e yukle - otomatik retry ve fallback ile.
        self._check_client()
        if isinstance(image_base64, bytes):
            image_base64 = image_base64.decode('ascii')
        if image_base64.startswith('data:'):
            image_base64 = image_base64.split(';base64,', 1)[1]
        raw_bytes = base64.b64decode(image_base64)
        
        # ═══ WEBP OPTİMİZASYONU ═══
        # Kalite kaybı olmadan dosya boyutunu %80-90 oranında küçülterek
        # Fal CDN yükleme ve GPU indirme/işleme süresini dramatik şekilde hızlandırır.
        try:
            from PIL import Image as _PILImage
            import io as _io
            _img = _PILImage.open(_io.BytesIO(raw_bytes))
            _fmt = (_img.format or '').upper()
            w, h = _img.size
            if _fmt != 'WEBP' or max(w, h) > 1600 or len(raw_bytes) > 1024 * 1024:
                if _img.mode in ('RGBA', 'LA', 'P'):
                    if _img.mode == 'P':
                        _img = _img.convert('RGBA')
                elif _img.mode != 'RGB':
                    _img = _img.convert('RGB')
                if max(w, h) > 1600:
                    _img.thumbnail((1600, 1600), _PILImage.LANCZOS)
                _out = _io.BytesIO()
                # Önce WebP dene, yoksa JPEG'e düş
                try:
                    _img.save(_out, format='WEBP', quality=92, method=4)
                    raw_bytes = _out.getvalue()
                    content_type = 'image/webp'
                    _logger.info('fal CDN yükleme öncesi WebP formatına optimize edildi: %d KB (%dx%d)', len(raw_bytes) // 1024, _img.width, _img.height)
                except (KeyError, OSError):
                    _logger.warning('Pillow WebP destegi yok, JPEG fallback ile optimize ediliyor')
                    _out = _io.BytesIO()
                    _rgb = _img.convert('RGB') if _img.mode != 'RGB' else _img
                    _rgb.save(_out, format='JPEG', quality=92, optimize=True)
                    raw_bytes = _out.getvalue()
                    content_type = 'image/jpeg'
                    _logger.info('fal CDN yükleme öncesi JPEG formatına optimize edildi: %d KB (%dx%d)', len(raw_bytes) // 1024, _img.width, _img.height)
            elif _fmt == 'WEBP':
                content_type = 'image/webp'
        except Exception as _re:
            _logger.warning('Görsel optimizasyonu başarısız, orijinal gönderilecek: %s', _re)
        
        # 1. fal_client.upload (HTTP REST - primary)
        file_name = 'image.webp' if content_type == 'image/webp' else 'image.jpg'
        for attempt in range(3):
            try:
                return fal_client.upload(raw_bytes, content_type, file_name=file_name)
            except Exception as e:
                _logger.warning('fal CDN yükleme denemesi %d/3 başarısız: %s', attempt + 1, e)
                if attempt < 2:
                    time.sleep(2 ** attempt)
        
        # 2. REST API doğrudan deneme (fallback)
        try:
            import requests as _req
            resp = _req.post(
                'https://rest.alpha.fal.ai/storage/upload/initiate',
                headers={'Authorization': f'Key {self.api_key}'},
                json={'content_type': content_type, 'file_name': file_name},
                timeout=15,
            )
            if resp.status_code in (200, 201):
                init_data = resp.json()
                upload_url = init_data.get('upload_url')
                file_url = init_data.get('file_url')
                if upload_url and file_url:
                    put_resp = _req.put(upload_url, data=raw_bytes, headers={'Content-Type': content_type}, timeout=30)
                    if put_resp.status_code in (200, 201):
                        return file_url
        except Exception as e2:
            _logger.warning('fal REST doğrudan yükleme de başarısız: %s', e2)
        
        # 3. Son çare: base64 data URI dönder
        _logger.warning('fal CDN yükleme tamamen başarısız, data URI fallback')
        return f'data:{content_type};base64,{image_base64}'

    def kontext_edit(self, image_base64, prompt, **kwargs):
        """FLUX Kontext ile hedefli gorsel duzenleme.

        Mask gerektirmez — metin komutuyla hedefli duzenleme yapar.
        Ornek: 'Remove belt loops from the waistband, make it smooth and clean'
        """
        self._check_client()
        image_url = self.upload_image(image_base64)

        import time
        max_retries = 2
        for attempt in range(max_retries):
            try:
                result = fal_client.subscribe(
                    self.ENDPOINTS['flux_kontext'],
                    arguments={
                        'prompt': prompt,
                        'image_url': image_url,
                        'num_images': 1,
                    },
                    client_timeout=120,
                )
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(3)
                else:
                    raise

        output_url = ''
        if isinstance(result, dict):
            if 'images' in result and isinstance(result['images'], list) and result['images']:
                first = result['images'][0]
                if isinstance(first, dict):
                    output_url = first.get('url', '')
                elif isinstance(first, str):
                    output_url = first
            elif 'image' in result and result['image']:
                first = result['image']
                if isinstance(first, dict):
                    output_url = first.get('url', '')
                elif isinstance(first, str):
                    output_url = first

        if output_url:
            import requests as req_lib
            img_data = req_lib.get(output_url, timeout=60).content
            return base64.b64encode(img_data).decode()
        return None

    def inpaint_edit(self, prompt, image_urls, **kwargs):
        """Seedream v5 Pro Edit — Region-precise inpainting/editing."""
        self._check_client()
        arguments = {
            'prompt': prompt,
            'image_urls': image_urls,
            'aspect_ratio': kwargs.get('aspect_ratio', '2:3'),
            'output_format': 'png',
            'resolution': kwargs.get('resolution', '2k'),
        }
        if 'seed' in kwargs and kwargs['seed']:
            arguments['seed'] = int(kwargs['seed'])

        import time
        max_retries = 3
        result = None
        for attempt in range(max_retries):
            try:
                result = fal_client.subscribe(
                    self.ENDPOINTS['seedream'],
                    arguments=arguments,
                    client_timeout=300,
                )
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(3)
                else:
                    raise

        output_url = ''
        if isinstance(result, dict):
            if 'images' in result and isinstance(result['images'], list) and result['images']:
                first = result['images'][0]
                if isinstance(first, dict):
                    output_url = first.get('url', '')
                elif isinstance(first, str):
                    output_url = first
            elif 'image' in result and result['image']:
                first = result['image']
                if isinstance(first, dict):
                    output_url = first.get('url', '')
                elif isinstance(first, str):
                    output_url = first

        if output_url:
            import requests as req_lib
            img_data = req_lib.get(output_url, timeout=60).content
            return base64.b64encode(img_data).decode()
        return None
