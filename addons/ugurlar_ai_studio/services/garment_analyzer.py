"""AI gorsel analiz servisi — kiyafet analizi ve prompt olusturma.

SaaS ai-fashion-studio/services/geminiService.ts'den uyarlanmistir.
fal.ai any-llm + vision API kullanir.
"""
import json
import logging

_logger = logging.getLogger(__name__)

try:
    import fal_client
except ImportError:
    fal_client = None

try:
    import requests
except ImportError:
    requests = None


def _prepare_gemini_image(image_url):
    """Gorseli Gemini inlineData formatina hazirlar.

    Returns:
        tuple: (mime_type, base64_data)
    """
    if not image_url:
        return None, None

    import base64
    # Case 1: Data URI
    if image_url.startswith('data:'):
        try:
            mime_part, base64_part = image_url.split(';base64,', 1)
            mime_type = mime_part.replace('data:', '')
            return mime_type, base64_part
        except Exception:
            pass

    # Case 2: Public URL / Local URL
    if image_url.startswith('http://') or image_url.startswith('https://'):
        try:
            if not requests:
                _logger.warning('requests kütüphanesi yüklü değil, görsel indirilemedi')
                return None, None
            resp = requests.get(image_url, timeout=30)
            resp.raise_for_status()
            mime_type = resp.headers.get('Content-Type', 'image/jpeg')
            base64_data = base64.b64encode(resp.content).decode('utf-8')
            return mime_type, base64_data
        except Exception as e:
            _logger.error('Failed to download image for Gemini: %s', e)
            return None, None

    # Case 3: Raw base64 string
    try:
        base64.b64decode(image_url)
        return 'image/jpeg', image_url
    except Exception:
        pass

    return None, None


def analyze_garment(api_key, image_url, gemini_api_key=None):
    """Kiyafet gorseli analiz et — tur, renk, kumas, detaylar.

    Gemini API anahtarı verilmişse doğrudan Google Gemini API kullanılır.
    Aksi halde fal.ai proxy/any-llm kullanılır.

    Args:
        api_key: fal.ai API anahtari (fallback/any-llm için)
        image_url: Analiz edilecek gorsel URL'si veya base64 verisi
        gemini_api_key: Google Gemini API anahtarı (varsa doğrudan kullanım için)

    Returns:
        dict: Analiz sonuclari
    """
    prompt = """You are a senior Fashion Merchandiser analyzing a product image.

Analyze the garment and return a JSON with these fields:
{
  "garmentType": "string — type (e.g., T-Shirt, Gömlek, Pantolon, Elbise, Kazak, Ceket, Etek)",
  "clothingCategory": "string — tops/bottoms/dress/outerwear/knitwear",
  "primaryColor": "string — dominant color (e.g., Siyah, Beyaz, Lacivert, Kirmizi)",
  "colorHex": "string — approximate hex code (e.g., #1a1a2e)",
  "secondaryColors": ["array of other colors present"],
  "fabricType": "string — fabric (e.g., Pamuk, Polyester, Keten, Denim, Triko, Saten)",
  "pattern": "string — pattern (e.g., Duz, Cizgili, Kareli, Cicekli, Baskili)",
  "style": "string — style (e.g., Casual, Formal, Sporcu, Elegance)",
  "fitDetails": "string — fit description (e.g., Regular Fit, Slim Fit, Oversize)",
  "collarType": "string — collar/neckline if visible",
  "sleeveType": "string — sleeve type if visible",
  "closureType": "string — closure type (Dugme, Fermuar, Yok)",
  "buttonCount": "number or null",
  "hasGraphic": "boolean — has print/graphic",
  "graphicDescription": "string — describe any print/graphic",
  "garmentLength": "string — mini/midi/maxi/standard",
  "hemline": "string — hem description",
  "seoTitle": "string — SEO optimized Turkish title",
  "seoDescription": "string — SEO optimized Turkish description (50-100 words)"
}

Return ONLY valid JSON, no markdown."""

    if gemini_api_key:
        _logger.info('Google Gemini API kullanılarak doğrudan kiyafet analizi yapılıyor...')
        mime_type, base64_data = _prepare_gemini_image(image_url)
        if mime_type and base64_data:
            model = "gemini-2.5-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_api_key}"
            
            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": base64_data
                            }
                        }
                    ]
                }],
                "generationConfig": {
                    "responseMimeType": "application/json"
                }
            }
            
            try:
                if not requests:
                    raise RuntimeError("requests paketi kurulu değil.")
                
                headers = {'Content-Type': 'application/json'}
                resp = requests.post(url, json=payload, headers=headers, timeout=45)
                resp.raise_for_status()
                res_data = resp.json()
                
                candidates = res_data.get('candidates', [])
                if candidates:
                    text = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', '')
                    if text:
                        text = text.strip()
                        # Clean markdown formatting if present
                        if text.startswith('```json'):
                            text = text[7:]
                        if text.endswith('```'):
                            text = text[:-3]
                        text = text.strip()
                        return json.loads(text)
            except Exception as e:
                _logger.exception('Direct Gemini API hatası, fal.ai fallback denenecek: %s', e)
        else:
            _logger.warning('Görsel Gemini API için hazırlanamadı, fal.ai fallback denenecek')

    # Fallback to fal.ai if gemini fails or isn't provided
    if api_key:
        return _analyze_via_fal(api_key, image_url, prompt)

    return _default_analysis()


