# Garment (urun gorseli) on isleme pipeline'i.
#
# FASHN API'ye gonderilmeden once urun gorsellerini profesyonel
# sekilde hazirlayan 7 adimli pipeline:
#   1. Beyaz denge duzeltme (Gray-World)
#   2. Pozlama normalizasyonu (CLAHE)
#   3. Gurultu azaltma (bilateral filter)
#   4. Akilli boyutlandirma (Lanczos, 864px hedef)
#   5. RGBA -> RGB beyaz zemin donusumu
#   6. Hafif keskinlestirme (unsharp mask)
#   7. JPEG cikti (%95 kalite)

import base64
import io
import logging

import numpy as np

_logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageFilter, ImageEnhance
except ImportError:
    Image = None
    _logger.warning('Pillow kurulu degil. pip install Pillow')

try:
    import cv2
except ImportError:
    cv2 = None
    _logger.warning('OpenCV kurulu degil. pip install opencv-python-headless')


# ---------------------------------------------------------------------------
# 1. Beyaz Denge — Gray-World Algoritmasi
# ---------------------------------------------------------------------------
def white_balance_gray_world(img_array):
    """Tum renklerin ortalamasinin gri olmasi gerektigini varsayarak kanal
    basina duzeltme yapar. Sari/mavi/yesil ton kaymalarini duzeltir.

    Args:
        img_array: numpy array (BGR, uint8)
    Returns:
        numpy array (BGR, uint8) — duzeltilmis
    """
    if cv2 is None:
        return img_array

    result = img_array.copy().astype(np.float64)
    avg_b = np.mean(result[:, :, 0])
    avg_g = np.mean(result[:, :, 1])
    avg_r = np.mean(result[:, :, 2])
    avg_all = (avg_b + avg_g + avg_r) / 3.0

    if avg_b > 0:
        result[:, :, 0] = np.clip(result[:, :, 0] * (avg_all / avg_b), 0, 255)
    if avg_g > 0:
        result[:, :, 1] = np.clip(result[:, :, 1] * (avg_all / avg_g), 0, 255)
    if avg_r > 0:
        result[:, :, 2] = np.clip(result[:, :, 2] * (avg_all / avg_r), 0, 255)

    return result.astype(np.uint8)


# ---------------------------------------------------------------------------
# 2. Pozlama Normalizasyonu — CLAHE (LAB L kanali)
# ---------------------------------------------------------------------------
def normalize_exposure(img_array, clip_limit=2.0, tile_size=8):
    """LAB renk uzayinda L kanalina CLAHE uygular.
    Karanlik/asiri parlak gorsellerde detayi korur.

    Args:
        img_array: numpy array (BGR, uint8)
        clip_limit: CLAHE kontrast limiti (2.0 = dengeli)
        tile_size: CLAHE karo boyutu
    Returns:
        numpy array (BGR, uint8)
    """
    if cv2 is None:
        return img_array

    lab = cv2.cvtColor(img_array, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_size, tile_size))
    cl = clahe.apply(l_ch)
    merged = cv2.merge((cl, a_ch, b_ch))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


# ---------------------------------------------------------------------------
# 3. Gurultu Azaltma — Bilateral Filter
# ---------------------------------------------------------------------------
def reduce_noise(img_array, d=9, sigma_color=75, sigma_space=75):
    """Kenarlari koruyarak gurultuyu azaltir.
    Kumas dokusunu yok etmeden telefon kamerasi gurultusunu temizler.

    Args:
        img_array: numpy array (BGR, uint8)
    Returns:
        numpy array (BGR, uint8)
    """
    if cv2 is None:
        return img_array

    return cv2.bilateralFilter(img_array, d, sigma_color, sigma_space)


# ---------------------------------------------------------------------------
# 4. Akilli Boyutlandirma — Lanczos
# ---------------------------------------------------------------------------
def smart_resize(pil_image, target_long_edge=864):
    """En-boy oranini koruyarak en uzun kenari target_long_edge'e getirir.
    Lanczos interpolasyon ile detay korunur.

    FASHN v1.6 cikti boyutu: 864x1296
    FASHN v1.6 maksimum giris: 2000px (en uzun kenar)

    Args:
        pil_image: PIL Image
        target_long_edge: hedef piksel (en uzun kenar)
    Returns:
        PIL Image — boyutlandirilmis
    """
    if Image is None:
        return pil_image

    w, h = pil_image.size

    # Zaten kucukse dokunma
    if max(w, h) <= target_long_edge:
        return pil_image

    # En-boy oranini koru
    ratio = target_long_edge / max(w, h)
    new_w = int(w * ratio)
    new_h = int(h * ratio)

    return pil_image.resize((new_w, new_h), resample=Image.LANCZOS)


