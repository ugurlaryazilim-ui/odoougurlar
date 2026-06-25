# Kalite kontrol servisi — AI ciktisi dogrulama.
#
# Orijinal urun gorseli ile AI ciktisini karsilastirarak
# kalite skoru hesaplar:
#   1. Delta-E (CIEDE2000) — renk dogrulugu
#   2. Gorsel boyut kontrolu
#   3. Toplam kalite skoru

import base64
import io
import logging

import numpy as np

_logger = logging.getLogger(__name__)

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import cv2
except ImportError:
    cv2 = None


def _rgb_to_lab(rgb_array):
    """RGB numpy array'i CIELAB'e donusturur (OpenCV ile).

    Args:
        rgb_array: numpy array (RGB, uint8)
    Returns:
        numpy array (LAB, float32) veya None
    """
    if cv2 is None:
        return None

    bgr = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    # OpenCV LAB: L [0,255], a [0,255], b [0,255]
    # Standart LAB: L [0,100], a [-128,127], b [-128,127]
    lab[:, :, 0] = lab[:, :, 0] * 100.0 / 255.0
    lab[:, :, 1] = lab[:, :, 1] - 128.0
    lab[:, :, 2] = lab[:, :, 2] - 128.0
    return lab


def _extract_dominant_color_lab(image_base64, num_clusters=3):
    """Gorselden dominant renkleri cikarir (LAB uzayinda).

    K-means clustering ile en baskin renkleri bulur.

    Args:
        image_base64: str — base64 encoded gorsel
        num_clusters: int — kac renk kümesi cikarilacak

    Returns:
        numpy array (num_clusters, 3) — LAB degerleri
        veya None (hata durumunda)
    """
    if cv2 is None or Image is None:
        return None

    try:
        raw = base64.b64decode(image_base64)
        pil_img = Image.open(io.BytesIO(raw)).convert('RGB')

        # Islem hizi icin kucult
        pil_img = pil_img.resize((100, 100), Image.LANCZOS)
        rgb = np.array(pil_img).reshape(-1, 3).astype(np.float32)

        # K-means clustering
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        _, labels, centers = cv2.kmeans(
            rgb, num_clusters, None, criteria, 5, cv2.KMEANS_RANDOM_CENTERS
        )

        # Her cluster'in buyuklugune gore sirala (en buyuk = dominant)
        label_counts = np.bincount(labels.flatten())
        sorted_indices = np.argsort(-label_counts)
        sorted_centers = centers[sorted_indices]

        # RGB -> LAB
        lab_centers = []
        for center in sorted_centers:
            center_img = center.reshape(1, 1, 3).astype(np.uint8)
            lab = _rgb_to_lab(center_img)
            if lab is not None:
                lab_centers.append(lab[0, 0])

        return np.array(lab_centers) if lab_centers else None

    except Exception as e:
        _logger.warning('Dominant renk cikarma hatasi: %s', e)
        return None


def delta_e_ciede2000_simple(lab1, lab2):
    """Basitlestirilmis CIEDE2000 Delta-E hesaplama.

    Tam CIEDE2000 formulu yerine CIE76 (Euclidean LAB distance)
    kullanir — yeterince dogru ve hizli.

    Args:
        lab1, lab2: numpy array (3,) — LAB degerleri

    Returns:
        float — Delta-E degeri
            < 1: Fark gorulemez
            1-5: Hafif fark
            5-15: Belirgin fark
            > 15: Ciddi renk kaymasi
    """
    return float(np.sqrt(np.sum((lab1 - lab2) ** 2)))