def _analyze_via_fal(api_key, image_url, prompt):
    """fal.ai any-llm kullanarak kiyafet analizi yap."""
    if not fal_client:
        _logger.warning('fal_client kurulu degil, analiz yapilamadi')
        return _default_analysis()

    import os
    os.environ['FAL_KEY'] = api_key

    try:
        result = fal_client.subscribe(
            'fal-ai/any-llm',
            arguments={
                'prompt': prompt,
                'model': 'google/gemini-2.5-flash',
                'image_url': image_url,
                'max_tokens': 4096,
            },
            client_timeout=60,
        )

        output = result.get('output', '') if isinstance(result, dict) else ''
        if not output and hasattr(result, 'data'):
            output = result.data.get('output', '')

        # JSON cikar
        json_match = None
        if '```json' in output:
            start = output.index('```json') + 7
            end = output.index('```', start)
            json_match = output[start:end].strip()
        elif '{' in output:
            start = output.index('{')
            end = output.rindex('}') + 1
            json_match = output[start:end]

        if json_match:
            return json.loads(json_match)

    except Exception as e:
        _logger.exception('fal.ai kiyafet analizi hatasi: %s', e)

    return _default_analysis()


def build_generation_prompt(analysis, preset, prompt_locks, extra_prompt='',
                            photo_type='front'):
    """Analiz sonuclarina gore AI gorsel uretim promptu olustur.

    Her photo_type icin ozellestirilmis prompt uretir:
    - front: Modelin one bakis, tam vucut, on yuzu gorunen cekimi
    - back: Modelin arkaya donuk, arkasi gorunen cekimi
    - side: 3/4 aci, profil gorunen cekimi
    - detail: Yakin cekim, kumas/dikus/detay gorunen cekimi

    Args:
        analysis: Kiyafet analiz sonuclari (dict)
        preset: Manken preset bilgileri (dict)
        prompt_locks: Aktif prompt lock listesi (list of str)
        extra_prompt: Ek kullanici promptu
        photo_type: str — 'front', 'back', 'side', 'detail'

    Returns:
        dict: {'positive': str, 'negative': str}
    """
    garment_type = analysis.get('garmentType', 'garment')
    color = analysis.get('primaryColor', '')
    fabric = analysis.get('fabricType', '')
    pattern = analysis.get('pattern', 'Duz')
    style = analysis.get('style', 'Casual')
    fit = analysis.get('fitDetails', 'Regular Fit')
    collar = analysis.get('collarType', '')
    sleeve = analysis.get('sleeveType', '')

    # ═══ VIEW-SPESIFIK BAZ PROMPT ═══
    view_base = _VIEW_PROMPT_TEMPLATES.get(photo_type, _VIEW_PROMPT_TEMPLATES['front'])
    base_prompt = view_base.format(
        garment_type=garment_type,
        color=color,
        fabric=fabric,
        pattern=pattern,
        style=style,
        fit=fit,
    )

    if collar:
        base_prompt += f"Collar: {collar}. "
    if sleeve:
        base_prompt += f"Sleeves: {sleeve}. "

    # ═══ BASKI / GRAFIK KORUMA TALIMATLARI ═══
    has_graphic = analysis.get('hasGraphic', False)
    graphic_desc = analysis.get('graphicDescription', '')
    if has_graphic and graphic_desc:
        base_prompt += (
            f"CRITICAL GARMENT DETAIL PRESERVATION: "
            f"This garment has a graphic print/design described as: "
            f"'{graphic_desc}'. "
            f"The print MUST be preserved EXACTLY as shown in the input image — "
            f"same position, same colors, same proportions. "
            f"Do NOT alter, simplify, remove, or reinterpret ANY part of the design. "
        )
    elif has_graphic:
        base_prompt += (
            "CRITICAL: This garment has a graphic print/design. "
            "Preserve the print EXACTLY as shown in the input — "
            "same position, same colors, same proportions. "
            "Do NOT alter or remove any part of the design. "
        )

    # Preset bilgileri
    if preset:
        gender = preset.get('gender', 'female')
        body = preset.get('body_type', 'average')
        audience = preset.get('target_audience', '')
        base_prompt += (
            f"Model: {gender}, {body} body type. "
        )
        if audience:
            base_prompt += f"Target audience: {audience}. "

    # Prompt lock'lari ekle
    for lock in prompt_locks:
        base_prompt += f" {lock}"

    # Kullanici ek promptu
    if extra_prompt:
        base_prompt += f" ADDITIONAL USER DIRECTIVE: {extra_prompt}"

    # View-spesifik negatif prompt
    negative = _VIEW_NEGATIVE_PROMPTS.get(photo_type, _VIEW_NEGATIVE_PROMPTS['front'])

    _logger.info(
        'Prompt olusturuldu (photo_type=%s, hasGraphic=%s): %d karakter',
        photo_type, has_graphic, len(base_prompt),
    )

    return {
        'positive': base_prompt,
        'negative': negative,
    }


