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
    if not isinstance(analysis, dict):
        analysis = _default_analysis()
    if not isinstance(preset, dict):
        preset = {}
    if not isinstance(outfit_consistency, dict):
        outfit_consistency = {}

    category = analysis.get('clothingCategory', 'tops')
    garment_type = analysis.get('garmentType', 'garment')
    garment_type_lower = f"{garment_type} {category}".lower()

    # Dış giyim ve üst giyim koruması (manto, kaban, palto, ceket, bluz, gömlek ASLA elbise olamaz)
    TOPS_AND_OUTERWEAR_KEYWORDS = [
        'manto', 'kaban', 'palto', 'mont', 'ceket', 'jacket', 'coat',
        'trenchcoat', 'trençkot', 'trench', 'pardösü', 'pardesu',
        'parka', 'anorak', 'blazer', 'bluz', 'blouse', 'gömlek', 'shirt',
        'tişört', 'tisort', 't-shirt', 'tshirt', 'kazak', 'sweater',
        'hırka', 'hirka', 'cardigan', 'yelek', 'vest', 'sweatshirt',
        'hoodie', 'tunik', 'tunic', 'atlet', 'süveter'
    ]
    is_top_or_outerwear = (
        category in ['tops', 'outerwear', 'knitwear']
        or _safe_keyword_match(garment_type_lower, TOPS_AND_OUTERWEAR_KEYWORDS)
    )

    if is_top_or_outerwear:
        is_skirt = False
        is_shorts = False
        is_dress = False
        if category not in ['tops', 'outerwear', 'knitwear']:
            category = 'outerwear' if _safe_keyword_match(garment_type_lower, ['manto', 'kaban', 'palto', 'mont', 'ceket', 'coat', 'jacket', 'trençkot']) else 'tops'
    else:
        is_skirt = _safe_keyword_match(garment_type_lower, ['etek', 'skirt'])
        is_shorts = _safe_keyword_match(garment_type_lower, ['şort', 'sort', 'shorts', 'bermuda'])
        is_dress = category in ['dress', 'one_piece', 'one-piece', 'full-body'] or _safe_keyword_match(garment_type_lower, ['elbise', 'dress', 'tulum', 'jumpsuit', 'abiye'])

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
        # fal vb. modeller icin kisa ve olumlu prompt
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

        # Yaka/kol bilgisi (sadece ust giyim)
        if collar and category not in ['bottoms']:
            base_prompt += f"Collar: {collar}. "
        if sleeve and category not in ['bottoms']:
            base_prompt += f"Sleeves: {sleeve}. "

            # Strapless / Sleeveless — olumlu cerceleme
            sleeve_lower = sleeve.lower()
            if any(k in sleeve_lower for k in ['strapless', 'askisiz', 'askısız', 'sleeveless', 'kolsuz', 'tube']):
                base_prompt += (
                    "This garment is strapless with completely bare shoulders. "
                    "The model has bare upper arms with clean, exposed shoulders. "
                )

            # Ince askili — olumlu cerceleme
            if any(k in sleeve_lower for k in ['ince askı', 'ince aski', 'spaghetti', 'thin strap', 'askili', 'askılı']):
                base_prompt += (
                    "This garment has single thin spaghetti straps — exactly one delicate strap per shoulder. "
                )

        # ═══ BASKI / GRAFIK KORUMA ═══
        has_graphic = analysis.get('hasGraphic', False)
        graphic_desc = analysis.get('graphicDescription', '')
        if has_graphic and graphic_desc:
            base_prompt += (
                f"This garment has a graphic print: '{graphic_desc}'. "
                f"Preserve the print exactly as shown — same position, colors, proportions. "
            )
        elif has_graphic:
            base_prompt += "Preserve the graphic print exactly as shown in the reference. "

        # ═══ DONANIM KORUMA ═══
        closure = analysis.get('closureType', '')
        button_count = analysis.get('buttonCount')
        waistband_type = analysis.get('waistbandType', '')
        # Beli lastikli pantolonda 1 adet dugme algilanmissa bu neredeyse kesinlikle alarm pinidir
        is_elastic_bottom = category == 'bottoms' and (
            'elastic' in str(waistband_type).lower() or 'lastik' in str(waistband_type).lower()
        )
        if is_elastic_bottom and (button_count == 1 or str(button_count) == '1'):
            closure = ''
            button_count = None

        if closure and str(closure).lower() not in ['yok', 'none', 'null', 'false', '']:
            base_prompt += f"Hardware: genuine garment {closure} only. Preserve authentic buttons/zippers. "
            if button_count and str(button_count).isdigit() and int(str(button_count)) > 0:
                base_prompt += f"Exactly {button_count} buttons, matched precisely. "

        # ═══ WAISTBAND / ALT GİYİM DETAYLARI (Gemini analizinden) ═══
        if category == 'bottoms':
            waistband_type = analysis.get('waistbandType', '')
            has_belt_loops = analysis.get('hasBeltLoops', False)
            if has_belt_loops:
                base_prompt += "The waistband has belt loops as visible in the reference image. "
            elif waistband_type:
                base_prompt += f"The waistband is {waistband_type}, smooth and uninterrupted. "
            else:
                base_prompt += "The waistband is smooth, clean, and continuous as shown in the reference. "

        # ═══ YAKA KORUMA (sadece ust giyim) ═══
        if photo_type in ['front', 'side'] and category not in ['bottoms']:
            base_prompt += (
                "The front neckline is clean and single-layered. "
                "Ignore any inner back lining visible through the neck opening. "
            )

        # ═══ AKSESUAR (Minimal ve Doğal) ═══
        # Asla rastgele el çantası (handbag) eklenmemelidir: çantalar kıyafeti kapatır, uyumsuz durur ve elleri bozar.
        if photo_type in ['front', 'side', 'back']:
            base_prompt += "No handbag, no purse. Clean minimalist studio fashion posing, arms and hands relaxed naturally. "

        # ═══ OUTFIT KOMBİN & ALT/ÜST GİYİM DİREKTİFİ ═══
        if is_skirt:
            base_prompt += (
                "SKIRT: Model wears ONLY this skirt. Natural bare legs below hemline. "
                "NO pants, jeans, or leggings underneath. Neutral fitted top on upper body. "
            )
        elif is_shorts:
            base_prompt += (
                "SHORTS: Model wears ONLY these shorts. Natural bare legs below hemline. "
                "NO long pants or leggings underneath. Neutral fitted top on upper body. "
            )
        elif is_dress:
            base_prompt += (
                "DRESS: Model wears ONLY this dress with shoes. Natural bare legs below hemline. "
                "NO pants, jeans, or leggings underneath. "
            )
        elif category == 'bottoms':
            base_prompt += (
                "PANTS: Legs fully covered as shown in reference. "
                "Neutral fitted top on upper body. "
            )
        elif is_top_or_outerwear or category in ['tops', 'outerwear', 'knitwear']:
            recommended_bottoms = analysis.get('recommendedBottoms', 'dark blue skinny jeans')
            if not recommended_bottoms:
                recommended_bottoms = 'dark blue skinny jeans'
            base_prompt += (
                f"MANDATORY BOTTOM: Model MUST wear {recommended_bottoms}. "
                "Full-length, covering entire legs. NO bare legs, NO shorts. "
            )

        # ═══ GÜVENLİK ETİKETİ / ALARM TAGI İGNORE ═══
        base_prompt += "Remove all store security tags, alarm pins, price tags. Output must be clean and tag-free. "

    # Cift bosluklari temizle
    base_prompt = " ".join(base_prompt.split()) + " "

    # ═══ CROSS-VIEW OUTFIT TUTARLILIĞI ═══
    # Front haric diger acilarda alt kombin (pantolon, ayakkabi) tutarlilik talimatini
    # prompt'un EN BASINA yerlestir — nano-banana-2 modeli bu talimati once gormeli.
    if outfit_consistency and photo_type != 'front':
        consistency_prompt = outfit_consistency.get('fullOutfitPrompt', '')
        if consistency_prompt:
            base_prompt = consistency_prompt + base_prompt

    if photo_type == 'back':
        base_prompt += (
            "BACK VIEW. Reproduce back design exactly. "
            "Back waistband must be clean — no buttons, rivets, or tags. "
            "Hanger fold-over at shoulder is the FRONT side, not back design — show only single back panel. "
        )
    elif photo_type == 'side':
        if is_top_or_outerwear:
            base_prompt += (
                "45-DEGREE SIDE VIEW. Same inner top and pants as front view. "
                "Do NOT put back fabric on chest. No bare legs. "
            )
        else:
            base_prompt += "45-DEGREE SIDE VIEW. Reproduce garment accurately from side angle. "

    # Preset bilgileri (manken tipi, cinsiyeti)
    if preset:
        gender = preset.get('gender', 'female')
        body = preset.get('body_type', 'average')
        audience = preset.get('target_audience', '')
        base_prompt += f"Model: {gender}, {body} body type. "
        if audience:
            base_prompt += f"Target audience: {audience}. "

    # Negatif prompt başlangıcı
    negative = _VIEW_NEGATIVE_PROMPTS.get(photo_type, _VIEW_NEGATIVE_PROMPTS['front'])

    # Kalite ve kilit promptlar
    for lock in prompt_locks:
        lock_str = str(lock).strip()
        if lock_str.upper().startswith('NEGATIVE'):
            # Negatif kilitler pozitif prompta değil, negatif prompta eklenmeli
            neg_content = lock_str[8:].lstrip(': ')
            negative = f"{negative}, {neg_content}"
        else:
            base_prompt += f" {lock}"

    # Kullanici ek promptu
    if extra_prompt:
        base_prompt += f" ADDITIONAL USER DIRECTIVE: {extra_prompt}"

    if is_skirt or is_shorts or is_dress:
        # Mini etek, sort veya elbiselerde bacak acilmasini engelleyen token'lari temizle ve altina pantolon giyilmesini kesin yasakla
        for banned_token in ['mini skirt', 'short shorts', 'hot pants', 'bare legs', 'bare thighs', 'exposed legs']:
            negative = negative.replace(banned_token, '')
        negative = "pants under skirt, jeans under skirt, trousers under skirt, leggings under skirt, denim under skirt, double pants, double bottoms, pants under dress, jeans under dress, denim under dress, " + negative
    elif is_top_or_outerwear or category in ['tops', 'outerwear', 'knitwear']:
        # Üst giyim ve dış giyimde (manto, mont, ceket, bluz vb.) pantolonsuz / çıplak bacak kesinlikle yasak!
        for pants_banned in ['pants under dress', 'jeans under dress', 'trousers under dress', 'denim under dress']:
            negative = negative.replace(pants_banned, '')
        negative = "bare legs, bare thighs, exposed legs, no pants, shorts, cycling shorts, hot pants, underwear only, nude legs, bare knees, mini dress coat, " + negative

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
        "Professional e-commerce front view photography. "
        "Full-body model facing camera wearing {color} {fabric} {garment_type}. "
        "{fit}, {pattern} pattern. Clean white studio background, even lighting. "
        "Confident fashion pose, one hand on hip, slight S-curve silhouette. "
        "Sharp focus on garment details and fabric texture. "
    ),
    'back': (
        "Professional e-commerce back view photography. "
        "Full-body model facing AWAY from camera showing the back of {color} {fabric} {garment_type}. "
        "{fit}, {pattern} pattern. Clean white studio background, even lighting. "
        "Elegant back pose, slight contrapposto. "
        "Sharp focus on back details, seams, and garment shape. "
    ),
    'side': (
        "Professional e-commerce side view photography. "
        "Full-body model turned 45 degrees showing profile of {color} {fabric} {garment_type}. "
        "{fit}, {pattern} pattern. Clean white studio background, even lighting. "
        "Three-quarter fashion pose, contrapposto stance. "
        "Sharp focus on garment side profile and fit. "
    ),
    'detail': (
        "Professional close-up detail shot of {color} {fabric} {garment_type} worn on a model. "
        "Tight crop on chest/torso area. {pattern} pattern. "
        "Focus on fabric texture, stitching quality, and material details. "
        "Studio macro lighting, extreme sharp focus. "
    ),
}

