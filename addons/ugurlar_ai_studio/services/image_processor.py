"""Görsel işleme yardımcı fonksiyonları."""
import base64
import logging

_logger = logging.getLogger(__name__)


def check_image_quality(image_base64):
    """Görsel kalitesini kontrol et.

    Returns:
        dict: {
            'score': float (0-100),
            'warnings': list of str,
            'is_acceptable': bool,
        }
    """
    warnings = []
    score = 100.0

    try:
        image_bytes = base64.b64decode(image_base64)
        size_kb = len(image_bytes) / 1024

        # Boyut kontrolü
        if size_kb < 50:
            warnings.append('Dosya çok küçük — düşük çözünürlük olabilir')
            score -= 30
        elif size_kb > 10240:
            warnings.append('Dosya çok büyük (>10MB) — otomatik boyutlandırılacak')
            score -= 5

        # Temel format kontrolü
        if image_bytes[:2] == b'\xff\xd8':
            pass  # JPEG OK
        elif image_bytes[:4] == b'\x89PNG':
            pass  # PNG OK
        elif image_bytes[:4] == b'RIFF':
            pass  # WebP OK
        else:
            warnings.append('Desteklenmeyen görsel formatı')
            score -= 20

    except Exception as e:
        _logger.warning('Kalite kontrol hatası: %s', e)
        warnings.append('Kalite kontrolü yapılamadı')
        score = 50.0

    return {
        'score': max(0, min(100, score)),
        'warnings': warnings,
        'is_acceptable': score >= 50,
    }


def resize_image_if_needed(image_base64, max_width=1920, max_height=1920):
    """Gerekirse görseli boyutlandır. Odoo tools kullanır."""
    try:
        from odoo.tools.image import image_process
        return image_process(
            image_base64,
            size=(max_width, max_height),
            quality=85,
        )
    except Exception as e:
        _logger.warning('Resize hatası: %s', e)
        return image_base64
