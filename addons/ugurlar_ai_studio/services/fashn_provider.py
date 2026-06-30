# FASHN direkt API provider implementation.
#
# FASHN Python SDK (pip install fashn) kullanir.
# api.fashn.ai uzerinden dogrudan calisan provider.
#
# Desteklenen modeller:
#   - tryon-v1.6   : Virtual try-on (giydirme)
#   - tryon-max     : Premium try-on (yuksek kalite)
#   - background-remove : Arka plan kaldirma
#   - model-create  : AI manken olusturma

import base64
import logging
import time

from .ai_provider_base import AIProviderBase

_logger = logging.getLogger(__name__)

try:
    from fashn import Fashn
    import fashn as fashn_module
except ImportError:
    Fashn = None
    fashn_module = None
    _logger.warning(
        'fashn SDK kurulu degil. FASHN provider calismayacak. '
        'Kurulum: pip install fashn'
    )


def _to_data_uri(image_base64, content_type='image/jpeg'):
    """Base64 string'i FASHN'in kabul ettigi data URI formatina cevirir.

    FASHN API base64 girislerinde data URI prefix'i gerektirir:
    data:image/jpeg;base64,/9j/4AAQ...

    Args:
        image_base64: str veya bytes — raw base64 encoded gorsel
        content_type: str — MIME tipi

    Returns:
        str — data URI formatinda base64
    """
    if isinstance(image_base64, bytes):
        image_base64 = image_base64.decode('ascii')

    # Zaten data URI ise dokunma
    if image_base64.startswith('data:'):
        return image_base64

    return f'data:{content_type};base64,{image_base64}'


