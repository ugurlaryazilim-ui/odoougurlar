# Garment (urun gorseli) on isleme pipeline'i.
#
# AI try-on'a gonderilmeden once urun gorsellerini hazirlayan pipeline:
#   0. Guvenlik etiketi silme (inpaint)
#   1. Beyaz denge (Gray-World) — VARSAYILAN KAPALI: tek renkli (ör. kirmizi)
#      giysilerde ortalamayi griye cekip urun rengini bozuyordu
#   2. Pozlama normalizasyonu (CLAHE)
#   3. Gurultu azaltma (bilateral) — VARSAYILAN KAPALI: orgu/tvit dokusunu yumusatiyordu
#   4. Akilli boyutlandirma (Lanczos)
#   5. RGBA -> RGB beyaz zemin donusumu
#   6. Hafif keskinlestirme (unsharp mask)
#   7. WebP cikti (%95 kalite)

import base64
import io
import logging

import numpy as np

_logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageFilter, ImageEnhance
    # Odoo, Pillow'u yalnız temel formatlarla başlatır (Image._initialized = 2);
    # WebP kaydı için eklenti açıkça yüklenmeli (Odoo'nun IcoImagePlugin'i yüklemesi gibi)
    try:
        from PIL import WebPImagePlugin  # noqa: F401
    except ImportError:
        pass
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
# 3.5 Güvenlik Etiketi / Alarm Pini Silme — Inpainting (Telea)
# ---------------------------------------------------------------------------
# Etiket inpaint eşikleri. Tespit promptu da %50 eşiği kullanır (çift süzme yok).
# Alan sınırı yakın çekim detay fotoğraflarında gerçek alarmı atmayacak kadar geniş.
MIN_TAG_CONFIDENCE = 0.5
MAX_TAG_AREA_RATIO = 0.15
# Askı (kanca + çubuk) ve pantolon askısı mandalları. Kutuyla SİLİNMEZ: ürün genişliğindeki çubuğun
# maskesi bel bandını (düğme, yan tırnak, pile başları) tamamen yutuyordu. Ürün metinle segmente
# edilip (apply_garment_mask) askı zemine bırakılır.
HANGER_LABELS = ('hanger', 'hanger_clip')
# Düğmeye benzeyen küçük yuvarlak nesne: gerçek düğme mi, alarm iğnesinin başı mı yakın planda
# doğrulanana kadar silinmez (verify_button_candidates sonucu alarm_tag / garment_detail olur)
CANDIDATE_LABELS = ('button_like',)
NON_ERASE_LABELS = HANGER_LABELS + CANDIDATE_LABELS


def tag_box_to_pixels(item, w, h, pad_ratio=0.25, min_pad=10):
    """Gemini kutusunu ([ymin, xmin, ymax, xmax], 0-1000) dolgulu piksel dikdörtgenine çevir.

    Returns:
        (x1, y1, x2, y2) veya None (geçersiz / silinmemeli)
    """
    box = item.get('box_2d') if isinstance(item, dict) else item
    if not box or len(box) < 4:
        return None
    if isinstance(item, dict):
        if item.get('label') == 'design_label':
            return None  # ürünün kendi tasarım etiketi — dokunma
        if item.get('label') in NON_ERASE_LABELS:
            return None  # askı segmentasyonla ayrılır; düğme adayı önce doğrulanır
        if item.get('confidence') is not None:
            try:
                if float(item['confidence']) < MIN_TAG_CONFIDENCE:
                    return None
            except (TypeError, ValueError):
                pass
    try:
        ymin, xmin, ymax, xmax = (float(v) for v in box[:4])
    except (TypeError, ValueError):
        return None
    if max(ymin, xmin, ymax, xmax) > 1.0:
        ymin, xmin, ymax, xmax = ymin / 1000.0, xmin / 1000.0, ymax / 1000.0, xmax / 1000.0
    px1, py1 = max(0, int(xmin * w)), max(0, int(ymin * h))
    px2, py2 = min(w, int(xmax * w)), min(h, int(ymax * h))
    if px2 <= px1 or py2 <= py1:
        return None
    if (px2 - px1) * (py2 - py1) > MAX_TAG_AREA_RATIO * w * h:
        return None  # etiket değil (cep, logo, baskı...)
    # Dolgu kutunun geometrik ortalamasına göre ve iki yönde eşit: kalem tipi (ince uzun) alarmda
    # uzun kenarın %60'ı bel ortasında dikey bir şerit maskesine dönüşüyor, model şeridi fermuar sanıyordu
    pad = max(min_pad, int(((px2 - px1) * (py2 - py1)) ** 0.5 * pad_ratio))
    # İnce uzun kutuda dolgu kısa kenarı aşmaz: maske yandaki ürün parçalarını yutmasın
    pad = min(pad, max(min_pad, min(px2 - px1, py2 - py1)))
    return (max(0, px1 - pad), max(0, py1 - pad), min(w, px2 + pad), min(h, py2 + pad))