# ---------------------------------------------------------------------------
# 5. RGBA -> RGB Beyaz Zemin Donusumu
# ---------------------------------------------------------------------------
def rgba_to_rgb_white(pil_image):
    """Seffaf arka plani beyaz zemine donusturur.

    KRITIK: BiRefNet RGBA (seffaf) cikti verir.
    FASHN API sadece RGB kabul eder — RGBA gonderilirse artefakt olusur!

    Args:
        pil_image: PIL Image (RGBA veya RGB)
    Returns:
        PIL Image (RGB, beyaz zemin)
    """
    if Image is None:
        return pil_image

    if pil_image.mode == 'RGBA':
        background = Image.new('RGB', pil_image.size, (255, 255, 255))
        background.paste(pil_image, mask=pil_image.split()[3])
        return background
    elif pil_image.mode != 'RGB':
        return pil_image.convert('RGB')
    return pil_image


# ---------------------------------------------------------------------------
# 6. Hafif Keskinlestirme — Unsharp Mask
# ---------------------------------------------------------------------------
def sharpen_image(pil_image, amount=1.0, threshold=3):
    """Resize sonrasi hafif bulaniklasmayi duzeltir.
    Kumas dokusunu koruyarak keskinlestirir.

    Args:
        pil_image: PIL Image (RGB)
        amount: keskinlik miktari (1.0 = hafif, 2.0 = agresif)
        threshold: dusuk kontrastli alanlari atla
    Returns:
        PIL Image (RGB)
    """
    if Image is None:
        return pil_image

    # PIL UnsharpMask: radius, percent, threshold
    sharpened = pil_image.filter(ImageFilter.UnsharpMask(
        radius=2,
        percent=int(amount * 100),
        threshold=threshold,
    ))
    return sharpened


