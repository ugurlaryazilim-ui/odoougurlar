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
    - Renk dogrulugu (%40 agirlik)
    - SSIM yapisal benzerlik (%25 agirlik)
    - Bulaniklik tespiti (%15 agirlik)
    - Gorsel boyut + format (%20 agirlik)

    Args:
        original_b64: str — orijinal urun gorseli (base64)
        generated_b64: str — AI ciktisi (base64)

    Returns:
        dict: {
            'score': float (0-100),
            'color_accuracy': dict — check_color_accuracy sonucu,
            'ssim_score': float (0-1, 1=ayni),
            'blur_score': float (Laplacian variance, yuksek=keskin),
            'is_acceptable': bool,
            'details': str,
        }
    """
    score = 0.0
    details_parts = []
    ssim_val = -1.0
    blur_val = -1.0

    # 1. Renk dogrulugu (%40)
    color_result = check_color_accuracy(original_b64, generated_b64)
    if color_result['delta_e'] >= 0:
        color_score = max(0, 100 - (color_result['delta_e'] * 3))
        score += color_score * 0.40
        details_parts.append(
            'Renk: %s (Delta-E: %.1f, puan: %.0f)' % (
                color_result['rating'], color_result['delta_e'], color_score
            )
        )
    else:
        score += 50 * 0.40  # Bilinmiyor — orta skor
        details_parts.append('Renk kontrolu yapilamadi')

    # 2. SSIM Yapisal Benzerlik (%25)
    try:
        ssim_val = _compute_ssim(original_b64, generated_b64)
        if ssim_val >= 0:
            # SSIM 0-1 arasi, 0.3+ iyi (try-on icin tam eslesme beklenmez)
            ssim_score = min(100, ssim_val * 200)  # 0.5 = 100 puan
            score += ssim_score * 0.25
            details_parts.append('SSIM: %.3f (puan: %.0f)' % (ssim_val, ssim_score))
        else:
            score += 50 * 0.25
    except Exception:
        score += 50 * 0.25
        details_parts.append('SSIM hesaplanamadi')

    # 3. Bulaniklik Tespiti — Laplacian Variance (%15)
    try:
        blur_val = _compute_blur_score(generated_b64)
        if blur_val >= 0:
            # Laplacian variance: <50 = bulanik, 100+ = keskin, 200+ = cok keskin
            if blur_val >= 100:
                blur_score = 100
            elif blur_val >= 50:
                blur_score = 50 + (blur_val - 50)
            else:
                blur_score = max(0, blur_val)
            score += blur_score * 0.15
            details_parts.append('Keskinlik: %.0f (puan: %.0f)' % (blur_val, blur_score))
        else:
            score += 50 * 0.15
    except Exception:
        score += 50 * 0.15

    # 4. Gorsel boyut + format (%20)
    try:
        gen_bytes = base64.b64decode(generated_b64)
        size_kb = len(gen_bytes) / 1024
        pil_img = Image.open(io.BytesIO(gen_bytes))
        w, h = pil_img.size

        size_format_score = 100
        if size_kb < 20:
            size_format_score -= 40
            details_parts.append('Cikti cok kucuk (%.1fKB)' % size_kb)
        if w < 200 or h < 200:
            size_format_score -= 40
            details_parts.append('Cozunurluk cok dusuk (%dx%d)' % (w, h))
        else:
            details_parts.append('Boyut: %dx%d (%.1fKB)' % (w, h, size_kb))

        score += max(0, size_format_score) * 0.20
    except Exception:
        score += 30 * 0.20
        details_parts.append('Gorsel acilamadi')

    final_score = max(0, min(100, score))

    return {
        'score': round(final_score, 1),
        'color_accuracy': color_result,
        'ssim_score': round(ssim_val, 4) if ssim_val >= 0 else -1,
        'blur_score': round(blur_val, 1) if blur_val >= 0 else -1,
        'is_acceptable': final_score >= 50,
        'details': ' | '.join(details_parts),
    }


def _compute_ssim(original_b64, generated_b64):
    """SSIM (Structural Similarity Index) hesapla.

    Iki gorsel arasindaki yapisal benzerligi olcer.
    Virtual try-on icin dusuk SSIM beklenir (farkli arka plan/vucut),
    ama kiyafet bolgesi yuksek olmali.

    Returns:
        float: 0-1 arasi SSIM degeri, veya -1 (hesaplanamadiysa)
    """
    if cv2 is None or Image is None:
        return -1.0

    try:
        orig_bytes = base64.b64decode(original_b64)
        gen_bytes = base64.b64decode(generated_b64)

        orig_img = Image.open(io.BytesIO(orig_bytes)).convert('RGB')
        gen_img = Image.open(io.BytesIO(gen_bytes)).convert('RGB')

        # Ayni boyuta getir (kucuk, hizli hesaplama)
        target_size = (256, 256)
        orig_resized = orig_img.resize(target_size, Image.LANCZOS)
        gen_resized = gen_img.resize(target_size, Image.LANCZOS)

        orig_gray = cv2.cvtColor(np.array(orig_resized), cv2.COLOR_RGB2GRAY)
        gen_gray = cv2.cvtColor(np.array(gen_resized), cv2.COLOR_RGB2GRAY)

        # Mean SSIM hesapla (pencere bazli)
        C1 = (0.01 * 255) ** 2
        C2 = (0.03 * 255) ** 2

        orig_f = orig_gray.astype(np.float64)
        gen_f = gen_gray.astype(np.float64)

        mu1 = cv2.GaussianBlur(orig_f, (11, 11), 1.5)
        mu2 = cv2.GaussianBlur(gen_f, (11, 11), 1.5)

        mu1_sq = mu1 ** 2
        mu2_sq = mu2 ** 2
        mu1_mu2 = mu1 * mu2

        sigma1_sq = cv2.GaussianBlur(orig_f ** 2, (11, 11), 1.5) - mu1_sq
        sigma2_sq = cv2.GaussianBlur(gen_f ** 2, (11, 11), 1.5) - mu2_sq
        sigma12 = cv2.GaussianBlur(orig_f * gen_f, (11, 11), 1.5) - mu1_mu2

        ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / \
                   ((mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2))

        return float(np.mean(ssim_map))

    except Exception as e:
        _logger.debug('SSIM hesaplama hatasi: %s', e)
        return -1.0


def _compute_blur_score(image_b64):
    """Laplacian Variance ile bulaniklik skoru hesapla.

    Yuksek deger = keskin gorsel, dusuk deger = bulanik gorsel.

    Returns:
        float: Laplacian variance degeri, veya -1
    """
    if cv2 is None or Image is None:
        return -1.0

    try:
        gen_bytes = base64.b64decode(image_b64)
        pil_img = Image.open(io.BytesIO(gen_bytes)).convert('RGB')

        # Olcekle (hiz icin)
        pil_img = pil_img.resize((512, 512), Image.LANCZOS)
        gray = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2GRAY)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        return float(laplacian.var())

    except Exception as e:
        _logger.debug('Bulaniklik tespiti hatasi: %s', e)
        return -1.0
