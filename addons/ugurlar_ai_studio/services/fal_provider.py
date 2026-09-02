# fal.ai provider implementation.
#
# fal_client SDK kullanir - kuyruk destekli, otomatik retry,
# timeout yonetimi ve yapisal hata ayristirma entegrasyonu ile.

import base64
import logging

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

    def __init__(self, api_key):
        import os
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
        # Manken uzerine giydirme.
        self._check_client()

        # default endpoint mapping based on model_name
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
                endpoint = self.ENDPOINTS['tryon_fashn']  # Default to FASHN v1.6 for best quality

        prompt = kwargs.get('prompt', '')

        if 'nano-banana' in endpoint or 'seedream' in endpoint:
            # nano-banana-2/edit formatı
            # View-spesifik prompt bilgisini ekle
            photo_type = kwargs.get('photo_type', 'front')
            front_output_url = kwargs.get('front_output_url')
            detail_urls = kwargs.get('detail_urls') or []
            
            image_urls_list = [garment_image_url, model_image_url]
            if front_output_url and photo_type in ('back', 'side'):
                image_urls_list.append(front_output_url)
                
            for du in detail_urls:
                image_urls_list.append(du)
                
            enhanced_prompt = prompt
            
            # ═══ GARMENT FIDELITY (OLUMLU ÇERÇEVELEME) ═══
            if 'seedream' in endpoint:
                # Seedream uses Figure references
                garment_fidelity = (
                    "Dress the model in Figure 2 with the exact garment shown in Figure 1. "
                    "IMPORTANT: Ignore any security tags, alarm tags, price tags, hangers, or store fixtures "
                    "visible on Figure 1 — these are store artifacts, NOT part of the garment. "
                    "The output garment must be completely clean and tag-free. "
                    "Reproduce every visible garment detail of Figure 1 precisely: same waistband, "
                    "same seams, same pockets, same hardware, same fabric texture. "
                    "The output garment must be a pixel-perfect match of Figure 1 (minus any store tags). "
                )
            else:
                garment_fidelity = (
                    "GARMENT FIDELITY: The 1st reference image is the EXACT garment. "
                    "Reproduce every visible detail precisely: same waistband construction, "
                    "same seams, same pockets, same hardware. "
                    "The output garment must be a pixel-perfect match of the 1st reference. "
                )

            # Base View Hints
            if 'seedream' in endpoint:
                view_hints = {
                    'back': 'Show the BACK view of the model from Figure 2, facing away from camera, wearing the garment from Figure 1. Copy EVERY detail from Figure 1 exactly — same waistband, same pockets, same surface. ',
                    'side': (
                        'Show the SIDE view of the model from Figure 2, turned 45 degrees. '
                        'The garment is from Figure 1 — Figure 1 is the ONLY source of truth for the garment. '
                        'Copy EVERY structural detail from Figure 1: same waistband construction, same surface texture, same pockets. '
                        'The waistband must match Figure 1 exactly — if Figure 1 shows a smooth waistband, the side view must also have a smooth waistband. '
                    ),
                    'detail': 'Close-up detail shot of the garment from Figure 1 on the model. ',
                }
            else:
                view_hints = {
                    'back': 'IMPORTANT: Show the BACK view of the model, facing away from camera. ',
                    'side': 'IMPORTANT: Show the SIDE view of the model, turned 45 degrees. ',
                    'detail': 'IMPORTANT: Close-up detail shot showing fabric texture and details. ',
                }
            base_hint = view_hints.get(photo_type, '') if photo_type and photo_type != 'front' else ''
            dynamic_prompt = garment_fidelity + base_hint
            
            detail_start_idx = 3
            if front_output_url and photo_type in ('back', 'side'):
                if 'seedream' in endpoint:
                    dynamic_prompt += "Figure 3 is the FRONT generated view of this model. Use Figure 3 as the source of truth for model identity, hairstyle, skin, and all outfit parts. Keep the same model and outfit, only rotate the camera to show the view and apply the garment from Figure 1. "
                else:
                    dynamic_prompt += "The THIRD reference image is the FRONT generated view of this model; use the THIRD image as the source of truth for the model identity, hairstyle, skin, and all other outfit parts (top, bottom, shoes). Keep the same model and outfit, only rotate the camera to show the view and apply the garment. "
                detail_start_idx = 4
                
            if detail_urls:
                for i in range(len(detail_urls)):
                    idx = detail_start_idx + i
                    
                    # Sayı sonlarına uygun ek getirme (1st, 2nd, 3rd, 4th, vb.)
                    suffix = "th"
                    if idx % 10 == 1 and idx % 100 != 11:
                        suffix = "st"
                    elif idx % 10 == 2 and idx % 100 != 12:
                        suffix = "nd"
                    elif idx % 10 == 3 and idx % 100 != 13:
                        suffix = "rd"
                        
                    if 'seedream' in endpoint:
                        dynamic_prompt += f"Figure {idx} is a MACRO DETAIL shot of the garment showing fabric texture and patterns. Apply this exact texture and detail precisely. "
                    else:
                        dynamic_prompt += f"The {idx}{suffix} reference image is a MACRO DETAIL shot of the garment showing fabric texture and specific patterns. Apply this exact texture and detail to the garment precisely. Copy the exact pattern, texture, and construction details from this reference. "
                
                # Detail shot oldugunda full body ciktisi icin yonlendirme
                if 'seedream' in endpoint:
                    dynamic_prompt += (
                        "The final output is a FULL BODY photograph of the model wearing the garment from Figure 1. "
                        "Detail figures are for texture reference only. "
                    )
                else:
                    dynamic_prompt += (
                        "The final output is a FULL BODY photograph of the model wearing the garment. "
                        "The detail images are for texture reference only. "
                        "The garment in the output is a pixel-perfect match of the 1st reference image. "
                        "Match every pattern, texture, and construction detail exactly as shown. "
                    )
                    
            if dynamic_prompt:
                enhanced_prompt = dynamic_prompt + "\n" + enhanced_prompt

            arguments = {
                'prompt': enhanced_prompt,
                'image_urls': image_urls_list,
                'aspect_ratio': '2:3',
                'output_format': 'png',
                'resolution': kwargs.get('resolution', '2k'),
            }
            if 'nano-banana' in endpoint:
                arguments['num_images'] = kwargs.get('num_samples', 1)
                arguments['safety_tolerance'] = '4'
                arguments['limit_generations'] = True
                arguments['enable_watermark'] = False
            if 'negative_prompt' in kwargs and kwargs['negative_prompt']:
                arguments['negative_prompt'] = kwargs['negative_prompt']
            if 'seed' in kwargs and kwargs['seed']:
                arguments['seed'] = int(kwargs['seed'])
        else:
            # FASHN v1.6 veya Kolors formatı
            fal_category = {
                'tops': 'tops',
                'bottoms': 'bottoms',
                'one_piece': 'one-piece',
                'one-piece': 'one-piece',
                'full-body': 'one-piece',
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
            if 'negative_prompt' in kwargs and kwargs['negative_prompt']:
                arguments['negative_prompt'] = kwargs['negative_prompt']
            if 'seed' in kwargs and kwargs['seed']:
                arguments['seed'] = int(kwargs['seed'])

        # Rate Limit / Concurrency Limit Retry Mekanizması
        import time
        max_retries = 3
        backoff_factor = 4
        result = None
        for attempt in range(max_retries):
            try:
                result = fal_client.subscribe(
                    endpoint,
                    arguments=arguments,
                    client_timeout=300,
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

        image_urls = []
        if 'images' in result and result['images']:
            image_urls = [img.get('url', '') for img in result['images']]
        elif 'image' in result and result['image']:
            image_urls = [result['image'].get('url', '')]

        image_url = image_urls[0] if image_urls else ''
        request_id = result.get('request_id', '')
        
        # fal.ai base response'dan veya result dict'ten seed oku
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
        output_url = result.get('image', {}).get('url', '')
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

        image_url = result.get('images', [{}])[0].get('url', '')
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
        image_bytes = base64.b64decode(image_base64)
        return fal_client.upload(image_bytes, content_type)

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
        if 'images' in result and result['images']:
            output_url = result['images'][0].get('url', '')
        elif 'image' in result and result['image']:
            output_url = result['image'].get('url', '')

        if output_url:
            import requests as req_lib
            img_data = req_lib.get(output_url, timeout=60).content
            return base64.b64encode(img_data).decode()
        return None
