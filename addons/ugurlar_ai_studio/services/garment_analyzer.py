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


def analyze_garment(api_key, image_url):
    """Kiyafet gorseli analiz et — tur, renk, kumas, detaylar.

    Args:
        api_key: fal.ai API anahtari
        image_url: Analiz edilecek gorsel URL'si

    Returns:
        dict: Analiz sonuclari
    """
    if not fal_client:
        _logger.warning('fal_client kurulu degil, analiz yapilamadi')
        return _default_analysis()

    import os
    os.environ['FAL_KEY'] = api_key

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
        _logger.exception('Kiyafet analizi hatasi: %s', e)

    return _default_analysis()


def build_generation_prompt(analysis, preset, prompt_locks, extra_prompt=''):
    """Analiz sonuclarina gore AI gorsel uretim promptu olustur.

    Args:
        analysis: Kiyafet analiz sonuclari (dict)
        preset: Manken preset bilgileri (dict)
        prompt_locks: Aktif prompt lock listesi (list of str)
        extra_prompt: Ek kullanici promptu

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

    # Ana prompt
    base_prompt = (
        f"Professional e-commerce fashion photography. "
        f"A model wearing a {color} {fabric} {garment_type}. "
        f"Style: {style}, Fit: {fit}. "
        f"Pattern: {pattern}. "
    )

    if collar:
        base_prompt += f"Collar: {collar}. "
    if sleeve:
        base_prompt += f"Sleeves: {sleeve}. "

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

    # Negatif prompt
    negative = (
        "extra arms, extra legs, extra fingers, duplicated face, double head, "
        "ghosting limbs, warped anatomy, deformed body, mannequin, doll, "
        "plastic/waxy/porcelain skin, CGI look, beauty filter, airbrushed, "
        "blurry, low quality, collage, split screen, multi-panel, "
        "studio equipment, softbox, light stand, flash head, "
        "altered garment design, changed collar, wrong garment color, "
        "wrong fabric texture, wrong button style, "
        "bare midriff, bare chest, nude model"
    )

    return {
        'positive': base_prompt,
        'negative': negative,
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
