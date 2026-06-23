"""Abstract base class for AI providers (provider-agnostic mimari)."""
import logging
from abc import ABC, abstractmethod

_logger = logging.getLogger(__name__)


class AIProviderBase(ABC):
    """Tüm AI provider'ların uyması gereken arayüz.

    Provider-agnostic mimari sayesinde fal.ai, Replicate veya
    özel bir endpoint kolayca eklenebilir.
    """

    @abstractmethod
    def virtual_tryon(self, model_image_url, garment_image_url,
                      category='tops', mode='balanced', **kwargs):
        """Manken üzerine giydirme.

        Returns:
            dict: {'image_url': str, 'cost': float, 'request_id': str}
        """

    @abstractmethod
    def remove_background(self, image_base64):
        """Arka plan kaldırma.

        Returns:
            str: base64 encoded processed image
        """

    @abstractmethod
    def generate_mannequin(self, prompt, **kwargs):
        """AI ile manken fotoğrafı oluştur.

        Returns:
            str: base64 encoded mannequin image
        """

    @abstractmethod
    def upload_image(self, image_base64, content_type='image/jpeg'):
        """Görseli geçici URL'ye yükle.

        Returns:
            str: Public URL
        """