def crop_boxes_for_zoom(image_base64, boxes, context=3.0, min_side=160, out_side=512):
    """Her kutuyu çevresiyle birlikte kare kırpıp out_side'a büyüt (yakın plan doğrulama için).

    Küçültülmüş tam görselde alarm iğnesinin başı ile düğme ayırt edilemiyordu: delik / sap / iplik
    ancak yakın planda görünür.

    Returns:
        list[base64 JPEG] — kutu sırasıyla; geçersiz kutu için None
    """
    img = Image.open(io.BytesIO(base64.b64decode(image_base64))).convert('RGB')
    w, h = img.size
    crops = []
    for item in boxes or []:
        box = item.get('box_2d') if isinstance(item, dict) else item
        try:
            ymin, xmin, ymax, xmax = (float(v) / 1000.0 for v in box[:4])
        except (TypeError, ValueError):
            crops.append(None)
            continue
        cx, cy = (xmin + xmax) / 2 * w, (ymin + ymax) / 2 * h
        side = max(min_side, max((xmax - xmin) * w, (ymax - ymin) * h) * context)
        side = min(side, w, h)
        x1 = int(min(max(0, cx - side / 2), w - side))
        y1 = int(min(max(0, cy - side / 2), h - side))
        if side <= 0 or xmax <= xmin or ymax <= ymin:
            crops.append(None)
            continue
        crop = img.crop((x1, y1, x1 + int(side), y1 + int(side))).resize((out_side, out_side), Image.LANCZOS)
        buf = io.BytesIO()
        crop.save(buf, format='JPEG', quality=95)
        crops.append(base64.b64encode(buf.getvalue()).decode())
    return crops


def protect_box_pixels(item, w, h, pad=4):
    """Etikete eklenmiş korunacak ürün detayı kutuları (fermuar, düğme, logo...) → piksel dikdörtgenleri."""
    rects = []
    for box in (item.get('protect') or []) if isinstance(item, dict) else []:
        try:
            ymin, xmin, ymax, xmax = (float(v) for v in box[:4])
        except (TypeError, ValueError):
            continue
        if max(ymin, xmin, ymax, xmax) > 1.0:
            ymin, xmin, ymax, xmax = ymin / 1000.0, xmin / 1000.0, ymax / 1000.0, xmax / 1000.0
        x1, y1 = max(0, int(xmin * w) - pad), max(0, int(ymin * h) - pad)
        x2, y2 = min(w, int(xmax * w) + pad), min(h, int(ymax * h) + pad)
        if x2 > x1 and y2 > y1:
            rects.append((x1, y1, x2, y2))
    return rects


def crop_to_content(image_base64, margin_ratio=0.04, threshold=245):
    """Beyaz zeminli (arka planı kaldırılmış) ürün görselini ürüne kırp.

    Mağaza fotoğrafında ürün kadrajın küçük bir kısmıdır; kırpmak hem etiket
    tespitinde alarmı büyütür hem de try-on'a daha net ürün görseli gider.
    """
    if Image is None:
        return image_base64
    try:
        img = Image.open(io.BytesIO(base64.b64decode(image_base64))).convert('RGB')
        arr = np.array(img)
        content = np.where(arr.min(axis=2) < threshold)
        if content[0].size == 0:
            return image_base64
        y1, y2 = int(content[0].min()), int(content[0].max())
        x1, x2 = int(content[1].min()), int(content[1].max())
        w, h = img.size
        if (x2 - x1) * (y2 - y1) > 0.9 * w * h:
            return image_base64  # zaten sıkı kadraj
        mx, my = int(w * margin_ratio), int(h * margin_ratio)
        img = img.crop((max(0, x1 - mx), max(0, y1 - my), min(w, x2 + mx), min(h, y2 + my)))
        return to_jpeg_base64(img, quality=95)
    except Exception as e:
        _logger.warning('Ürüne kırpma başarısız: %s', e)
        return image_base64