# ---------------------------------------------------------------------------
# 7. JPEG Cikti
# ---------------------------------------------------------------------------
def to_jpeg_base64(pil_image, quality=95):
    """PIL Image'i JPEG base64 string'e donusturur.

    Args:
        pil_image: PIL Image (RGB)
        quality: JPEG kalite (95 = yuksek, 85 = orta)
    Returns:
        str — base64 encoded JPEG
    """
    if Image is None:
        return None

    buf = io.BytesIO()
    pil_image.save(buf, format='JPEG', quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode('ascii')


def to_png_bytes(pil_image):
    """PIL Image'i PNG bytes'a donusturur (upload icin).

    Args:
        pil_image: PIL Image
    Returns:
        bytes — PNG veri
    """
    buf = io.BytesIO()
    pil_image.save(buf, format='PNG')
    return buf.getvalue()


# ===========================================================================
# ANA PIPELINE
# ===========================================================================

def preprocess_garment_image(image_base64, target_long_edge=864,
                              apply_white_balance=True,
                              apply_exposure_norm=True,
                              apply_noise_reduction=True,
                              apply_sharpening=True):
    """Urun gorselini FASHN API'ye gondermeden once profesyonel sekilde hazirlar.

    7 adimli pipeline:
    1. Beyaz denge (Gray-World) — renk kaymasini duzeltir
    2. Pozlama normalizasyonu (CLAHE) — karanlik/parlak duzeltir
    3. Gurultu azaltma (bilateral) — telefon gurultusunu temizler
    4. Akilli boyutlandirma (Lanczos) — detay korunur
    5. RGBA -> RGB (beyaz zemin) — FASHN uyumlulugu
    6. Keskinlestirme (unsharp mask) — resize sonrasi netlik
    7. JPEG %95 kalite cikti

    Args:
        image_base64: str — base64 encoded gorsel
        target_long_edge: int — hedef boyut (864 = FASHN v1.6 optimal)
        apply_white_balance: bool — beyaz denge uygulansin mi
        apply_exposure_norm: bool — pozlama normalizasyonu uygulansin mi
        apply_noise_reduction: bool — gurultu azaltma uygulansin mi
        apply_sharpening: bool — keskinlestirme uygulansin mi

    Returns:
        dict: {
            'image_base64': str — islenimis gorsel (JPEG base64),
            'image_bytes': bytes — islenimis gorsel (PNG bytes, upload icin),
            'original_size': tuple (w, h),
            'final_size': tuple (w, h),
            'steps_applied': list of str,
            'had_alpha': bool — orijinal RGBA miydi,
        }
    """
    steps_applied = []
    had_alpha = False

    try:
        # Base64 decode -> PIL Image
        raw_bytes = base64.b64decode(image_base64)
        pil_image = Image.open(io.BytesIO(raw_bytes))
        original_size = pil_image.size

        _logger.info(
            'Garment on isleme basliyor: boyut=%sx%s, mod=%s, boyut=%.1fKB',
            pil_image.size[0], pil_image.size[1], pil_image.mode,
            len(raw_bytes) / 1024,
        )

        # RGBA kontrol
        if pil_image.mode == 'RGBA':
            had_alpha = True

        # --- OpenCV adimlari (1-3) ---
        if cv2 is not None and (apply_white_balance or apply_exposure_norm or apply_noise_reduction):
            # PIL -> numpy (BGR)
            rgb_array = np.array(rgba_to_rgb_white(pil_image) if had_alpha else pil_image.convert('RGB'))
            bgr_array = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)

            # 1. Beyaz denge
            if apply_white_balance:
                bgr_array = white_balance_gray_world(bgr_array)
                steps_applied.append('beyaz_denge')

            # 2. Pozlama normalizasyonu
            if apply_exposure_norm:
                bgr_array = normalize_exposure(bgr_array)
                steps_applied.append('pozlama_norm')

            # 3. Gurultu azaltma
            if apply_noise_reduction:
                bgr_array = reduce_noise(bgr_array)
                steps_applied.append('gurultu_azaltma')

            # numpy -> PIL
            rgb_array = cv2.cvtColor(bgr_array, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb_array)
        else:
            # OpenCV yoksa sadece RGB'ye cevir
            pil_image = rgba_to_rgb_white(pil_image) if had_alpha else pil_image.convert('RGB')

        # 4. Akilli boyutlandirma
        pil_image = smart_resize(pil_image, target_long_edge)
        if pil_image.size != original_size:
            steps_applied.append('boyutlandirma')

        # 5. RGBA -> RGB (OpenCV adimindan sonra tekrar kontrol)
        pil_image = rgba_to_rgb_white(pil_image)
        if had_alpha:
            steps_applied.append('rgba_rgb_donusum')

        # 6. Keskinlestirme
        if apply_sharpening:
            pil_image = sharpen_image(pil_image)
            steps_applied.append('keskinlestirme')

        final_size = pil_image.size

        # 7. Cikti
        result_b64 = to_jpeg_base64(pil_image, quality=95)
        result_bytes = to_png_bytes(pil_image)

        _logger.info(
            'Garment on isleme tamamlandi: %sx%s -> %sx%s, adimlar=%s',
            original_size[0], original_size[1],
            final_size[0], final_size[1],
            ', '.join(steps_applied) or 'yok',
        )

        return {
            'image_base64': result_b64,
            'image_bytes': result_bytes,
            'original_size': original_size,
            'final_size': final_size,
            'steps_applied': steps_applied,
            'had_alpha': had_alpha,
        }

    except Exception as e:
        _logger.warning('Garment on isleme hatasi, orijinal kullaniliyor: %s', e)
        # Hata durumunda orijinal gorseli dondur (pipeline basarisiz olursa duraklama)
        return {
            'image_base64': image_base64,
            'image_bytes': base64.b64decode(image_base64),
            'original_size': (0, 0),
            'final_size': (0, 0),
            'steps_applied': [],
            'had_alpha': False,
        }


def convert_birefnet_output_to_rgb(image_data_bytes):
    """BiRefNet ciktisini (RGBA PNG) -> RGB JPEG'e donusturur.

    BiRefNet arka plan kaldirma sonrasi RGBA (seffaf) cikti verir.
    FASHN API sadece RGB kabul eder.

    Args:
        image_data_bytes: bytes — indirilen gorsel verisi (genelde RGBA PNG)
    Returns:
        bytes — RGB JPEG gorsel (beyaz zemin uzerinde)
    """
    if Image is None:
        return image_data_bytes

    try:
        pil_image = Image.open(io.BytesIO(image_data_bytes))

        if pil_image.mode == 'RGBA':
            background = Image.new('RGB', pil_image.size, (255, 255, 255))
            background.paste(pil_image, mask=pil_image.split()[3])
            pil_image = background
            _logger.info('BiRefNet RGBA -> RGB beyaz zemin donusumu yapildi')
        elif pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')

        buf = io.BytesIO()
        pil_image.save(buf, format='JPEG', quality=95)
        return buf.getvalue()

    except Exception as e:
        _logger.warning('BiRefNet cikti donusumu hatasi: %s', e)
        return image_data_bytes
