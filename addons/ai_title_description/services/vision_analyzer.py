# -*- coding: utf-8 -*-
"""Vision analyzer service to prepare image data for Gemini."""
import base64
import logging

_logger = logging.getLogger(__name__)

class VisionAnalyzer:
    def extract_image_base64(self, product_template, image_field='image_1024'):
        """
        Extracts image data from a product record as a base64 string.
        """
        try:
            image_data = getattr(product_template, image_field)
            if not image_data:
                return None
                
            if isinstance(image_data, bytes):
                return base64.b64encode(image_data).decode('utf-8')
            return image_data.decode('utf-8') if hasattr(image_data, 'decode') else image_data
        except Exception as e:
            _logger.warning("Failed to extract image base64: %s", str(e))
            return None

    def build_vision_prompt_addition(self):
        """
        Returns the additional prompt for multimodal vision analysis.
        """
        return (
            "Eklenen ürün görselini analiz et. Görselden çıkarabileceğin detayları "
            "(yaka tipi, kol tipi, desen, kumaş görünümü, kalıp, renk tonu) içeriğe yansıt. "
            "Görselde görünmeyen özellikleri UYDURMA."
        )
