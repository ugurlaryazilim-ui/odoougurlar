"""AI gorsel analiz servisi — kiyafet analizi ve prompt olusturma.

SaaS ai-fashion-studio/services/geminiService.ts'den uyarlanmistir.
fal.ai any-llm + vision API kullanir.

PROMPT KONFİGÜRASYONU:
    Ana analiz prompt'ı: GARMENT_ANALYSIS_PROMPT (aşağıda tanımlı)
    Görüş açısı prompt'ları: _VIEW_PROMPT_TEMPLATES, _VIEW_NEGATIVE_PROMPTS
    Bu constant'ları değiştirerek AI davranışını özelleştirebilirsiniz.
    Gelecekte ir.config_parameter'a taşınabilir.
"""
import json
import logging

_logger = logging.getLogger(__name__)

# ═══ Türkçe Substring Tuzağı Koruması ═══
# "tişört" içinde "şort", "tisort" içinde "sort" gibi false positive'leri önler.
_FALSE_POSITIVE_CLEAN = {
    'şort': ['tişört', 'tısört'],
    'sort': ['tisort', 'tısort', 'tshirt'],
}


def _safe_keyword_match(text, keywords):
    """Substring tuzaklarını engelleyen güvenli kelime eşleme.

    Türkçe'de 'tişört' kelimesinin içinde 'şort' alt dizgisi bulunur.
    Basit `in` operatörü ile kontrol edildiğinde tişört yanlışlıkla
    şort olarak sınıflandırılır. Bu fonksiyon bilinen false positive'leri
    metinden temizleyerek güvenli eşleme yapar.

    Args:
        text: Aranacak metin (lowercase)
        keywords: Aranacak anahtar kelimeler listesi

    Returns:
        bool: Herhangi bir kelime güvenli şekilde eşleşirse True
    """
    text_lower = text.lower()
    for kw in keywords:
        clean_text = text_lower
        for fp in _FALSE_POSITIVE_CLEAN.get(kw, []):
            clean_text = clean_text.replace(fp, '')
        if kw in clean_text:
            return True
    return False

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

    # Odoo Binary alanları bytes döner, str'ye çevir
    if isinstance(image_url, bytes):
        image_url = image_url.decode('utf-8')

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


