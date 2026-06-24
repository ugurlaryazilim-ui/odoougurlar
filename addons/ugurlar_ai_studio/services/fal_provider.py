"""fal.ai provider implementation."""
import base64
import logging

from .ai_provider_base import AIProviderBase

_logger = logging.getLogger(__name__)

try:
    import fal_client
except ImportError:
    fal_client = None
    _logger.warning(
        'fal-client kurulu değil. AI özellikleri çalışmayacak. '
        'Kurulum: pip install fal-client'
    )


class FalProvider(AIProviderBase):
    """fal.ai FASHN v1.6 implementasyonu."""

    ENDPOINTS = {
        'tryon_fashn': 'fal-ai/fashn/tryon/v1.6',
        'tryon_kolors': 'fal-ai/kling/v1-5/kolors-virtual-try-on',
        'bg_remove': 'fal-ai/birefnet',
        'flux_schnell': 'fal-ai/flux/schnell',
    }

    def __init__(self, api_key):
        import os
        os.environ['FAL_KEY'] = api_key
        self.api_key = api_key

    def _check_client(self):
        if fal_client is None:
            raise ImportError(
                'fal-client paketi kurulu değil. '
                'Kurulum: pip install fal-client'
            )

    def virtual_tryon(self, model_image_url, garment_image_url,
                      category='tops', mode='balanced', **kwargs):
        self._check_client()

        endpoint = kwargs.get('endpoint', self.ENDPOINTS['tryon_fashn'])
        fal_category = {
            'tops': 'tops',
            'bottoms': 'bottoms',
            'one_piece': 'one-piece',
            'shoes': 'tops',
            'bags': 'tops',
            'accessories': 'tops',
        }.get(category, 'tops')

        result = fal_client.subscribe(
            endpoint,
            arguments={
                'model_image': model_image_url,
                'garment_image': garment_image_url,
                'category': fal_category,
                'mode': mode,
                'garment_photo_type': kwargs.get('garment_photo_type', 'flat-lay'),
            },
        )

        image_url = ''
        if 'images' in result and result['images']:
            image_url = result['images'][0].get('url', '')
        elif 'image' in result and result['image']:
            image_url = result['image'].get('url', '')
        request_id = result.get('request_id', '')

        return {
            'image_url': image_url,
            'cost': 0.075,
            'request_id': request_id,
        }

    def remove_background(self, image_base64):
        self._check_client()

        image_url = self.upload_image(image_base64)
        result = fal_client.subscribe(
            self.ENDPOINTS['bg_remove'],
            arguments={'image_url': image_url},
        )
        output_url = result.get('image', {}).get('url', '')
        if output_url:
            import requests
            img_data = requests.get(output_url, timeout=60).content
            return base64.b64encode(img_data).decode()
        return image_base64

    def generate_mannequin(self, prompt, **kwargs):
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
        )

        image_url = result.get('images', [{}])[0].get('url', '')
        if image_url:
            import requests
            img_data = requests.get(image_url, timeout=60).content
            return base64.b64encode(img_data).decode()
        return None

    def upload_image(self, image_base64, content_type='image/jpeg'):
        self._check_client()
        image_bytes = base64.b64decode(image_base64)
        return fal_client.upload(image_bytes, content_type)
