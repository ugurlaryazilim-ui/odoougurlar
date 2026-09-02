# -*- coding: utf-8 -*-
"""Vision analyzer service to prepare image data for Gemini."""
import base64
import logging

_logger = logging.getLogger(__name__)

class VisionAnalyzer:
    def extract_image_base64(self, product_template, image_field='image_1024'):
        """
        Extracts image data from a product record as a raw base64 string.
        
        Odoo stores image fields as base64-encoded strings already.
        We must NOT double-encode them.
        """
        try:
            image_data = getattr(product_template, image_field, None)
            if not image_data:
                # Fallback to smaller image
                if image_field != 'image_128':
                    for fallback in ['image_512', 'image_256', 'image_128']:
                        image_data = getattr(product_template, fallback, None)
                        if image_data:
                            _logger.info("Fallback image field: %s", fallback)
                            break
                if not image_data:
                    return None

            # Odoo image fields are already base64-encoded strings
            if isinstance(image_data, str):
                # Strip any data URI prefix if present
                if ',' in image_data and image_data.startswith('data:'):
                    image_data = image_data.split(',', 1)[1]
                return image_data
            elif isinstance(image_data, bytes):
                # bytes -> decode to str (it's already base64 bytes in Odoo)
                return image_data.decode('utf-8')
            else:
                _logger.warning("Unexpected image data type: %s", type(image_data))
                return None
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