def analyze_garment(api_key, image_url, gemini_api_key=None, product_context=None):
    """Kiyafet gorseli analiz et — tur, renk, kumas, detaylar.

    Gemini API anahtarı verilmişse doğrudan Google Gemini API kullanılır.
    Aksi halde fal.ai proxy/any-llm kullanılır.

    Args:
        api_key: fal.ai API anahtari (fallback/any-llm için)
        image_url: Analiz edilecek gorsel URL'si veya base64 verisi
        gemini_api_key: Google Gemini API anahtarı (varsa doğrudan kullanım için)
        product_context: Ürün adı, kodu, kategorisi ve nitelikleri (Odoo ERP'den)

    Returns:
        dict: Analiz sonuclari
    """
    context_section = ""
    if product_context:
        context_section = f"""
OFFICIAL ERP / STORE PRODUCT INFORMATION (GROUND TRUTH):
"{product_context}"
Use this official product metadata as definitive context:
- If product name/category indicates Manto, Kaban, Palto, Mont, Ceket, Blazer, Trençkot, Pardösü, Cardigan, Hırka, Kazak, Bluz, Gömlek, Tişört, Tunik: clothingCategory MUST be 'outerwear' or 'tops' (NEVER 'dress' and NEVER 'bottoms')! Even if long or belted, it is worn OVER pants/trousers, NOT as a dress.
- If product name/category indicates Etek, Şort, Pantolon, Jean, Tayt: clothingCategory MUST be 'bottoms'!
- If product name/category indicates Elbise, Abiye, Tulum: clothingCategory MUST be 'dress'!
"""

    prompt = f"""You are a senior Fashion Merchandiser analyzing a product image.
Ignore any hangers, clips, hands, or mannequins holding the garment. Focus ONLY on the garment's actual design.
{context_section}
CRITICAL SECURITY ALARM & STORE TAG INSTRUCTION:
1. Retail garments frequently have store security alarm tags, anti-theft sensors, magnetic alarm pins, or round metal/plastic security tags pinned to the waistband, collar, pocket, or hemline.
2. DO NOT describe security tags as part of the garment's design.
3. DO NOT mistake any security alarm pin, sensor tag, or retail clip for a garment button, rivet, snap, or fastener! If an elastic waistband garment (or pants without a front fly button) has a metallic/plastic pin attached, closureType MUST be 'Yok' and buttonCount MUST be null.
4. DETECT ALL SECURITY TAGS: In the "securityTags" field, locate and return the 2D bounding boxes of ALL visible store security tags, alarm sensors, metallic alarm pins, or plastic EAS hard tags in normalized coordinates [ymin, xmin, ymax, xmax] on a scale of 0 to 1000. If there are no security tags or alarms visible, return an empty array [].

CRITICAL NECKLINE INSTRUCTION: If the garment is hanging on a hanger, the front collar often drops down, revealing the INSIDE of the BACK panel (inner back lining, back collar label, or back keyhole). You MUST completely IGNORE anything visible through the neck hole. Do NOT describe the inner back lining as part of the front collar. If you see a keyhole or label through the neck opening, do NOT say the garment has a keyhole collar. Assume a clean, standard front neckline.

CRITICAL CATEGORY INSTRUCTION:
- If the garment is an etek (skirt), mini skirt, A-line skirt, pleated skirt, pencil skirt, şort (shorts), or pants/trousers: clothingCategory MUST be 'bottoms' (NEVER tops, NEVER outerwear)!
- If the garment is an elbise (dress), abiye, or jumpsuit: clothingCategory MUST be 'dress'!
- For coats, mantos, kabans, paltos, trench coats, parkas, jackets, blazers, mont, cardigans, sweaters, blouses, shirts, and t-shirts: clothingCategory MUST be 'outerwear' or 'tops'! DO NOT classify a coat, jacket, manto, or cardigan as a 'dress' even if it reaches mid-thigh or has a belt!
- For skirts and dresses: garmentLength MUST accurately specify 'mini', 'midi', or 'maxi'.

Analyze the garment and return a JSON with these fields:
{
  "garmentType": "string — type (e.g., T-Shirt, Gömlek, Pantolon, Elbise, Kazak, Ceket, Etek, Mini Etek)",
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
  "seoDescription": "string — SEO optimized Turkish description (50-100 words)",
  "recommendedBottoms": "string — Describe in English the most matching pants/trousers/jeans style and color to build a stylish outfit with this product (e.g. 'dark blue slim-fit denim jeans', 'beige tailored cotton trousers', 'black cargo pants')",
  "recommendedShoes": "string — Describe in English the most matching shoes style and color for this outfit (e.g. 'clean white minimalist leather sneakers', 'brown leather loafers', 'black high-top boots')",
  "waistbandType": "string — for bottoms: smooth/flat, belted, elasticated, drawstring. For tops: null",
  "hasBeltLoops": "boolean — true ONLY if belt loops are clearly visible on the garment",
  "structuralDetails": "string — describe visible structural elements: pleats, darts, pintucks, piping",
  "securityTags": [
    {
      "box_2d": [100, 200, 150, 250],
      "label": "alarm_pin"
    }
  ]
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
                        parsed = json.loads(text)
                        if isinstance(parsed, dict):
                            return parsed
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

    # Odoo Binary alanları bytes döner, str'ye çevir (JSON serialization için)
    if isinstance(image_url, bytes):
        image_url = image_url.decode('utf-8')

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
            parsed = json.loads(json_match)
            if isinstance(parsed, dict):
                return parsed

    except Exception as e:
        _logger.exception('fal.ai kiyafet analizi hatasi: %s', e)

    return _default_analysis()


def analyze_outfit_consistency(image_data, api_key=None, gemini_api_key=None, category='tops'):
    """Front try-on sonucundaki TUM kıyafet detaylarını analiz et.

    Cross-view tutarlılık için: front sonucundaki pantolon, ayakkabı,
    saç stili gibi detayları çıkarır, back/side promptlarına enjekte edilir.

    Args:
        image_data: Front try-on sonucu (base64 veya URL)
        api_key: fal.ai API anahtarı (fallback)
        gemini_api_key: Gemini API anahtarı
        category: Değiştirilen kıyafetin kategorisi ('tops', 'bottoms', 'one-piece')

    Returns:
        dict: Çıkarılan analiz ve 'fullOutfitPrompt'
    """
    if category == 'bottoms':
        except_clause = "EXCEPT for the main BOTTOM garment (pants/jeans/skirt) which will be changed in other views."
    elif category == 'one-piece' or category == 'one_piece':
        except_clause = "EXCEPT for the main ONE-PIECE garment (dress/jumpsuit) which will be changed in other views."
    else:
        except_clause = "EXCEPT for the main TOP garment (shirt/t-shirt/jacket) which will be changed in other views."

    prompt = f"""You are analyzing a fashion model photograph for OUTFIT CONSISTENCY.
