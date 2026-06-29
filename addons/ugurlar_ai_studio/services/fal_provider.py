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
        'any_llm': 'fal-ai/any-llm',
    }

    # Endpoint basina tahmini maliyet (USD)
    ESTIMATED_COSTS = {
        'fal-ai/fashn/tryon/v1.6': 0.075,
        'fal-ai/birefnet': 0.002,
        'fal-ai/flux/schnell': 0.003,
        'fal-ai/flux-pro/v1.1': 0.05,
        'fal-ai/nano-banana-2/edit': 0.04,
        'fal-ai/any-llm': 0.001,
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
            if 'max' in model_name:
                endpoint = 'fal-ai/fashn/tryon-max'
            elif 'v1.6' in model_name or 'v1-6' in model_name:
                endpoint = self.ENDPOINTS['tryon_fashn']
            else:
                endpoint = self.ENDPOINTS['tryon_fashn']  # Default to FASHN v1.6 for best quality

        prompt = kwargs.get('prompt', '')

        if 'nano-banana' in endpoint:
            # nano-banana-2/edit formatı
            # View-spesifik prompt bilgisini ekle
            photo_type = kwargs.get('photo_type', 'front')
            enhanced_prompt = prompt
            if photo_type and photo_type != 'front' and prompt:
                view_hints = {
                    'back': 'IMPORTANT: Show the BACK view of the model, facing away from camera. ',
                    'side': 'IMPORTANT: Show the SIDE view of the model, turned 45 degrees. ',
                    'detail': 'IMPORTANT: Close-up detail shot showing fabric texture and details. ',
                }
                enhanced_prompt = view_hints.get(photo_type, '') + prompt

            arguments = {
                'prompt': enhanced_prompt,
                'image_urls': [garment_image_url, model_image_url],
                'num_images': kwargs.get('num_samples', 1),
                'aspect_ratio': '3:4',
                'output_format': 'png',
                'safety_tolerance': '4',
                'resolution': kwargs.get('resolution', '2K'),
                'limit_generations': True,
            }
        else:
            # FASHN v1.6 veya Kolors formatı
            fal_category = {
                'tops': 'tops',
                'bottoms': 'bottoms',
                'one_piece': 'one-piece',
                'one-piece': 'one-piece',
                'shoes': 'tops',
                'bags': 'tops',
                'accessories': 'tops',
            }.get(category, 'tops')

            arguments = {
                'human_image_url': model_image_url,
                'garment_image_url': garment_image_url,
                'category': fal_category,
                'mode': mode,
                'garment_photo_type': kwargs.get('garment_photo_type', 'flat-lay'),
            }
            if prompt:
                arguments['prompt'] = prompt
            if 'seed' in kwargs and kwargs['seed']:
                arguments['seed'] = int(kwargs['seed'])

        result = fal_client.subscribe(
            endpoint,
            arguments=arguments,
            client_timeout=300,
        )

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