# ═══════════════════════════════════════════════════════════════════════════
# VIEW-SPESIFIK PROMPT SABLONLARI
# ═══════════════════════════════════════════════════════════════════════════

_VIEW_PROMPT_TEMPLATES = {
    'front': (
        "Professional e-commerce FRONT VIEW fashion photography. "
        "Full-body shot of a model facing directly toward the camera. "
        "The FRONT of the {color} {fabric} {garment_type} is fully visible. "
        "Clean white/light studio background. Even, shadow-free lighting. "
        "Style: {style}, Fit: {fit}. Pattern: {pattern}. "
        "Natural standing pose with arms relaxed at sides. "
        "Sharp focus on garment details, fabric texture, and construction. "
    ),
    'back': (
        "Professional e-commerce BACK VIEW fashion photography. "
        "Full-body shot of a model facing AWAY from the camera, showing their back. "
        "The BACK of the {color} {fabric} {garment_type} is fully visible. "
        "Clean white/light studio background. Even, shadow-free lighting. "
        "Style: {style}, Fit: {fit}. Pattern: {pattern}. "
        "Natural standing pose showing the rear construction and fit. "
        "Sharp focus on back details, seams, and garment shape. "
    ),
    'side': (
        "Professional e-commerce SIDE/THREE-QUARTER VIEW fashion photography. "
        "Full-body shot of a model turned approximately 45 degrees, showing profile. "
        "The SIDE PROFILE of the {color} {fabric} {garment_type} is visible. "
        "Clean white/light studio background. Even, shadow-free lighting. "
        "Style: {style}, Fit: {fit}. Pattern: {pattern}. "
        "Natural three-quarter pose showing garment drape and silhouette. "
        "Sharp focus on garment side profile and fit on body. "
    ),
    'detail': (
        "Professional CLOSE-UP DETAIL fashion photography. "
        "Macro shot showing the fine details of the {color} {fabric} {garment_type}. "
        "Focus on fabric texture, stitching quality, button/zipper details, and material. "
        "Pattern: {pattern}. "
        "Extreme sharp focus, studio macro lighting. "
        "Show the craftsmanship and material quality. "
    ),
}

_VIEW_NEGATIVE_PROMPTS = {
    'front': (
        "extra arms, extra legs, extra fingers, duplicated face, double head, "
        "ghosting limbs, warped anatomy, deformed body, mannequin, doll, "
        "plastic/waxy/porcelain skin, CGI look, beauty filter, airbrushed, "
        "blurry, low quality, collage, split screen, multi-panel, "
        "studio equipment, softbox, light stand, flash head, "
        "altered garment design, changed collar, wrong garment color, "
        "wrong fabric texture, wrong button style, modified print, "
        "different pattern, altered graphic, changed logo, "
        "bare midriff, bare chest, nude model, "
        "back view, rear view, side view, profile view"
    ),
    'back': (
        "extra arms, extra legs, extra fingers, duplicated face, double head, "
        "ghosting limbs, warped anatomy, deformed body, mannequin, doll, "
        "plastic/waxy/porcelain skin, CGI look, beauty filter, airbrushed, "
        "blurry, low quality, collage, split screen, multi-panel, "
        "studio equipment, softbox, light stand, flash head, "
        "altered garment design, wrong garment color, wrong fabric texture, "
        "front view, facing camera, face visible, "
        "bare midriff, bare chest, nude model"
    ),
    'side': (
        "extra arms, extra legs, extra fingers, duplicated face, double head, "
        "ghosting limbs, warped anatomy, deformed body, mannequin, doll, "
        "plastic/waxy/porcelain skin, CGI look, beauty filter, airbrushed, "
        "blurry, low quality, collage, split screen, multi-panel, "
        "studio equipment, softbox, light stand, flash head, "
        "altered garment design, wrong garment color, wrong fabric texture, "
        "bare midriff, bare chest, nude model"
    ),
    'detail': (
        "full body shot, wide angle, person visible, face visible, "
        "blurry, low quality, out of focus, "
        "altered garment design, wrong garment color, wrong fabric texture, "
        "modified print, different pattern, altered graphic"
    ),
}