class FashnProvider(AIProviderBase):
    """FASHN direkt API provider.

    FASHN Python SDK ile tum API cagirilari yapilir.
    subscribe() metodu otomatik polling yapar — callback gerekmez.

    Desteklenen try-on modelleri:
    - tryon-v1.6: Hizli, uygun maliyetli (1 kredi)
    - tryon-max: Premium kalite (2-5 kredi, cozunurluge bagli)
    """

    # Model basina tahmini maliyet (USD / kredi)
    ESTIMATED_COSTS = {
        'tryon-v1.6': 0.05,
        'tryon-max': 0.15,
        'background-remove': 0.01,
        'model-create': 0.05,
    }

    def __init__(self, api_key):
        if Fashn is None:
            raise ImportError(
                'fashn SDK kurulu degil. '
                'Kurulum: pip install fashn'
            )
        self.client = Fashn(api_key=api_key)
        self.api_key = api_key

    def get_estimated_cost(self, model_name):
        """Model icin tahmini maliyeti dondur."""
        return self.ESTIMATED_COSTS.get(model_name, 0.05)

    def virtual_tryon(self, model_image_url, garment_image_url,
                      category='tops', mode='balanced', **kwargs):
        """Manken uzerine giydirme — FASHN tryon-v1.6 veya tryon-max.

        Args:
            model_image_url: str — manken gorseli (URL veya data URI)
            garment_image_url: str — urun gorseli (URL veya data URI)
            category: str — tops/bottoms/one-pieces/auto
            mode: str — performance/balanced/quality
            **kwargs:
                model_name: str — 'tryon-v1.6' veya 'tryon-max'
                num_samples: int — uretim sayisi (1-4)
                garment_photo_type: str — auto/flat-lay/model
                output_format: str — png/jpeg

        Returns:
            dict: {
                'image_urls': list[str],
                'image_url': str (ilk sonuc),
                'cost': float,
                'request_id': str,
                'credits_used': float,
            }
        """
        model_name = kwargs.get('model_name', 'tryon-v1.6')
        num_samples = kwargs.get('num_samples', 1)
        output_format = kwargs.get('output_format', 'jpeg')

        # v1.6 vs max icin farkli input yapisi
        if model_name == 'tryon-max':
            resolution = kwargs.get('resolution', '2K')
            inputs = {
                'model_image': model_image_url,
                'product_image': garment_image_url,  # tryon-max: product_image!
                'num_images': num_samples,
                'output_format': output_format,
                'resolution': resolution,
            }
            # generation_mode: quality modunda en iyi baskı/logo koruma sağlanır
            if mode == 'quality':
                inputs['generation_mode'] = 'quality'
            elif mode == 'performance':
                inputs['generation_mode'] = 'fast'
            else:
                inputs['generation_mode'] = 'balanced'
        else:
            # tryon-v1.6
            inputs = {
                'model_image': model_image_url,
                'garment_image': garment_image_url,
                'category': category,
                'mode': mode,
                'garment_photo_type': kwargs.get('garment_photo_type', 'auto'),
                'num_samples': num_samples,
                'output_format': output_format,
            }

        # Prompt ve Seed parametreleri ekleme
        prompt = kwargs.get('prompt', '')
        if prompt:
            inputs['prompt'] = prompt
            
        negative_prompt = kwargs.get('negative_prompt', '')
        if negative_prompt:
            inputs['negative_prompt'] = negative_prompt
            
        if 'seed' in kwargs and kwargs['seed']:
            inputs['seed'] = int(kwargs['seed'])

        _logger.info(
            'FASHN %s cagriliyor: category=%s, mode=%s, samples=%d',
            model_name, category, mode, num_samples,
        )

        start_time = time.time()
        try:
            result = self.client.predictions.subscribe(
                model_name=model_name,
                inputs=inputs,
            )
        except Exception as e:
            _logger.error('FASHN API hatasi: %s', e)
            raise

        elapsed = time.time() - start_time

        # Sonuclari parse et
        image_urls = []
        if result.status == 'completed' and result.output:
            if isinstance(result.output, list):
                image_urls = result.output
            elif isinstance(result.output, str):
                image_urls = [result.output]

        credits_used = getattr(result, 'credits_used', None) or 0
        cost = credits_used * 0.05 if credits_used else self.get_estimated_cost(model_name) * num_samples
        seed_val = getattr(result, 'seed', None) or (result.output.get('seed') if isinstance(result.output, dict) else None)

        _logger.info(
            'FASHN %s tamamlandi: %d gorsel, %.1f sn, %.3f kredi',
            model_name, len(image_urls), elapsed, credits_used,
        )

        return {
            'image_urls': image_urls,
            'image_url': image_urls[0] if image_urls else '',
            'cost': cost,
            'request_id': getattr(result, 'id', ''),
            'credits_used': credits_used,
            'seed': seed_val,
        }

    def remove_background(self, image_base64):
        """Arka plan kaldirma — FASHN background-remove.

        Args:
            image_base64: str — base64 encoded gorsel

        Returns:
            str — base64 encoded sonuc (arka plansiz)
        """
        data_uri = _to_data_uri(image_base64)

        try:
            result = self.client.predictions.subscribe(
                model_name='background-remove',
                inputs={
                    'image': data_uri,
                    'return_base64': True,
                },
            )

            if result.status == 'completed' and result.output:
                output = result.output
                if isinstance(output, list):
                    output = output[0]
                # data:image/png;base64,... formatindan raw base64'e cevir
                if isinstance(output, str) and ';base64,' in output:
                    return output.split(';base64,', 1)[1]
                return output

        except Exception as e:
            _logger.error('FASHN background-remove hatasi: %s', e)

        return image_base64

    def generate_mannequin(self, prompt, **kwargs):
        """AI ile manken fotografi olustur — FASHN model-create.

        Args:
            prompt: str — manken aciklamasi
            **kwargs:
                aspect_ratio: str — '2:3', '3:4', vb.
                num_images: int — uretim sayisi

        Returns:
            str — base64 encoded manken gorseli veya None
        """
        aspect_ratio = kwargs.get('aspect_ratio', '2:3')

        try:
            result = self.client.predictions.subscribe(
                model_name='model-create',
                inputs={
                    'prompt': prompt,
                    'aspect_ratio': aspect_ratio,
                    'output_format': 'jpeg',
                },
            )

            if result.status == 'completed' and result.output:
                output = result.output
                if isinstance(output, list):
                    output = output[0]

                # URL ise indir
                if isinstance(output, str) and output.startswith('http'):
                    import requests
                    img_data = requests.get(output, timeout=60).content
                    return base64.b64encode(img_data).decode()

                # data URI ise decode et
                if isinstance(output, str) and ';base64,' in output:
                    return output.split(';base64,', 1)[1]

                return output

        except Exception as e:
            _logger.error('FASHN model-create hatasi: %s', e)

        return None

    def upload_image(self, image_base64, content_type='image/jpeg'):
        """Gorseli data URI formatina cevir.

        FASHN API base64 data URI'yi direkt kabul eder,
        ayri bir upload adimi gerekmez.

        Args:
            image_base64: str — base64 encoded gorsel
            content_type: str — MIME tipi

        Returns:
            str — data URI
        """
        return _to_data_uri(image_base64, content_type)
