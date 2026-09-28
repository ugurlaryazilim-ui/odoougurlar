# Kalite kontrol servisi — AI ciktisi dogrulama.
#
# Orijinal urun gorseli ile AI ciktisini karsilastirarak kalite skoru hesaplar:
#   1. Renk dogrulugu — arka plan maskelenmis dominant renkler, CIEDE2000
#   2. Keskinlik — Laplacian variance
#   3. Cozunurluk — pazaryeri (Trendyol 1200x1800) esigi
#   4. (Opsiyonel) Gorsel denetim — Gemini'nin buldugu gercek hatalar
#      (elbise altinda pantolon, bozuk parmak, etiket kalintisi...)
#
# NOT: Duz urun fotografi ile manken fotografi arasinda SSIM anlamsizdir
# (farkli kompozisyon); bu yuzden kaldirildi.

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

# Pazaryeri minimumu (Trendyol onerisi 1200x1800)
MIN_MARKETPLACE_SIZE = (1200, 1800)
# Gorsel denetimde bulunan her hata icin puan cezasi
VISUAL_ISSUE_PENALTY = 25
ACCEPTABLE_SCORE = 60


def _decode_rgb(image_b64, max_side=256):
    raw = base64.b64decode(image_b64)
    img = Image.open(io.BytesIO(raw)).convert('RGB')
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    return np.array(img)


def _rgb_to_lab(rgb_array):
    """RGB (uint8, ...x3) -> standart CIELAB (float)."""
    flat = rgb_array.reshape(-1, 1, 3).astype(np.uint8)
    lab = cv2.cvtColor(flat, cv2.COLOR_RGB2LAB).astype(np.float64).reshape(-1, 3)
    lab[:, 0] = lab[:, 0] * 100.0 / 255.0
    lab[:, 1] -= 128.0
    lab[:, 2] -= 128.0
    return lab


def _foreground_mask(lab):
    """Stüdyo arka planını (çok açık ve renksiz pikseller) dışarıda bırak."""
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    return ~((lab[:, 0] > 88) & (chroma < 8))


