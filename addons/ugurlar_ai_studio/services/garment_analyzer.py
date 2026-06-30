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
Ignore any hangers, clips, hands, or mannequins holding the garment. Focus ONLY on the garment's actual design.
CRITICAL: If there are any plastic security tags, anti-theft alarms, or store price tags visible on the garment, completely IGNORE them. Do not describe them or treat them as part of the garment's design.

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
  "seoDescription": "string — SEO optimized Turkish description (50-100 words)",
  "recommendedBottoms": "string — Describe in English the most matching pants/trousers/jeans style and color to build a stylish outfit with this product (e.g. 'dark blue slim-fit denim jeans', 'beige tailored cotton trousers', 'black cargo pants')",
  "recommendedShoes": "string — Describe in English the most matching shoes style and color for this outfit (e.g. 'clean white minimalist leather sneakers', 'brown leather loafers', 'black high-top boots')"
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


def analyze_outfit_consistency(image_data, api_key=None, gemini_api_key=None):
    """Front try-on sonucundaki TUM kıyafet detaylarını analiz et.

    Cross-view tutarlılık için: front sonucundaki pantolon, ayakkabı,
    saç stili gibi detayları çıkarır, back/side promptlarına enjekte edilir.

    Args:
        image_data: Front try-on sonucu (base64 veya URL)
        api_key: fal.ai API anahtarı (fallback)
        gemini_api_key: Gemini API anahtarı

    Returns:
        dict: {
            'bottomsDescription': str — alt giyim detayı,
            'shoesDescription': str — ayakkabı detayı,
            'hairDescription': str — saç stili,
            'accessoriesDescription': str — aksesuar detayı,
            'skinTone': str — ten rengi,
            'fullOutfitPrompt': str — tüm tutarlılık talimatı,
        }
    """
    prompt = """You are analyzing a fashion model photograph for OUTFIT CONSISTENCY.
Your job is to describe EVERYTHING the model is wearing and their appearance,
EXCEPT for the main top garment (which will be changed in other views).

Analyze and return JSON:
{
  "bottomsType": "string — pants/jeans/skirt/shorts type (e.g., 'slim-fit white trousers', 'dark blue skinny jeans')",
  "bottomsColor": "string — exact color (e.g., 'white', 'dark navy blue', 'black')",
  "shoesType": "string — shoe type (e.g., 'white low-top sneakers', 'black ankle boots', 'beige heels')",
  "shoesColor": "string — shoe color",
  "hairStyle": "string — hair description (e.g., 'long wavy blonde hair', 'short brown bob')",
  "hairColor": "string — hair color",
  "skinTone": "string — skin tone (e.g., 'fair/light', 'medium', 'olive', 'dark')",
  "accessories": "string — any visible accessories (watch, necklace, earrings, belt) or 'none'",
  "modelBuild": "string — body build (e.g., 'slim', 'athletic', 'curvy', 'standard')",
  "backgroundDescription": "string — background (e.g., 'clean white studio', 'light grey')"
}

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
        "CROSS-VIEW OUTFIT CONSISTENCY — CRITICAL: "
        "The model MUST wear the EXACT SAME outfit as the front view: "
        + ", ".join(parts) + ". "
        "Do NOT change the pants/bottoms color, shoe type, hair style, or any accessory. "
        "Every view must look like the SAME photoshoot session. "
    )


def build_generation_prompt(analysis, preset, prompt_locks, extra_prompt='',
                            photo_type='front', outfit_consistency=None, provider_type='fashn'):
    """Analiz sonuclarina gore AI gorsel uretim promptu olustur.
    
    FASHN ve virtual try-on modellerinde kiyafetin rengi, deseni veya baski grafik
    detaylari prompta yazilmamalidir. Ancak 'fal' (nano-banana-2/edit vb.) gibi
    genel inpainting modellerinde bu detaylar gereklidir.

    Args:
        analysis: Kiyafet analiz sonuclari (dict)
        preset: Manken preset bilgileri (dict)
        prompt_locks: Aktif prompt lock listesi (list of str)
        extra_prompt: Ek kullanici promptu
        photo_type: str — 'front', 'back', 'side', 'detail'
        outfit_consistency: dict — outfit tutarlilik verileri
        provider_type: str — 'fashn', 'fal', vb.

    Returns:
        dict: {'positive': str, 'negative': str}
    """
    view_base = _VIEW_PROMPT_TEMPLATES.get(photo_type, _VIEW_PROMPT_TEMPLATES['front'])

    if provider_type == 'fashn':
        # Sablonu generic kelimelerle formatla (kiyafet detaylari prompta gitmesin)
        base_prompt = view_base.format(
            garment_type="garment",
            color="",
            fabric="",
            pattern="plain",
            style="casual",
            fit="standard fit",
        )
    else:
        # fal vb. modeller icin tam detayli prompt
        garment_type = analysis.get('garmentType', 'garment')
        color = analysis.get('primaryColor', '')
        fabric = analysis.get('fabricType', '')
        pattern = analysis.get('pattern', 'Duz')
        style = analysis.get('style', 'Casual')
        fit = analysis.get('fitDetails', 'Regular Fit')
        collar = analysis.get('collarType', '')
        sleeve = analysis.get('sleeveType', '')

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
            
            # Strapless / Sleeveless icin Anti-Halusinasyon Kilidi
            sleeve_lower = sleeve.lower()
            if any(k in sleeve_lower for k in ['strapless', 'askisiz', 'askısız', 'no sleeve', 'sleeveless', 'kolsuz', 'kol yok', 'tube']):
                base_prompt += (
                    "CRITICAL GARMENT STRUCTURE LOCK: This garment is STRICTLY STRAPLESS / TUBE TOP. "
                    "The model MUST have completely BARE shoulders and BARE upper arms. "
                    "DO NOT generate ANY straps, sleeves, arm bands, or shoulder fabric. "
                    "Any fabric on the shoulders or arms is a hallucination and a FAILURE. "
                    "Ignore any hanger strings in the input image. "
                )

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

        # ═══ DONANIM VE DETAY KORUMA (ALARM YOK SAYMA) ═══
        closure = analysis.get('closureType', '')
        if closure and str(closure).lower() not in ['yok', 'none', 'null', 'false', '']:
            base_prompt += (
                f"CRITICAL HARDWARE PRESERVATION: The garment has {closure} details. "
                "You MUST exactly preserve all visible buttons, zippers, snaps, rivets, and hardware "
                "from the original image. Do not alter their size, shape, color, or placement. "
            )
        else:
            base_prompt += (
                "CRITICAL HARDWARE PRESERVATION: You MUST exactly preserve any visible buttons, "
                "zippers, snaps, rivets, or hardware from the original image. Do not alter their "
                "size, shape, color, or placement. "
            )
        base_prompt += (
            "CRITICAL: IGNORE and REMOVE any plastic security tags, anti-theft alarms, "
            "or store price tags attached to the garment. Do not generate them. "
        )

        # ═══ E-TİCARET PROFESYONEL STYLING & AKSESUAR ═══
        if photo_type in ['front', 'side', 'back']:
            base_prompt += (
                "STYLE INSTRUCTION: Elevate the model's look for a high-end luxury e-commerce aesthetic. "
                "Decorate the model with elegant, perfectly matching accessories such as a stylish handbag, "
                "a luxury watch, and elegant earrings or a necklace. The accessories MUST complement the outfit perfectly "
                "and add a premium feel to the overall look. "
                "CRITICAL: The accessories (especially the handbag) MUST NOT cover, hide, or obstruct the garment. "
                "Keep the handbag held low or to the side so the entire garment remains clearly visible. "
            )

    # Cift bosluklari temizle
    base_prompt = " ".join(base_prompt.split()) + " "

    # ═══ CROSS-VIEW OUTFIT TUTARLILIĞI ═══
    # Front haric diger acilarda alt kombin (pantolon, ayakkabi) tutarlilik talimatini ekle
    if outfit_consistency and photo_type != 'front':
        consistency_prompt = outfit_consistency.get('fullOutfitPrompt', '')
        if consistency_prompt:
            base_prompt += consistency_prompt

    # Preset bilgileri (manken tipi, cinsiyeti)
    if preset:
        gender = preset.get('gender', 'female')
        body = preset.get('body_type', 'average')
        audience = preset.get('target_audience', '')
        base_prompt += f"Model: {gender}, {body} body type. "
        if audience:
            base_prompt += f"Target audience: {audience}. "

    # Kalite ve kilit promptlar
    for lock in prompt_locks:
        base_prompt += f" {lock}"

    # Kullanici ek promptu
    if extra_prompt:
        base_prompt += f" ADDITIONAL USER DIRECTIVE: {extra_prompt}"

    # Negatif prompt
    negative = _VIEW_NEGATIVE_PROMPTS.get(photo_type, _VIEW_NEGATIVE_PROMPTS['front'])

    _logger.info(
        'Prompt olusturuldu (photo_type=%s, provider=%s): %d karakter',
        photo_type, provider_type, len(base_prompt),
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
        "PROFESSIONAL MODEL POSE: Confident, dynamic fashion pose — "
        "one hand on hip or slightly touching the thigh, weight shifted to one leg, "
        "slight body angle creating an S-curve silhouette. "
        "Natural relaxed shoulders, chin slightly lifted. "
        "NOT a stiff mannequin pose — the model should look alive and editorial. "
        "Sharp focus on garment details, fabric texture, and construction. "
    ),
    'back': (
        "Professional e-commerce BACK VIEW fashion photography. "
        "Full-body shot of a model facing AWAY from the camera, showing their back. "
        "The BACK of the {color} {fabric} {garment_type} is fully visible. "
        "Clean white/light studio background. Even, shadow-free lighting. "
        "Style: {style}, Fit: {fit}. Pattern: {pattern}. "
        "PROFESSIONAL MODEL POSE: Elegant back pose — "
        "slight contrapposto stance with weight on one leg, "
        "one hand resting naturally on hip or at side with slight bend, "
        "head turned very slightly to show jawline profile. "
        "NOT a rigid straight standing pose — the model should convey movement and elegance. "
        "Sharp focus on back details, seams, and garment shape. "
    ),
    'side': (
        "Professional e-commerce SIDE/THREE-QUARTER VIEW fashion photography. "
        "Full-body shot of a model turned approximately 45 degrees, showing profile. "
        "The SIDE PROFILE of the {color} {fabric} {garment_type} is visible. "
        "Clean white/light studio background. Even, shadow-free lighting. "
        "Style: {style}, Fit: {fit}. Pattern: {pattern}. "
        "PROFESSIONAL MODEL POSE: Elegant three-quarter fashion pose — "
        "contrapposto stance, one hand on hip, "
        "body slightly twisted to create dynamic silhouette, "
        "walking stride or mid-step look for editorial feel. "
        "Sharp focus on garment side profile and fit on body. "
    ),
    'detail': (
        "Professional CLOSE-UP DETAIL shot of a {color} {fabric} {garment_type} "
        "WORN ON A MODEL. Tight crop on the chest/torso area showing the garment up close. "
        "Focus on fabric texture, stitching quality, button/zipper details, and material. "
        "Pattern: {pattern}. "
        "Extreme sharp focus, studio macro lighting. "
        "Show the craftsmanship and material quality AS WORN on a real person. "
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
        "security tag, anti-theft alarm, plastic tag, price tag, store label, hanger clip, "
        "altered buttons, missing buttons, changed zipper, modified hardware, "
        "stiff pose, rigid standing, arms straight at sides, amateur pose, "
        "military stance, passport photo pose, "
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
        "security tag, anti-theft alarm, plastic tag, price tag, store label, hanger clip, "
        "altered buttons, missing buttons, changed zipper, modified hardware, "
        "stiff pose, rigid standing, arms straight at sides, amateur pose, "
        "military stance, "
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
        "security tag, anti-theft alarm, plastic tag, price tag, store label, hanger clip, "
        "altered buttons, missing buttons, changed zipper, modified hardware, "
        "stiff pose, rigid standing, amateur pose, "
        "bare midriff, bare chest, nude model"
    ),
    'detail': (
        "full body shot, wide angle, "
        "blurry, low quality, out of focus, "
        "altered garment design, wrong garment color, wrong fabric texture, "
        "modified print, different pattern, altered graphic, "
        "security tag, anti-theft alarm, plastic tag, price tag, store label, hanger clip, "
        "altered buttons, missing buttons, changed zipper, modified hardware, "
        "flat-lay photo, hanger, product-only shot without model"
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
        'recommendedBottoms': 'dark blue skinny jeans',
        'recommendedShoes': 'white sneakers',
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