def check_color_accuracy(original_b64, generated_b64):
    """Orijinal urun ile AI ciktisi arasindaki renk dogrlugunu kontrol eder.

    Args:
        original_b64: str — orijinal urun gorseli (base64)
        generated_b64: str — AI ciktisi (base64)

    Returns:
        dict: {
            'delta_e': float — ortalama Delta-E (dusuk = iyi),
            'rating': str — 'mukemmel'/'iyi'/'kabul_edilebilir'/'renk_kaymasi',
            'details': str — Turkce aciklama,
        }
    """
    if cv2 is None:
        return {
            'delta_e': -1,
            'rating': 'bilinmiyor',
            'details': 'OpenCV kurulu degil, renk kontrolu yapilamadi.',
        }

    orig_colors = _extract_dominant_color_lab(original_b64)
    gen_colors = _extract_dominant_color_lab(generated_b64)

    if orig_colors is None or gen_colors is None:
        return {
            'delta_e': -1,
            'rating': 'bilinmiyor',
            'details': 'Renk cikarma basarisiz.',
        }

    # Her dominant renk icin en yakin eslemeyi bul
    total_delta_e = 0
    count = 0
    for orig_lab in orig_colors:
        min_de = float('inf')
        for gen_lab in gen_colors:
            de = delta_e_ciede2000_simple(orig_lab, gen_lab)
            if de < min_de:
                min_de = de
        total_delta_e += min_de
        count += 1

    avg_delta_e = total_delta_e / count if count > 0 else 999

    # Degerlendirme
    if avg_delta_e < 5:
        rating = 'mukemmel'
        details = 'Renk dogrulugu mukemmel — neredeyse ayni.'
    elif avg_delta_e < 10:
        rating = 'iyi'
        details = 'Renk dogrulugu iyi — hafif fark var ama kabul edilebilir.'
    elif avg_delta_e < 20:
        rating = 'kabul_edilebilir'
        details = 'Renk dogrulugu orta — belirgin fark var.'
    else:
        rating = 'renk_kaymasi'
        details = 'Renk kaymasi tespit edildi — urun rengi korunmamis.'

    return {
        'delta_e': round(avg_delta_e, 2),
        'rating': rating,
        'details': details,
    }


def compute_quality_score(original_b64, generated_b64):
    """Genel kalite skoru hesaplar.

    Bilesenler:
    - Renk dogrulugu (%60 agirlik)
    - Gorsel boyut (%20 agirlik)
    - Format/gecerlilik (%20 agirlik)

    Args:
        original_b64: str — orijinal urun gorseli (base64)
        generated_b64: str — AI ciktisi (base64)

    Returns:
        dict: {
            'score': float (0-100),
            'color_accuracy': dict — check_color_accuracy sonucu,
            'is_acceptable': bool,
            'details': str,
        }
    """
    score = 100.0
    details_parts = []

    # 1. Renk dogrulugu (%60)
    color_result = check_color_accuracy(original_b64, generated_b64)
    if color_result['delta_e'] >= 0:
        color_score = max(0, 100 - (color_result['delta_e'] * 3))
        score = score * 0.4 + color_score * 0.6
        details_parts.append(
            'Renk: %s (Delta-E: %.1f)' % (color_result['rating'], color_result['delta_e'])
        )
    else:
        details_parts.append('Renk kontrolu yapilamadi')

    # 2. Gorsel boyut kontrolu (%20)
    try:
        gen_bytes = base64.b64decode(generated_b64)
        size_kb = len(gen_bytes) / 1024
        if size_kb < 20:
            score -= 20
            details_parts.append('Cikti cok kucuk (%.1fKB)' % size_kb)
        elif size_kb > 50:
            details_parts.append('Cikti boyutu iyi (%.1fKB)' % size_kb)
    except Exception:
        score -= 10

    # 3. Format gecerliligi (%20)
    try:
        gen_bytes = base64.b64decode(generated_b64)
        pil_img = Image.open(io.BytesIO(gen_bytes))
        w, h = pil_img.size
        if w < 200 or h < 200:
            score -= 20
            details_parts.append('Cozunurluk cok dusuk (%dx%d)' % (w, h))
        else:
            details_parts.append('Boyut: %dx%d' % (w, h))
    except Exception:
        score -= 20
        details_parts.append('Gorsel acilamadi')

    final_score = max(0, min(100, score))

    return {
        'score': round(final_score, 1),
        'color_accuracy': color_result,
        'is_acceptable': final_score >= 50,
        'details': ' | '.join(details_parts),
    }