def _default_analysis():
    """Analiz yapilamadiysa varsayilan dondurulen degerler."""
    return {
        'garmentType': 'Kiyafet',
        'clothingCategory': 'tops',
        'primaryColor': '',
        'colorHex': '#000000',
        'secondaryColors': [],
        'fabricType': '',
        'pattern': 'Duz',
        'style': 'Casual',
        'fitDetails': 'Regular Fit',
        'collarType': '',
        'sleeveType': '',
        'closureType': '',
        'buttonCount': None,
        'hasGraphic': False,
        'graphicDescription': '',
        'garmentLength': 'standard',
        'hemline': '',
        'seoTitle': '',
        'seoDescription': '',
    }


# =========================================================================
# FASHN API Category Mapping
# =========================================================================

# Kiyafet turunun FASHN API category parametresine donusumu
_FASHN_CATEGORY_MAP = {
    # clothingCategory -> FASHN category
    'tops': 'tops',
    'bottoms': 'bottoms',
    'dress': 'full-body',
    'outerwear': 'tops',
    'knitwear': 'tops',
    'one_piece': 'full-body',
    'full-body': 'full-body',
}

# Detayli garmentType -> FASHN category mapping (fallback)
_GARMENT_TYPE_MAP = {
    # Ust giyim
    't-shirt': 'tops', 'tisort': 'tops', 'gomlek': 'tops',
    'bluz': 'tops', 'kazak': 'tops', 'hirka': 'tops',
    'ceket': 'tops', 'mont': 'tops', 'yelek': 'tops',
    'sweatshirt': 'tops', 'hoodie': 'tops', 'polo': 'tops',
    'atlet': 'tops', 'tank top': 'tops', 'crop top': 'tops',
    'shirt': 'tops', 'blouse': 'tops', 'jacket': 'tops',
    'coat': 'tops', 'sweater': 'tops', 'cardigan': 'tops',
    'vest': 'tops', 'top': 'tops',
    # Alt giyim
    'pantolon': 'bottoms', 'sort': 'bottoms', 'etek': 'bottoms',
    'jean': 'bottoms', 'denim': 'bottoms', 'tayt': 'bottoms',
    'esofman alti': 'bottoms',
    'pants': 'bottoms', 'trousers': 'bottoms', 'shorts': 'bottoms',
    'skirt': 'bottoms', 'jeans': 'bottoms', 'leggings': 'bottoms',
    # Tam vucut
    'elbise': 'full-body', 'tulum': 'full-body', 'overall': 'full-body',
    'dress': 'full-body', 'jumpsuit': 'full-body', 'romper': 'full-body',
    'gown': 'full-body', 'abiye': 'full-body',
}


def map_to_fashn_category(analysis):
    """Kiyafet analizinden FASHN API category parametresini belirle.

    Oncelik sirasi:
    1. clothingCategory (genel kategori) — en guvenilir
    2. garmentType (detayli tur) — fallback
    3. 'tops' — son care

    Args:
        analysis: dict — analyze_garment() ciktisi

    Returns:
        str: FASHN category ('tops', 'bottoms', 'full-body')
    """
    # 1. clothingCategory ile eslestir
    clothing_cat = (analysis.get('clothingCategory') or '').lower().strip()
    if clothing_cat in _FASHN_CATEGORY_MAP:
        result = _FASHN_CATEGORY_MAP[clothing_cat]
        _logger.info('FASHN category (clothingCategory): %s -> %s', clothing_cat, result)
        return result

    # 2. garmentType ile eslestir
    garment_type = (analysis.get('garmentType') or '').lower().strip()
    for key, cat in _GARMENT_TYPE_MAP.items():
        if key in garment_type:
            _logger.info('FASHN category (garmentType): %s -> %s', garment_type, cat)
            return cat

    # 3. Varsayilan
    _logger.info('FASHN category: varsayilan tops kullaniliyor')
    return 'tops'