# Segmentasyon maskesi ürünün (beyaz olmayan) piksellerinin en az bu kadarını tutmalı;
# altındaysa model ürünü kaçırmıştır, askı silinmeden devam edilir
MIN_GARMENT_MASK_KEEP = 0.4


def apply_garment_mask(image_base64, mask_bytes, threshold=245):
    """Ürün maskesi dışını (askı kancası, çubuğu, mandallar) beyaza boya → JPEG base64 veya None.

    Maske ürünün çoğunu kaçırıyorsa None döner (görsel değiştirilmez).
    """
    if Image is None or not mask_bytes:
        return None
    img = Image.open(io.BytesIO(base64.b64decode(image_base64))).convert('RGB')
    mask = Image.open(io.BytesIO(mask_bytes)).convert('L')
    if mask.size != img.size:
        mask = mask.resize(img.size, Image.NEAREST)
    arr = np.array(img)
    keep = np.array(mask) > 127
    content = arr.min(axis=2) < threshold
    total = int(content.sum())
    if not total or not keep.any():
        return None
    kept = int((content & keep).sum()) / total
    if kept < MIN_GARMENT_MASK_KEEP:
        _logger.warning('Ürün maskesi ürünün yalnız %%%d kısmını tutuyor, askı silinmedi', round(kept * 100))
        return None
    arr[~keep] = 255
    _logger.info('Askı/mandal ürün maskesiyle ayrıldı (ürünün %%%d kısmı korundu)', round(kept * 100))
    return to_jpeg_base64(Image.fromarray(arr), quality=95)


def texture_fill_tags_base64(image_base64, tag_boxes, pad_ratio=0.25):
    """Etiket bölgesini aynı satırlardaki komşu kumaşla doldur (AI silme izli kaldıysa).

    Bel bandı ribi, örgü, dikiş çizgileri yatay komşuda aynı devam eder: soldaki (yoksa sağdaki)
    eşit genişlikte şerit kopyalanır, kenarlar yumuşak geçişle harmanlanır. Telea'nın aksine
    bulanık leke bırakmaz — model lekeyi fermuar / parça sanmaz.
    """
    if Image is None or not tag_boxes:
        return image_base64
    img = Image.open(io.BytesIO(base64.b64decode(image_base64))).convert('RGB')
    arr = np.array(img).astype(np.float32)
    h, w = arr.shape[:2]
    filled = 0
    for item in tag_boxes:
        rect = tag_box_to_pixels(item, w, h, pad_ratio=pad_ratio)
        if not rect:
            continue
        x1, y1, x2, y2 = rect
        bw = x2 - x1
        if x1 - bw >= 0:
            src = arr[y1:y2, x1 - bw:x1].copy()
        elif x2 + bw <= w:
            src = arr[y1:y2, x2:x2 + bw].copy()
        else:
            continue
        # Kenarlarda dolgudan dar (≤8 px) yumuşak geçiş: dikiş izi kalmasın, etiket hiç karışmasın
        ramp = max(1, min(bw // 4, 8))
        alpha = np.ones(bw, np.float32)
        alpha[:ramp] = np.linspace(0.0, 1.0, ramp, endpoint=False)
        alpha[-ramp:] = np.minimum(alpha[-ramp:], np.linspace(1.0, 0.0, ramp))
        alpha = alpha[None, :, None]
        arr[y1:y2, x1:x2] = src * alpha + arr[y1:y2, x1:x2] * (1 - alpha)
        filled += 1
    if not filled:
        return image_base64
    _logger.info('Doku dolgusu: %d etiket bölgesi komşu kumaşla dolduruldu', filled)
    return to_jpeg_base64(Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)), quality=95)