def _dominant_colors_lab(image_b64, num_clusters=4):
    """Arka plan hariç dominant renkler (LAB) ve ağırlıkları, büyükten küçüğe."""
    lab = _rgb_to_lab(_decode_rgb(image_b64))
    fg = lab[_foreground_mask(lab)]
    if len(fg) < 50:
        return None, None
    k = min(num_clusters, len(fg))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(fg.astype(np.float32), k, None, criteria, 3,
                                    cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    order = np.argsort(-counts)
    return centers[order].astype(np.float64), counts[order] / counts.sum()


def delta_e_ciede2000(lab1, lab2):
    """CIEDE2000 renk farkı (Sharma et al. 2005)."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    C_bar = (C1 + C2) / 2.0
    G = 0.5 * (1 - np.sqrt(C_bar ** 7 / (C_bar ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360

    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    else:
        dhp = h2p - h1p
        if dhp > 180:
            dhp -= 360
        elif dhp < -180:
            dhp += 360
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp / 2.0))

    Lp_bar = (L1 + L2) / 2.0
    Cp_bar = (C1p + C2p) / 2.0
    if C1p * C2p == 0:
        hp_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hp_bar = (h1p + h2p) / 2.0
    elif h1p + h2p < 360:
        hp_bar = (h1p + h2p + 360) / 2.0
    else:
        hp_bar = (h1p + h2p - 360) / 2.0

    T = (1 - 0.17 * np.cos(np.radians(hp_bar - 30)) + 0.24 * np.cos(np.radians(2 * hp_bar))
         + 0.32 * np.cos(np.radians(3 * hp_bar + 6)) - 0.20 * np.cos(np.radians(4 * hp_bar - 63)))
    d_theta = 30 * np.exp(-(((hp_bar - 275) / 25) ** 2))
    R_C = 2 * np.sqrt(Cp_bar ** 7 / (Cp_bar ** 7 + 25.0 ** 7))
    S_L = 1 + (0.015 * (Lp_bar - 50) ** 2) / np.sqrt(20 + (Lp_bar - 50) ** 2)
    S_C = 1 + 0.045 * Cp_bar
    S_H = 1 + 0.015 * Cp_bar * T
    R_T = -np.sin(np.radians(2 * d_theta)) * R_C
    return float(np.sqrt(
        (dLp / S_L) ** 2 + (dCp / S_C) ** 2 + (dHp / S_H) ** 2
        + R_T * (dCp / S_C) * (dHp / S_H)
    ))


def check_color_accuracy(original_b64, generated_b64):
    """Ürünün dominant rengi AI çıktısında korunmuş mu?

    Orijinal görseldeki arka plan dışı en baskın renkler (ürün), çıktıdaki
    renk kümelerinin en yakınıyla CIEDE2000 ile karşılaştırılır. Çıktıda cilt,
    saç vb. ek renkler olacağından yalnızca orijinal → çıktı yönü ölçülür.
    """
    if cv2 is None or Image is None:
        return {'delta_e': -1, 'rating': 'bilinmiyor', 'details': 'OpenCV/Pillow kurulu degil.'}
    try:
        orig_c, orig_w = _dominant_colors_lab(original_b64, num_clusters=3)
        gen_c, _ = _dominant_colors_lab(generated_b64, num_clusters=6)
    except Exception as e:
        _logger.warning('Renk cikarma hatasi: %s', e)
        orig_c = gen_c = None
    if orig_c is None or gen_c is None:
        return {'delta_e': -1, 'rating': 'bilinmiyor', 'details': 'Renk cikarma basarisiz.'}

    # Ağırlıklı ortalama: ürünün ana rengi daha önemli
    total, weight_sum = 0.0, 0.0
    for c, w in zip(orig_c, orig_w):
        if w < 0.1:
            continue  # gölge / küçük detay
        total += w * min(delta_e_ciede2000(c, g) for g in gen_c)
        weight_sum += w
    avg = total / weight_sum if weight_sum else 999.0

    if avg < 3:
        rating, details = 'mukemmel', 'Renk neredeyse ayni.'
    elif avg < 6:
        rating, details = 'iyi', 'Hafif renk farki.'
    elif avg < 12:
        rating, details = 'kabul_edilebilir', 'Belirgin renk farki.'
    else:
        rating, details = 'renk_kaymasi', 'Renk kaymasi — urun rengi korunmamis.'
    return {'delta_e': round(avg, 2), 'rating': rating, 'details': details}


def _compute_blur_score(image_b64):
    """Laplacian variance (yüksek = keskin). Hata durumunda -1."""
    if cv2 is None or Image is None:
        return -1.0
    try:
        gray = cv2.cvtColor(_decode_rgb(image_b64, max_side=768), cv2.COLOR_RGB2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception as e:
        _logger.debug('Bulaniklik tespiti hatasi: %s', e)
        return -1.0


def compute_quality_score(original_b64, generated_b64, visual_qc=None):
    """Genel kalite skoru (0-100).

    Ağırlıklar: renk %50, keskinlik %20, çözünürlük %30. Görsel denetim
    (visual_qc) verildiyse bulunan her hata için VISUAL_ISSUE_PENALTY düşülür.

    Args:
        original_b64: orijinal ürün görseli (base64)
        generated_b64: AI çıktısı (base64)
        visual_qc: garment_analyzer.visual_quality_check() sonucu veya None

    Returns:
        dict: score, color_accuracy, blur_score, issues, is_acceptable, details
    """
    score = 0.0
    details = []

    color = check_color_accuracy(original_b64, generated_b64)
    if color['delta_e'] >= 0:
        color_score = max(0.0, 100 - color['delta_e'] * 5)
        details.append('Renk: %s (ΔE2000 %.1f)' % (color['rating'], color['delta_e']))
    else:
        color_score = 50.0
        details.append('Renk kontrolu yapilamadi')
    score += color_score * 0.50

    blur_val = _compute_blur_score(generated_b64)
    if blur_val >= 0:
        blur_score = 100.0 if blur_val >= 100 else max(0.0, blur_val)
        details.append('Keskinlik: %.0f' % blur_val)
    else:
        blur_score = 50.0
    score += blur_score * 0.20

    try:
        w, h = Image.open(io.BytesIO(base64.b64decode(generated_b64))).size
        min_w, min_h = MIN_MARKETPLACE_SIZE
        size_score = 100.0 * min(1.0, min(w / min_w, h / min_h))
        details.append('Boyut: %dx%d' % (w, h))
    except Exception:
        size_score = 30.0
        details.append('Gorsel acilamadi')
    score += size_score * 0.30

    issues = list((visual_qc or {}).get('issues') or [])
    if issues:
        score -= VISUAL_ISSUE_PENALTY * len(issues)
        details.append('⚠ ' + '; '.join(issues))

    final = round(max(0.0, min(100.0, score)), 1)
    return {
        'score': final,
        'color_accuracy': color,
        'ssim_score': -1,
        'blur_score': round(blur_val, 1) if blur_val >= 0 else -1,
        'issues': issues,
        'is_acceptable': final >= ACCEPTABLE_SCORE and not issues,
        'details': ' | '.join(details),
    }