_VIEW_NEGATIVE_PROMPTS = {
    'front': (
        "nudity, naked, underwear, lingerie, swimwear, bikini, "
        "no pants, panties, see-through clothing revealing skin, inappropriate, NSFW, "
        "security tag, alarm tag, anti-theft tag, EAS sensor, retail security badge, "
        "plastic alarm pin, ink tag, hard tag, security button, store tag, price tag, "
        "store fixture, retail clip, fake waist rivet, misplaced rivet, extra buttons, "
        "handbag, purse, clutch, tote bag, bag held in hand, shopping bag, awkward accessories, floating bag"
    ),
    'back': (
        "nudity, naked, bare back, "
        "underwear, lingerie, swimwear, bikini, "
        "no pants, panties, see-through clothing revealing skin, inappropriate, NSFW, "
        "crop top only, sports bra only, "
        "hanger, hanger hook, fabric fold-over, double-layered back, cape-like flap, "
        "extra fabric layer on back, wing-like extensions on shoulders, two-toned back panel, "
        "security tag, alarm tag, anti-theft tag, EAS sensor, retail security badge, "
        "plastic alarm pin, ink tag, hard tag, store tag, price tag, store fixture, "
        "retail clip, button on back waistband, rivet on back waistband, back waist button, "
        "metal badge on waistband, back pocket rivet, fake waistband hardware, "
        "handbag, purse, clutch, tote bag, bag held in hand, shopping bag, awkward accessories, floating bag"
    ),
    'side': (
        "nudity, naked, "
        "underwear, lingerie, swimwear, bikini, "
        "no pants, panties, see-through clothing revealing skin, inappropriate, NSFW, "
        "security tag, alarm tag, anti-theft tag, EAS sensor, retail security badge, "
        "plastic alarm pin, ink tag, hard tag, store tag, price tag, store fixture, retail clip, "
        "handbag, purse, clutch, tote bag, bag held in hand, shopping bag, awkward accessories, floating bag"
    ),
    'detail': (
        "security tag, alarm tag, anti-theft tag, EAS sensor, retail security badge, "
        "plastic alarm pin, ink tag, hard tag, store tag, price tag, store fixture, retail clip, "
        "handbag, purse, clutch, tote bag, bag held in hand, awkward accessories"
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