def crop_around_boxes(image_base64, boxes, context=1.5, min_side=160):
    """Kutuların birleşimini çevresiyle (her yönde kutu boyunun context katı) kırp → JPEG base64."""
    if Image is None or not boxes:
        return None
    img = Image.open(io.BytesIO(base64.b64decode(image_base64))).convert('RGB')
    w, h = img.size
    rects = [r for r in (tag_box_to_pixels(b, w, h, pad_ratio=0, min_pad=0) for b in boxes) if r]
    if not rects:
        return None
    x1, y1 = min(r[0] for r in rects), min(r[1] for r in rects)
    x2, y2 = max(r[2] for r in rects), max(r[3] for r in rects)
    mx = max(int((x2 - x1) * context), min_side // 2)
    my = max(int((y2 - y1) * context), min_side // 2)
    crop = img.crop((max(0, x1 - mx), max(0, y1 - my), min(w, x2 + mx), min(h, y2 + my)))
    return to_jpeg_base64(crop, quality=95)


def inpaint_tags_base64(image_base64, tag_boxes):
    """Base64 görsel üzerinde OpenCV Telea ile etiket silme (AI silme yedeği)."""
    if cv2 is None or not tag_boxes:
        return image_base64
    img = Image.open(io.BytesIO(base64.b64decode(image_base64))).convert('RGB')
    bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    bgr = inpaint_security_tags(bgr, tag_boxes)
    return to_jpeg_base64(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)), quality=95)