Your job is to describe EVERYTHING the model is wearing and their appearance,
{except_clause}

Analyze and return JSON:
{{
  "topsType": "string — top garment type (e.g., 'white cotton t-shirt', 'black hoodie'). Leave empty if analyzing a one-piece or if it's the target top.",
  "topsColor": "string — top garment exact color",
  "bottomsType": "string — pants/jeans/skirt/shorts type (e.g., 'slim-fit white trousers', 'dark blue skinny jeans'). Leave empty if it's the target bottom.",
  "bottomsColor": "string — bottom garment exact color",
  "shoesType": "string — shoe type (e.g., 'white low-top sneakers', 'black ankle boots', 'beige heels')",
  "shoesColor": "string — shoe color",
  "hairStyle": "string — hair description (e.g., 'long wavy blonde hair', 'short brown bob')",
  "hairColor": "string — hair color",
  "skinTone": "string — skin tone (e.g., 'fair/light', 'medium', 'olive', 'dark')",
  "accessories": "string — any visible accessories (watch, necklace, earrings, belt) or 'none'",
  "modelBuild": "string — body build (e.g., 'slim', 'athletic', 'curvy', 'standard')",
  "backgroundDescription": "string — background (e.g., 'clean white studio', 'light grey')"
}}

Return ONLY valid JSON, no markdown. Be VERY specific about colors and styles."""

    try:
        if gemini_api_key:
            mime_type, base64_data = _prepare_gemini_image(image_data)
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

                if requests:
                    headers = {'Content-Type': 'application/json'}
                    resp = requests.post(url, json=payload, headers=headers, timeout=30)
                    resp.raise_for_status()
                    res_data = resp.json()
                    candidates = res_data.get('candidates', [])
                    if candidates:
                        text = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', '')
                        if text:
                            text = text.strip()
                            if text.startswith('```json'):
                                text = text[7:]
                            if text.endswith('```'):
                                text = text[:-3]
                            outfit_data = json.loads(text.strip())
                            # fullOutfitPrompt oluştur
                            outfit_data['fullOutfitPrompt'] = _build_consistency_prompt(outfit_data)
                            _logger.info(
                                'Outfit tutarlılık analizi: %s %s, %s %s, saç=%s',
                                outfit_data.get('bottomsColor', '?'),
                                outfit_data.get('bottomsType', '?'),
                                outfit_data.get('shoesColor', '?'),
                                outfit_data.get('shoesType', '?'),
                                outfit_data.get('hairStyle', '?'),
                            )
                            return outfit_data

        # Fallback: fal.ai
        if api_key:
            result = _analyze_via_fal(api_key, image_data, prompt)
            if result and result != _default_analysis():
                result['fullOutfitPrompt'] = _build_consistency_prompt(result)
                return result

    except Exception as e:
        _logger.warning('Outfit tutarlılık analizi başarısız: %s', e)

    return {
        'fullOutfitPrompt': '',
        'bottomsType': '', 'bottomsColor': '',
        'shoesType': '', 'shoesColor': '',
        'hairStyle': '', 'hairColor': '',
        'skinTone': '', 'accessories': '',
    }


def _build_consistency_prompt(outfit_data):
    """Outfit verilerinden tutarlılık prompt cümlesi oluştur."""
    parts = []

    tops = outfit_data.get('topsType', '')
    tops_color = outfit_data.get('topsColor', '')
    if tops and tops_color:
        parts.append(f"{tops_color} {tops}")
    elif tops:
        parts.append(tops)

    bottoms = outfit_data.get('bottomsType', '')
    bottoms_color = outfit_data.get('bottomsColor', '')
    if bottoms and bottoms_color:
        parts.append(f"{bottoms_color} {bottoms}")
    elif bottoms:
        parts.append(bottoms)

    shoes = outfit_data.get('shoesType', '')
    shoes_color = outfit_data.get('shoesColor', '')
    if shoes and shoes_color:
        parts.append(f"{shoes_color} {shoes}")
    elif shoes:
        parts.append(shoes)

    hair = outfit_data.get('hairStyle', '')
    if hair:
        parts.append(f"hair: {hair}")

    skin = outfit_data.get('skinTone', '')
    if skin:
        parts.append(f"skin tone: {skin}")

    accessories = outfit_data.get('accessories', '')
    if accessories and accessories.lower() != 'none':
        parts.append(f"accessories: {accessories}")

    if not parts:
        return ''

    return (
        "ABSOLUTE PRIORITY — CROSS-VIEW OUTFIT CONSISTENCY LOCK: "
        "You MUST replicate the EXACT SAME complete outfit from the front view reference image. "
        "The model is wearing: "
        + ", ".join(parts) + ". "
        "Do NOT change, replace, or hallucinate ANY clothing item. "
        "The bottoms MUST be IDENTICAL — same color, same fabric, same fit, same style. "
        "The shoes MUST be IDENTICAL. The hair MUST be IDENTICAL. "
        "If the front view shows white pants, the side/back view MUST also show white pants — NOT jeans, NOT different color. "
        "Every view must look like the SAME photoshoot session with the SAME outfit. "
        "ANY outfit change between views is a CRITICAL FAILURE. "
    )


def build_generation_prompt(analysis, preset, prompt_locks, extra_prompt='',
                            photo_type='front', outfit_consistency=None, provider_type='fashn'):
    """Analiz sonuclarina gore AI gorsel uretim promptu olustur.

    Seedream v5 Pro icin kisa, kategori-bazli prompt sablonlari kullanir.
    Hedef: 40-65 kelime, < 500 karakter (Seedream optimal araliği).
    FASHN icin minimal prompt — kendi try-on modelini kullanir.

    Args:
        analysis: Kiyafet analiz sonuclari (dict)
        preset: Manken preset bilgileri (dict)
        prompt_locks: Aktif prompt lock listesi (list of str) — sadece kalite lock
        extra_prompt: Ek kullanici promptu
        photo_type: str — 'front', 'back', 'side', 'detail'
        outfit_consistency: dict — outfit tutarlilik verileri (back/side view icin)
        provider_type: str — 'fashn', 'fal', vb.

    Returns:
        dict: {'positive': str, 'negative': str}
    """
    from .category_constants import (
        SEEDREAM_TEMPLATES, SEEDREAM_DETAIL_TEMPLATE, SEEDREAM_NEGATIVES,
        LEG_RULES, HAND_POSES, QUALITY_SUFFIX,
        FASHN_VIEW_TEMPLATES, FASHN_NEGATIVE,
        TOPS_AND_OUTERWEAR_KW,
    )

    if not isinstance(analysis, dict):
        analysis = _default_analysis()
    if not isinstance(preset, dict):
        preset = {}
    if not isinstance(outfit_consistency, dict):
        outfit_consistency = {}

    category = analysis.get('clothingCategory', 'tops')
    garment_type = analysis.get('garmentType', 'garment')
    garment_type_lower = f"{garment_type} {category}".lower()

    # ═══ ALT TİP ALGILA (dress / skirt / shorts / tops / bottoms) ═══
    # ÖNCELİK: dress > skirt > shorts > tops/outerwear > bottoms
    # "Gömlek Elbise" gibi bileşik isimler dress olarak algılanmalı
    if category in ['dress', 'one_piece', 'one-piece', 'full-body'] or \
         _safe_keyword_match(garment_type_lower, ['elbise', 'dress', 'tulum', 'jumpsuit', 'abiye']):
        sub_type = 'dress'
    elif _safe_keyword_match(garment_type_lower, ['etek', 'skirt']):
        sub_type = 'skirt'
    elif _safe_keyword_match(garment_type_lower, ['şort', 'sort', 'shorts', 'bermuda']):
        sub_type = 'shorts'
    elif category in ['tops', 'outerwear', 'knitwear'] or \
         _safe_keyword_match(garment_type_lower, TOPS_AND_OUTERWEAR_KW):
        sub_type = 'tops'
    elif category == 'bottoms':
        sub_type = 'bottoms'
    else:
        sub_type = 'tops'  # Safe fallback

    # ═══ FASHN PROVIDER (minimal prompt, kendi try-on modeli) ═══
    if provider_type == 'fashn':
        base_prompt = FASHN_VIEW_TEMPLATES.get(photo_type, FASHN_VIEW_TEMPLATES['front'])
        negative = FASHN_NEGATIVE

        # Fashn icin outfit directive ve prompt locks
        if sub_type in ('dress', 'skirt', 'shorts'):
            base_prompt += " Natural bare legs below garment hemline."
        elif sub_type == 'tops':
            base_prompt += " Model wears full-length dark trousers."
        elif sub_type == 'bottoms':
            base_prompt += " Full trouser length visible to shoes."

        for lock in prompt_locks:
            lock_str = str(lock).strip()
            if not lock_str.upper().startswith('NEGATIVE'):
                base_prompt += f" {lock_str}"

        if extra_prompt:
            base_prompt += f" {extra_prompt}"

        _logger.info(
            'Prompt olusturuldu (photo_type=%s, provider=%s, sub_type=%s): %d karakter',
            photo_type, provider_type, sub_type, len(base_prompt),
        )
        return {'positive': base_prompt, 'negative': negative}

    # ═══ SEEDREAM / FAL PROVIDER (kategori-bazlı kısa template) ═══
    color = analysis.get('primaryColor', '')
    fabric = analysis.get('fabricType', '')
    garment_length = analysis.get('garmentLength', 'default') or 'default'

    # Bacak kuralı — uzunluğa göre
    leg_rules_for_type = LEG_RULES.get(sub_type, {})
    leg_rule = leg_rules_for_type.get(garment_length, leg_rules_for_type.get('default', ''))

    # El pozu
    hand_pose = HAND_POSES.get(photo_type, '')

    # Yaka/kol notu (kısa)
    collar_note = ''
    collar = analysis.get('collarType', '')
    sleeve = analysis.get('sleeveType', '')
    if collar and sub_type in ('tops', 'dress') and photo_type == 'front':
        collar_note = f"{collar} neckline. "
    if sleeve and sub_type in ('tops', 'dress') and photo_type == 'front':
        sleeve_lower = sleeve.lower()
        if any(k in sleeve_lower for k in ['strapless', 'askisiz', 'askısız', 'sleeveless', 'kolsuz']):
            collar_note += "Bare shoulders, strapless design. "
        elif any(k in sleeve_lower for k in ['ince askı', 'spaghetti', 'thin strap']):
            collar_note += "Thin spaghetti straps. "

    # Grafik/baskı notu
    graphic_note = ''
    if analysis.get('hasGraphic') and analysis.get('graphicDescription'):
        graphic_note = f"Preserve the graphic print: '{analysis['graphicDescription']}'. "
    elif analysis.get('hasGraphic'):
        graphic_note = "Preserve the graphic print exactly as in Figure 1. "

    # Extra prompt
    extra = ''
    if extra_prompt:
        extra = extra_prompt.strip()

    # ═══ TEMPLATE SEÇ VE FORMAT ET ═══
    if photo_type == 'detail':
        template = SEEDREAM_DETAIL_TEMPLATE
    else:
        template = SEEDREAM_TEMPLATES.get((sub_type, photo_type))
        if not template:
            # Fallback: front template
            template = SEEDREAM_TEMPLATES.get((sub_type, 'front'), SEEDREAM_TEMPLATES[('tops', 'front')])

    base_prompt = template.format(
        garment_type=garment_type,
        color=color,
        fabric=fabric,
        leg_rule=leg_rule,
        hand_pose=hand_pose,
        collar_note=collar_note,
        graphic_note=graphic_note,
        extra_prompt=extra,
    )

    # Kalite suffix ve tek prompt lock (fotorealizm)
    for lock in prompt_locks:
        lock_str = str(lock).strip()
        if not lock_str.upper().startswith('NEGATIVE'):
            base_prompt += f" {lock_str}"

    # Çift boşlukları temizle
    base_prompt = " ".join(base_prompt.split())

    # ═══ CROSS-VIEW OUTFIT TUTARLILIĞI ═══
    # Back/side view'da front view'daki outfit bilgisini kısa ekle
    if outfit_consistency and photo_type != 'front':
        consistency_data = outfit_consistency
        consistency_parts = []
        # Dress/etek ise pantolon bilgisi EKLEME — çünkü elbise bacak görünümünü değiştirir
        if sub_type not in ('dress', 'skirt', 'shorts'):
            bottoms_info = consistency_data.get('bottomsType', '')
            bottoms_color = consistency_data.get('bottomsColor', '')
            if bottoms_info:
                consistency_parts.append(f"{bottoms_color} {bottoms_info}".strip())
        shoes_info = consistency_data.get('shoesType', '')
        shoes_color = consistency_data.get('shoesColor', '')
        if shoes_info:
            consistency_parts.append(f"{shoes_color} {shoes_info}".strip())
        if consistency_parts:
            base_prompt += f" Same outfit as front view: {', '.join(consistency_parts)}."

    # ═══ NEGATİF PROMPT ═══
    negative = SEEDREAM_NEGATIVES.get(sub_type, SEEDREAM_NEGATIVES['tops'])

    # Scene negatif eklemeleri
    for lock in prompt_locks:
        lock_str = str(lock).strip()
        if lock_str.upper().startswith('NEGATIVE'):
            neg_content = lock_str[8:].lstrip(': ')
            if neg_content:
                negative = f"{negative}, {neg_content}"

    _logger.info(
        'Prompt olusturuldu (photo_type=%s, provider=%s, sub_type=%s): %d karakter, %d kelime',
        photo_type, provider_type, sub_type, len(base_prompt), len(base_prompt.split()),
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
        'recommendedBottoms': 'dark blue skinny jeans',
        'recommendedShoes': 'white sneakers',
        'securityTags': [],
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
    # Ust giyim / Dis giyim
    'manto': 'tops', 'kaban': 'tops', 'palto': 'tops', 'mont': 'tops',
    'ceket': 'tops', 'jacket': 'tops', 'coat': 'tops', 'trenchcoat': 'tops',
    'trenckot': 'tops', 'pardesu': 'tops', 'parka': 'tops', 'blazer': 'tops',
    't-shirt': 'tops', 'tisort': 'tops', 'gomlek': 'tops',
    'bluz': 'tops', 'kazak': 'tops', 'hirka': 'tops', 'yelek': 'tops',
    'sweatshirt': 'tops', 'hoodie': 'tops', 'polo': 'tops',
    'atlet': 'tops', 'tank top': 'tops', 'crop top': 'tops',
    'shirt': 'tops', 'blouse': 'tops', 'sweater': 'tops', 'cardigan': 'tops',
    'vest': 'tops', 'top': 'tops', 'tunik': 'tops',
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