def inpaint_security_tags(img_bgr, tag_boxes):
    """Giysi uzerindeki magazaya ait guvenlik etiketlerini ve alarm pinlerini
    OpenCV Telea inpainting algoritmasi ile cevre kumas dokusuna gore siler.

    Args:
        img_bgr: numpy array (BGR, uint8)
        tag_boxes: list of bounding boxes: [ymin, xmin, ymax, xmax] veya {'box_2d': [...]}
    Returns:
        numpy array (BGR, uint8) — etiketler silinmis gorsel
    """
    if cv2 is None or not tag_boxes:
        return img_bgr

    h, w = img_bgr.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    tags_found = 0

    for item in tag_boxes:
        box = item.get('box_2d') if isinstance(item, dict) else item
        if not box or len(box) < 4:
            continue
        if isinstance(item, dict) and item.get('label') == 'design_label':
            continue  # ürünün kendi tasarım etiketi
        # Düşük güvenli tespitleri atla (yanlış pozitif = kumaşta leke)
        if isinstance(item, dict) and item.get('confidence') is not None:
            try:
                if float(item['confidence']) < MIN_TAG_CONFIDENCE:
                    continue
            except (TypeError, ValueError):
                pass

        try:
            ymin, xmin, ymax, xmax = float(box[0]), float(box[1]), float(box[2]), float(box[3])
        except (ValueError, TypeError):
            continue

        # Gemini 0..1000 normalize koordinatlarini 0.0..1.0 araligina cevir
        if max(ymin, xmin, ymax, xmax) > 1.0:
            ymin, xmin, ymax, xmax = ymin / 1000.0, xmin / 1000.0, ymax / 1000.0, xmax / 1000.0

        # Piksel koordinatlarina donustur
        px1 = max(0, int(xmin * w))
        py1 = max(0, int(ymin * h))
        px2 = min(w, int(xmax * w))
        py2 = min(h, int(ymax * h))

        if px2 <= px1 or py2 <= py1:
            continue
        # Görselin büyük bölümünü kaplayan kutu etiket değildir (ör. cep, logo);
        # inpaint geniş desenli alanı bulanık lekeye çevirir
        if isinstance(item, dict) and item.get('label') in NON_ERASE_LABELS:
            continue
        if (px2 - px1) * (py2 - py1) > MAX_TAG_AREA_RATIO * w * h:
            _logger.info('Inpaint: aşırı büyük etiket kutusu atlandı (%dx%d)', px2 - px1, py2 - py1)
            continue

        # Etiketin/pinin metal/plastik ve kağıt kenarlarını tam kapsamak için %20 padding ekle
        bw = px2 - px1
        bh = py2 - py1
        pad_x = max(6, int(bw * 0.20))
        pad_y = max(6, int(bh * 0.20))

        x1 = max(0, px1 - pad_x)
        y1 = max(0, py1 - pad_y)
        x2 = min(w, px2 + pad_x)
        y2 = min(h, py2 + pad_y)

        # Mağaza etiketleri ve alarmlar dikdörtgen veya oval olabilir.
        # Köşelerin açıkta kalıp beyaz rozet/etiket olarak halüsinasyon yapmasını önlemek için
        # maskeyi tam kapsayıcı dikdörtgen olarak çiziyoruz.
        cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
        tags_found += 1

    # Etiketin değdiği ürün detayları (fermuar ucu, düğme, logo) silinmez
    for item in tag_boxes:
        for x1, y1, x2, y2 in protect_box_pixels(item, w, h):
            cv2.rectangle(mask, (x1, y1), (x2, y2), 0, -1)

    if tags_found > 0:
        _logger.info('OpenCV inpainting: %d adet guvenlik/alarm etiketi gorselden siliniyor...', tags_found)
        try:
            # Telea inpaint kumas dokusunu puruzsuz harmanlar
            return cv2.inpaint(img_bgr, mask, inpaintRadius=7, flags=cv2.INPAINT_TELEA)
        except Exception as e:
            _logger.warning('Guvenlik etiketi inpaint hatasi: %s', e)

    return img_bgr


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
# 7. WebP & JPEG Cikti
# ---------------------------------------------------------------------------
def to_webp_base64(pil_image, quality=92):
    """PIL Image'i WebP base64 string'e donusturur.
    Eger Pillow WebP destegi yoksa JPEG'e duser.

    Args:
        pil_image: PIL Image (RGB veya RGBA)
        quality: WebP kalite (92 = yuksek/kayipsiz hissi)
    Returns:
        str — base64 encoded WebP (veya JPEG fallback)
    """
    if Image is None:
        return None

    buf = io.BytesIO()
    # WebP desteği kontrolü
    try:
        pil_image.save(buf, format='WEBP', quality=quality, method=4)
        _logger.debug('WebP cikti basarili: %d KB', len(buf.getvalue()) // 1024)
    except (KeyError, OSError) as e:
        _logger.warning('Pillow WebP destegi yok, JPEG fallback kullaniliyor: %s', e)
        buf = io.BytesIO()
        rgb_img = pil_image.convert('RGB') if pil_image.mode != 'RGB' else pil_image
        rgb_img.save(buf, format='JPEG', quality=95, optimize=True)
    return base64.b64encode(buf.getvalue()).decode('ascii')


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

def preprocess_garment_image(image_base64, target_long_edge=1600,
                              apply_white_balance=False,
                              apply_exposure_norm=True,
                              apply_noise_reduction=False,
                              apply_sharpening=True,
                              security_tags=None):
    """Urun gorselini FASHN/fal.ai API'ye gondermeden once profesyonel sekilde hazirlar.

    Adimlar:
    0. Guvenlik etiketi / alarm pini silme (OpenCV Telea inpaint)
    1. Beyaz denge (Gray-World) — renk kaymasini duzeltir
    2. Pozlama normalizasyonu (CLAHE) — karanlik/parlak duzeltir
    3. Gurultu azaltma (bilateral) — telefon gurultusunu temizler
    4. Akilli boyutlandirma (Lanczos) — detay korunur
    5. RGBA -> RGB (beyaz zemin) — FASHN uyumlulugu
    6. Keskinlestirme (unsharp mask) — resize sonrasi netlik
    7. JPEG %95 kalite cikti

    Args:
        image_base64: str — base64 encoded gorsel
        target_long_edge: int — hedef boyut (864 = FASHN v1.6 optimal, 1200 = fal.ai)
        apply_white_balance: bool — beyaz denge uygulansin mi
        apply_exposure_norm: bool — pozlama normalizasyonu uygulansin mi
        apply_noise_reduction: bool — gurultu azaltma uygulansin mi
        apply_sharpening: bool — keskinlestirme uygulansin mi
        security_tags: list — Gemini tarafindan tespit edilen guvenlik etiketi/alarm koordinatlari

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

        # --- OpenCV adimlari (0-3: Alarm silme, Beyaz denge, Pozlama, Gurultu) ---
        if cv2 is not None and (apply_white_balance or apply_exposure_norm or apply_noise_reduction or security_tags):
            # PIL -> numpy (BGR)
            rgb_array = np.array(rgba_to_rgb_white(pil_image) if had_alpha else pil_image.convert('RGB'))
            bgr_array = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)

            # 0. Guvenlik etiketi / Alarm pini silme
            if security_tags:
                bgr_array = inpaint_security_tags(bgr_array, security_tags)
                steps_applied.append('alarm_inpaint')

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

        # 7. Cikti (WebP: Fal CDN ve GPU transferinde %80-90 daha hafif ve hızlı)
        result_b64 = to_webp_base64(pil_image, quality=95)
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
