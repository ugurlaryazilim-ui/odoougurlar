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

    # Case 3: Raw base64 string — biçimi içerikten tespit et (ön işleme WebP üretir)
    try:
        raw = base64.b64decode(image_url)
        mime_type = 'image/jpeg'
        try:
            import io
            from PIL import Image
            fmt = (Image.open(io.BytesIO(raw)).format or '').upper()
            mime_type = {'PNG': 'image/png', 'WEBP': 'image/webp', 'JPEG': 'image/jpeg'}.get(fmt, 'image/jpeg')
        except Exception:
            pass
        return mime_type, image_url
    except Exception:
        pass

    return None, None


_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


def _gemini_json(gemini_api_key, prompt, image, schema=None, timeout=30, deterministic=False,
                 extra_images=None):
    """Görsel + prompt ile Gemini'den JSON al.

    Args:
        schema: Gemini responseSchema (OpenAPI alt kümesi). API reddederse (400)
            şemasız bir kez daha denenir.
        deterministic: temperature 0 ve "thinking" kapalı — Google'ın nesne
            tespiti (bounding box) önerisi.

    Returns:
        dict veya None (başarısız)
    """
    if not gemini_api_key or requests is None:
        return None
    mime_type, base64_data = _prepare_gemini_image(image)
    if not base64_data:
        _logger.warning('Görsel Gemini için hazırlanamadı')
        return None
    parts = [{"text": prompt}, {"inlineData": {"mimeType": mime_type, "data": base64_data}}]
    for extra in extra_images or []:
        e_mime, e_data = _prepare_gemini_image(extra)
        if e_data:
            parts.append({"inlineData": {"mimeType": e_mime, "data": e_data}})

    def _call(with_schema):
        config = {"responseMimeType": "application/json"}
        if with_schema and schema:
            config["responseSchema"] = schema
        if deterministic:
            config["temperature"] = 0
            config["thinkingConfig"] = {"thinkingBudget": 0}
        return requests.post(
            _GEMINI_URL,
            json={
                "contents": [{"parts": parts}],
                "generationConfig": config,
            },
            headers={'Content-Type': 'application/json', 'x-goog-api-key': gemini_api_key},
            timeout=timeout,
        )

    try:
        resp = _call(True)
        if resp.status_code == 400 and schema:
            _logger.warning('Gemini responseSchema reddedildi, şemasız tekrar deneniyor')
            resp = _call(False)
        resp.raise_for_status()
        text = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        if text.startswith('```'):
            text = text.strip('`')
            if text.startswith('json'):
                text = text[4:]
        parsed = json.loads(text.strip())
        return parsed if isinstance(parsed, dict) else None
    except Exception as e:
        status = getattr(getattr(e, 'response', None), 'status_code', None)
        _logger.warning('Gemini çağrısı başarısız (%s, status=%s)', e.__class__.__name__, status)
        return None


# Analizden gerçekten kullanılan alanlar (prompt kurucu + QC ipucu + log)
_ANALYSIS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "garmentType": {"type": "STRING"},
        "garmentTypeEn": {"type": "STRING"},
        "clothingCategory": {"type": "STRING", "enum": ["tops", "bottoms", "dress", "outerwear", "knitwear"]},
        "primaryColor": {"type": "STRING"},
        "primaryColorEn": {"type": "STRING"},
        "fabricType": {"type": "STRING"},
        "fabricTypeEn": {"type": "STRING"},
        "collarType": {"type": "STRING"},
        "collarTypeEn": {"type": "STRING"},
        "sleeveType": {"type": "STRING"},
        "hasGraphic": {"type": "BOOLEAN"},
        "graphicDescriptionEn": {"type": "STRING"},
        "garmentLength": {"type": "STRING", "enum": ["mini", "knee", "midi", "maxi", "standard"]},
    },
    "required": ["garmentType", "garmentTypeEn", "clothingCategory", "primaryColorEn", "garmentLength"],
}


def analyze_garment(api_key, image_url, gemini_api_key=None, product_context=None):
    """Kiyafet gorseli analiz et — tur, renk, kumas, detaylar.

    Mağaza etiketi tespiti burada YAPILMAZ: ayrı ve odaklı detect_image_tags()
    çağrısı çok daha doğru kutu verir.

    Args:
        api_key: fal.ai API anahtari (Gemini yoksa any-llm fallback)
        image_url: Analiz edilecek gorsel URL'si veya base64 verisi
        gemini_api_key: Google Gemini API anahtarı
        product_context: Ürün adı, kodu, kategorisi ve nitelikleri (Odoo ERP'den)

    Returns:
        dict: Analiz sonuclari
    """
    context_section = ""
    if product_context:
        context_section = f"""
OFFICIAL STORE PRODUCT INFORMATION (ground truth for the category):
"{product_context}"
- Manto, Kaban, Palto, Mont, Ceket, Blazer, Trençkot, Pardösü, Hırka, Kazak, Bluz, Gömlek, Tişört, Tunik → 'outerwear' or 'tops', never 'dress' (worn over trousers even if long or belted).
- Etek, Şort, Pantolon, Jean, Tayt → 'bottoms'.
- Elbise, Abiye, Tulum → 'dress'.
"""

    prompt = f"""You are a senior fashion merchandiser analyzing a product photo.
Ignore hangers, clips, hands, mannequins and any store tags; describe only the garment's own design.
{context_section}
If the garment hangs on a hanger, the front neckline may reveal the inside of the back panel (lining, back label, keyhole). Ignore anything seen through the neck opening and assume a clean standard front neckline.

Category rules:
- Skirts, shorts, trousers, jeans → 'bottoms'.
- Dresses, evening dresses, jumpsuits → 'dress'.
- Coats, jackets, cardigans, sweaters, blouses, shirts, t-shirts → 'outerwear' or 'tops', even if long or belted.
- For dresses and skirts, garmentLength must be 'mini', 'knee', 'midi' or 'maxi'; otherwise 'standard'.

Fields ending in "En" must be plain lowercase English; they go straight into an English image prompt.
The other text fields are in Turkish.

Return JSON:
{{
  "garmentType": "Turkish type, e.g. Gömlek, Pantolon, Triko Elbise, Mini Etek",
  "garmentTypeEn": "e.g. 'shirt', 'knit dress', 'wide-leg trousers', 'mini skirt', 'jumpsuit'",
  "clothingCategory": "tops | bottoms | dress | outerwear | knitwear",
  "primaryColor": "Turkish dominant color, e.g. Siyah, Lacivert",
  "primaryColorEn": "e.g. 'black', 'navy', 'burgundy'",
  "fabricType": "Turkish fabric, e.g. Pamuk, Triko, Saten",
  "fabricTypeEn": "e.g. 'cotton', 'knit', 'satin', 'denim'",
  "collarType": "Turkish collar/neckline if visible",
  "collarTypeEn": "without the word 'neckline', e.g. 'V', 'crew', 'shirt collar', 'turtleneck'",
  "sleeveType": "sleeve type if visible (e.g. uzun kollu, kolsuz, askılı)",
  "hasGraphic": true or false,
  "graphicDescriptionEn": "short English description of a print/graphic, or empty",
  "garmentLength": "mini | knee | midi | maxi | standard"
}}
Return ONLY valid JSON."""

    if gemini_api_key:
        _logger.info('Gemini ile kıyafet analizi yapılıyor...')
        parsed = _gemini_json(gemini_api_key, prompt, image_url, schema=_ANALYSIS_SCHEMA, timeout=45)
        if parsed:
            return parsed
        _logger.warning('Gemini analizi başarısız, fal.ai fallback denenecek')

    if api_key:
        return _analyze_via_fal(api_key, image_url, prompt)

    return _default_analysis()


# Mağaza etiketi tespiti — tek görev, kısa prompt, deterministik (daha doğru kutular)
_TAG_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "securityTags": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "box_2d": {"type": "ARRAY", "items": {"type": "INTEGER"}},
                    "label": {"type": "STRING",
                              "enum": ["alarm_tag", "price_tag", "hangtag", "tag_pin", "design_label"]},
                    "confidence": {"type": "NUMBER"},
                },
                "required": ["box_2d", "label"],
            },
        },
    },
    "required": ["securityTags"],
}

_TAG_PROMPT = """This garment was photographed inside a clothing store. Find every store item attached to it that must be removed before the product photo is published:
- alarm_tag: store security (EAS) hard tag. A rigid plastic piece, usually grey, white or black, round, oval or rectangular, about 2-6 cm, clipped ON TOP of the fabric with a pin. Very often on the waistband (front or back), hem, side seam or cuff.
- price_tag: paper or cardboard price or barcode tag, or a price sticker
- hangtag: brand hangtag hanging on a string, plastic fastener or safety pin
- tag_pin: the pin, plastic loop or string that attaches a tag
Also report the garment's own sewn-flat design elements that look similar (woven brand patch, leather patch) as "design_label", but ONLY when you are sure they are stitched into the garment. If you are unsure whether a small rectangle on the waistband is a store alarm tag or a brand patch, report it as "alarm_tag".
Never report buttons, rivets, zipper pulls, buckles, drawstrings or prints.
Include the whole object and its attachment in the box. Give each item a confidence from 0.0 to 1.0 and report anything at least 50% likely.
box_2d is [ymin, xmin, ymax, xmax] normalized to 0-1000.
Return JSON: {"securityTags": [{"box_2d": [ymin, xmin, ymax, xmax], "label": "alarm_tag", "confidence": 0.9}]}
Return {"securityTags": []} if there is none."""


def detect_image_tags(api_key, image_url, gemini_api_key=None):
    """Kıyafet görselindeki mağaza alarmı / fiyat etiketlerini tespit eder.

    Returns:
        list: [{'box_2d': [ymin, xmin, ymax, xmax], 'label': str, 'confidence': float}] veya []
    """
    if not image_url or not gemini_api_key:
        return []
    parsed = _gemini_json(gemini_api_key, _TAG_PROMPT, image_url, schema=_TAG_SCHEMA,
                          timeout=25, deterministic=True)
    tags = (parsed or {}).get('securityTags') or []
    tags = [t for t in tags if isinstance(t, dict) and isinstance(t.get('box_2d'), list)
            and len(t['box_2d']) == 4]
    if tags:
        _logger.info('detect_image_tags: %d etiket tespit edildi (%s)',
                     len(tags), ', '.join(str(t.get('label')) for t in tags))
    return tags


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
    if not image_url.startswith(('http://', 'https://', 'data:')):
        mime_type, b64 = _prepare_gemini_image(image_url)
        image_url = 'data:%s;base64,%s' % (mime_type or 'image/jpeg', b64)

    try:
        # any-llm yalnızca metin alır (görseli görmeden uydururdu); vision uç noktası şart
        result = fal_client.subscribe(
            'fal-ai/any-llm/vision',
            arguments={
                'prompt': prompt,
                'model': 'google/gemini-2.5-flash',
                'image_urls': [image_url],
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


_OUTFIT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "bottomsType": {"type": "STRING"},
        "bottomsColor": {"type": "STRING"},
        "shoesType": {"type": "STRING"},
        "shoesColor": {"type": "STRING"},
    },
}


def analyze_outfit_consistency(image_data, api_key=None, gemini_api_key=None, category='tops'):
    """Ön görünüm sonucundaki alt giyim ve ayakkabıyı çıkar (arka/yan tutarlılığı için).

    Arka/yan çağrılarına ön sonuç zaten Image 3 olarak gidiyor; bu kısa tarif
    yalnızca renk/model sabitlemeye yardımcı olur.

    Returns:
        dict: bottomsType, bottomsColor, shoesType, shoesColor (boş olabilir)
    """
    empty = {'bottomsType': '', 'bottomsColor': '', 'shoesType': '', 'shoesColor': ''}
    skip_bottoms = category in ('bottoms', 'one-piece', 'one_piece')
    prompt = (
        "Describe what this fashion model wears, in short plain English.\n"
        + ("Leave bottomsType and bottomsColor empty.\n" if skip_bottoms else
           "bottomsType: the trousers/jeans/skirt, e.g. 'slim-fit tailored trousers'. bottomsColor: its color.\n")
        + "shoesType: e.g. 'white low-top sneakers', 'nude pumps'. shoesColor: their color.\n"
        'Return JSON: {"bottomsType": "", "bottomsColor": "", "shoesType": "", "shoesColor": ""}'
    )
    parsed = None
    if gemini_api_key:
        parsed = _gemini_json(gemini_api_key, prompt, image_data, schema=_OUTFIT_SCHEMA, timeout=30)
    elif api_key:
        result = _analyze_via_fal(api_key, image_data, prompt)
        parsed = result if result != _default_analysis() else None
    if not parsed:
        return empty
    out = {k: str(parsed.get(k) or '').strip() for k in empty}
    if skip_bottoms:
        out['bottomsType'] = out['bottomsColor'] = ''
    _logger.info('Outfit tutarlılık: alt=%s %s, ayakkabı=%s %s',
                 out['bottomsColor'], out['bottomsType'], out['shoesColor'], out['shoesType'])
    return out



# Eski (İngilizce alan içermeyen) önbellekli analizler için minimal TR→EN sözlüğü.
# Yeni analizler garmentTypeEn / primaryColorEn / fabricTypeEn alanlarını döndürür.
_TR_EN_WORDS = {
    # renkler
    'siyah': 'black', 'beyaz': 'white', 'lacivert': 'navy', 'mavi': 'blue',
    'kirmizi': 'red', 'kırmızı': 'red', 'yesil': 'green', 'yeşil': 'green',
    'sari': 'yellow', 'sarı': 'yellow', 'gri': 'grey', 'bej': 'beige',
    'kahverengi': 'brown', 'kahve': 'brown', 'pembe': 'pink', 'mor': 'purple',
    'turuncu': 'orange', 'ekru': 'ecru', 'krem': 'cream', 'haki': 'khaki',
    'bordo': 'burgundy', 'vizon': 'mink', 'antrasit': 'anthracite', 'fume': 'smoke grey',
    'indigo': 'indigo', 'petrol': 'petrol blue', 'hardal': 'mustard', 'lila': 'lilac',
    'mint': 'mint', 'taba': 'tan', 'camel': 'camel', 'altin': 'gold', 'altın': 'gold',
    'gumus': 'silver', 'gümüş': 'silver', 'acik': 'light', 'açık': 'light', 'koyu': 'dark',
    # kumaşlar
    'pamuk': 'cotton', 'keten': 'linen', 'triko': 'knit', 'örme': 'knit', 'orme': 'knit',
    'saten': 'satin', 'ipek': 'silk', 'yun': 'wool', 'yün': 'wool', 'kase': 'cashmere-blend',
    'kaşe': 'cashmere-blend', 'kadife': 'velvet', 'deri': 'leather', 'suet': 'suede',
    'süet': 'suede', 'sifon': 'chiffon', 'şifon': 'chiffon', 'viskon': 'viscose',
    'krep': 'crepe', 'tul': 'tulle', 'tül': 'tulle', 'dantel': 'lace', 'kot': 'denim',
    'polar': 'fleece', 'tvit': 'tweed', 'gabardin': 'gabardine', 'poplin': 'poplin',
    # türler
    'elbise': 'dress', 'etek': 'skirt', 'pantolon': 'trousers', 'sort': 'shorts',
    'şort': 'shorts', 'gomlek': 'shirt', 'gömlek': 'shirt', 'bluz': 'blouse',
    'kazak': 'sweater', 'hirka': 'cardigan', 'hırka': 'cardigan', 'ceket': 'jacket',
    'mont': 'jacket', 'kaban': 'coat', 'palto': 'coat', 'manto': 'long coat',
    'trenckot': 'trench coat', 'trençkot': 'trench coat', 'yelek': 'vest',
    'tisort': 't-shirt', 'tişört': 't-shirt', 'tunik': 'tunic', 'tulum': 'jumpsuit',
    'abiye': 'evening dress', 'tayt': 'leggings', 'atlet': 'tank top',
    'jean': 'denim', 'kemerli': 'belted', 'mini': 'mini', 'midi': 'midi', 'maxi': 'maxi',
    'uzun': 'long', 'kisa': 'short',
    'kısa': 'short', 'kolsuz': 'sleeveless', 'askili': 'strappy', 'askılı': 'strappy',
    'desenli': 'patterned', 'cicekli': 'floral', 'çiçekli': 'floral',
    'cizgili': 'striped', 'çizgili': 'striped', 'kareli': 'checked', 'duz': '', 'düz': '',
    # yaka
    'yaka': '', 'yakalı': 'collared', 'yakali': 'collared', 'bisiklet': 'crew', 'balıkçı': 'turtleneck',
    'balikci': 'turtleneck', 'kayık': 'boat', 'kayik': 'boat', 'hakim': 'mandarin', 'kare': 'square',
    'kruvaze': 'wrap', 'kapüşonlu': 'hooded', 'kapusonlu': 'hooded',
}


def _to_english(analysis, key):
    """Analiz alanının İngilizce değerini döndür (keyEn → sözlük → orijinal)."""
    en_val = (analysis.get(f'{key}En') or '').strip()
    if en_val:
        return en_val
    raw = str(analysis.get(key) or '').strip()
    if not raw:
        return ''
    words = []
    for w in raw.split():
        mapped = _TR_EN_WORDS.get(w.lower())
        if mapped is None:
            # Sözlükte olmayan Türkçe kelime İngilizce prompta sızmasın ("Yakası" vb.)
            if set(w.lower()) & set('çğıöşü'):
                continue
            mapped = w
        words.append(mapped)
    return ' '.join(w for w in words if w)


def _detect_sub_type(category, garment_text):
    """Prompt alt tipini belirle: jumpsuit > dress > skirt > shorts > tops > bottoms."""
    from .category_constants import TOPS_AND_OUTERWEAR_KW, JUMPSUIT_KW, normalize_tr
    # 'ELBİSE'.lower() birleşik noktalı i üretir ve 'elbise' ile eşleşmez
    garment_text = normalize_tr(garment_text)
    if _safe_keyword_match(garment_text, JUMPSUIT_KW):
        return 'jumpsuit'
    if category in ('dress', 'one_piece', 'one-piece', 'full-body') or \
            _safe_keyword_match(garment_text, ['elbise', 'dress', 'abiye', 'gown']):
        return 'dress'
    if _safe_keyword_match(garment_text, ['etek', 'skirt']):
        return 'skirt'
    if _safe_keyword_match(garment_text, ['şort', 'sort', 'shorts', 'bermuda']):
        return 'shorts'
    if category in ('tops', 'outerwear', 'knitwear') or \
            _safe_keyword_match(garment_text, TOPS_AND_OUTERWEAR_KW):
        return 'tops'
    if category == 'bottoms':
        return 'bottoms'
    return 'tops'  # Safe fallback


_OPEN_FRONT_WORDS = ['yelek', 'vest', 'waistcoat', 'hırka', 'hirka', 'cardigan', 'ceket',
                     'jacket', 'blazer', 'mont', 'kaban', 'coat', 'trençkot', 'trench']


def build_generation_prompt(analysis, preset, prompt_locks, extra_prompt='',
                            photo_type='front', outfit_consistency=None, provider_type='fashn',
                            scene_prompt='', has_front_ref=True):
    """Analiz sonuclarina gore AI gorsel uretim promptu olustur.

    Seedream v5 Pro: pozitif dilde, yalnızca İngilizce, 60-90 kelimelik
    kategori şablonları (bkz. category_constants.SEEDREAM_TEMPLATES).
    FASHN için minimal prompt — kendi try-on modelini kullanır.

    Args:
        analysis: Kiyafet analiz sonuclari (dict)
        preset: Manken preset bilgileri (dict)
        prompt_locks: Aktif prompt lock listesi (list of str)
        extra_prompt: Ek kullanici / revizyon promptu (İngilizce olmalı)
        photo_type: 'front', 'back', 'side', 'detail'
        outfit_consistency: dict — ön görünüm outfit verisi (back/side için)
        provider_type: 'fashn', 'fal', vb.
        scene_prompt: Sahne tarifi; verilirse beyaz stüdyo arka planının yerini alır
        has_front_ref: back/side çağrısında ön görünüm sonucu (Image 3) gönderiliyor mu

    Returns:
        dict: {'positive': str, 'negative': str}
    """
    from .category_constants import (
        SEEDREAM_TEMPLATES, SEEDREAM_NEGATIVES,
        LEG_RULES, SHOE_RULES, HAND_POSES, DEFAULT_BACKGROUND, FRONT_REF_SENTENCE,
        FASHN_VIEW_TEMPLATES, FASHN_NEGATIVE, CLEAN_PRODUCT,
    )

    if not isinstance(analysis, dict):
        analysis = _default_analysis()
    if not isinstance(preset, dict):
        preset = {}
    if not isinstance(outfit_consistency, dict):
        outfit_consistency = {}

    category = analysis.get('clothingCategory', 'tops')
    garment_type_raw = analysis.get('garmentType', 'garment')
    sub_type = _detect_sub_type(category, f"{garment_type_raw} {category}".lower())

    # İngilizce ürün adı; alt tiple çelişen kelimeleri normalize et
    # (ör. "Triko Tunik" elbise ise "knit dress" — aksi halde model üst giyim sanıp
    # altına pantolon giydirir)
    garment = _to_english(analysis, 'garmentType') or 'garment'
    g_low = garment.lower()
    if sub_type == 'dress' and not any(d in g_low for d in ('dress', 'gown')):
        garment = 'knit dress' if 'knit' in g_low else ('shirt dress' if 'shirt' in g_low else 'dress')
    elif sub_type == 'jumpsuit' and 'jumpsuit' not in g_low and 'overall' not in g_low:
        garment = 'jumpsuit'
    elif sub_type == 'skirt' and 'skirt' not in g_low:
        garment = 'skirt'
    elif sub_type == 'shorts' and 'shorts' not in g_low:
        garment = 'shorts'

    # ═══ FASHN PROVIDER (minimal prompt, kendi try-on modeli) ═══
    if provider_type == 'fashn':
        base_prompt = FASHN_VIEW_TEMPLATES.get(photo_type, FASHN_VIEW_TEMPLATES['front'])
        negative = FASHN_NEGATIVE
        if sub_type in ('dress', 'skirt', 'shorts'):
            base_prompt += " Natural bare legs below the garment hemline. Model wears elegant heeled pumps or sandals."
        elif sub_type == 'tops':
            if any(w in g_low or w in garment_type_raw.lower() for w in _OPEN_FRONT_WORDS):
                base_prompt += f" The model wears a fitted solid neutral inner top underneath the open {garment}."
            base_prompt += " Model wears full-length dark trousers."
        elif sub_type in ('bottoms', 'jumpsuit'):
            base_prompt += " Full length visible down to the shoes."
        base_prompt += " " + CLEAN_PRODUCT
        for lock in prompt_locks:
            lock_str = str(lock).strip()
            if not lock_str.upper().startswith('NEGATIVE'):
                base_prompt += f" {lock_str}"
        if extra_prompt:
            base_prompt += f" {extra_prompt}"
        _logger.info('Prompt olusturuldu (photo_type=%s, provider=%s, sub_type=%s): %d karakter',
                     photo_type, provider_type, sub_type, len(base_prompt))
        return {'positive': base_prompt, 'negative': negative}

    # ═══ SEEDREAM / FAL PROVIDER ═══
    color = _to_english(analysis, 'primaryColor')
    fabric = _to_english(analysis, 'fabricType')
    # "knit knit dress" / "denim denim trousers" tekrarlarını ele
    desc_words = []
    for w in f"{color} {fabric} {garment}".lower().split():
        if w not in desc_words or w in ('light', 'dark'):
            desc_words.append(w)
    desc = ' '.join(desc_words)
    garment = garment.lower()

    garment_length = (analysis.get('garmentLength') or 'default').lower()
    leg_rules_for_type = LEG_RULES.get(sub_type, {})
    leg_rule = leg_rules_for_type.get(garment_length, leg_rules_for_type.get('default', ''))
    shoe_rule = ''
    if sub_type in ('dress', 'skirt'):
        shoe_rule = SHOE_RULES['maxi'] if garment_length == 'maxi' else SHOE_RULES['default']

    hand_pose = HAND_POSES.get(photo_type, '')

    # Yaka / kol notu (sadece ön görünüm)
    collar_note = ''
    if sub_type in ('tops', 'dress', 'jumpsuit') and photo_type == 'front':
        collar = _to_english(analysis, 'collarType')
        if collar:
            # "shirt collar neckline" gibi çift ifade olmasın
            collar_note = f"{collar}. " if 'collar' in collar.lower() or 'neck' in collar.lower() \
                else f"{collar} neckline. "
        sleeve_lower = str(analysis.get('sleeveType') or '').lower()
        if any(k in sleeve_lower for k in ['strapless', 'askisiz', 'askısız']):
            collar_note += "Bare shoulders, strapless design. "
        elif any(k in sleeve_lower for k in ['ince askı', 'spaghetti', 'thin strap']):
            collar_note += "Thin spaghetti straps. "
        elif any(k in sleeve_lower for k in ['sleeveless', 'kolsuz']):
            collar_note += "Sleeveless. "

    # Grafik / baskı notu
    graphic_note = ''
    if analysis.get('hasGraphic'):
        graphic_desc = (analysis.get('graphicDescriptionEn') or '').strip()
        graphic_note = (f"Preserve the print exactly: {graphic_desc.rstrip('. ')}. " if graphic_desc
                        else "Preserve the print exactly as in Image 2. ")

    # Açık önlü üst giyim (yelek, hırka, ceket...) için iç katman
    inner_top_note = ''
    if sub_type == 'tops' and any(w in g_low or w in garment_type_raw.lower() for w in _OPEN_FRONT_WORDS):
        inner_top_note = (
            f"A plain fitted neutral inner top is worn underneath the {garment}, "
            f"giving clean catalog coverage. "
        )

    front_ref = FRONT_REF_SENTENCE if (has_front_ref and photo_type in ('back', 'side')) else ''

    # Arka plan: sahne varsa stüdyo tarifinin yerini alır
    scene_prompt = (scene_prompt or '').strip()
    background = scene_prompt or DEFAULT_BACKGROUND

    # Detay görünümü AI'a gönderilmez (üretilen görselden kırpılır); tanımsız açılar ön şablonu kullanır
    template = SEEDREAM_TEMPLATES.get((sub_type, photo_type)) or \
        SEEDREAM_TEMPLATES.get((sub_type, 'front'), SEEDREAM_TEMPLATES[('tops', 'front')])

    base_prompt = template.format(
        garment=garment,
        desc=desc,
        leg_rule=leg_rule,
        shoe_rule=shoe_rule,
        inner_top_note=inner_top_note,
        hand_pose=hand_pose,
        collar_note=collar_note,
        graphic_note=graphic_note,
        front_ref=front_ref,
        background=background,
        extra_prompt=(extra_prompt or '').strip(),
    )

    # Prompt kilitleri (fotorealizm). Sahne seçiliyse stüdyo tarifi içerenler
    # sahneyle çelişeceği için atlanır.
    for lock in prompt_locks:
        lock_str = str(lock).strip()
        if not lock_str or lock_str.upper().startswith('NEGATIVE'):
            continue
        if scene_prompt and any(k in lock_str.lower() for k in ('studio', 'cyclorama')):
            continue
        base_prompt += f" {lock_str}"

    # Cross-view tutarlılık: sadece ÜST giyimde alt kombin bilgisi ekle
    # (alt giyimde bu bilgi değiştirilen ürünün kendisini tarif eder)
    if outfit_consistency and photo_type in ('back', 'side'):
        parts = []
        if sub_type == 'tops':
            bottoms = f"{outfit_consistency.get('bottomsColor', '')} {outfit_consistency.get('bottomsType', '')}".strip()
            if bottoms:
                parts.append(bottoms)
        if sub_type not in ('dress', 'skirt'):
            shoes = f"{outfit_consistency.get('shoesColor', '')} {outfit_consistency.get('shoesType', '')}".strip()
            if shoes:
                parts.append(shoes)
        if parts:
            base_prompt += f" Same styling as the front view: {', '.join(parts)}."

    base_prompt = " ".join(base_prompt.split())

    # Negatif prompt (Seedream kullanmaz; destekleyen modeller için)
    negative = SEEDREAM_NEGATIVES.get(sub_type, SEEDREAM_NEGATIVES['tops'])
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
    return {'positive': base_prompt, 'negative': negative}



# Görsel denetim hata kodları → reviewer'a gösterilecek Türkçe metin
VISUAL_QC_ISSUES = {
    'pants_under_dress': 'Elbise/etek altında pantolon veya tayt var',
    'bad_hands': 'El veya parmak bozuk',
    'store_tag_visible': 'Mağaza/alarm etiketi görünüyor',
    'added_label': 'Üründe olmayan etiket/yama eklenmiş',
    'extra_limbs_or_person': 'Fazla uzuv veya ikinci kişi var',
    'text_or_watermark': 'Görselde yazı veya filigran var',
    'garment_mismatch': 'Kıyafet ürünle uyuşmuyor',
}


def mannequin_legs_covered(gemini_api_key, image):
    """Manken görselinde bacaklar pantolon/tayt vb. ile kapalı mı?

    Returns:
        True / False, veya None (kontrol yapılamadı)
    """
    parsed = _gemini_json(
        gemini_api_key,
        "Look at the person's legs. Are they covered by trousers, jeans, leggings, tights or a long "
        "skirt? Answer legsCovered true or false. Return JSON: {\"legsCovered\": true}",
        image,
        schema={"type": "OBJECT", "properties": {"legsCovered": {"type": "BOOLEAN"}},
                "required": ["legsCovered"]},
        timeout=20, deterministic=True,
    )
    if not parsed or 'legsCovered' not in parsed:
        return None
    return bool(parsed['legsCovered'])


def visual_quality_check(gemini_api_key, generated_image, garment_hint='', timeout=30,
                         reference_image=None):
    """AI çıktısını Gemini ile gerçek üretim hatalarına karşı denetle.

    reference_image (temizlenmiş ürün görseli) verilirse karşılaştırmalı denetim yapılır:
    üründe olmayan etiket/yama/rozet "added_label" olarak bulunur. Etiket türü hataların
    konumu (box_2d, 0-1000) da döner; düzeltme bu kutularla maskeli silme yapar.

    Returns:
        dict: {'issues': [Türkçe], 'codes': [kod], 'boxes': [{'box_2d', 'code'}]} veya None
    """
    if not gemini_api_key or not generated_image:
        return None
    codes_doc = '\n'.join(f'- "{code}"' for code in VISUAL_QC_ISSUES)
    reference_note = (
        "Image 1 is the AI-generated photo. Image 2 is the real product (reference).\n"
        if reference_image else "Image 1 is the AI-generated photo.\n"
    )
    prompt = f"""You are a strict QA reviewer for AI-generated fashion e-commerce photos.
{reference_note}The product being modeled: {garment_hint or 'a garment'}.
Check Image 1 ONLY for these defects and report a code only when it is clearly present:
{codes_doc}
Rules:
- "pants_under_dress": only for dresses/skirts: trousers, jeans, leggings or tights visible under the hem. Jumpsuits are NOT dresses.
- "bad_hands": extra, missing, fused or malformed fingers, or deformed hands.
- "store_tag_visible": a security alarm tag, price tag, hangtag or tag pin attached to the garment.
- "added_label": {"a label, patch, badge, logo, tag or small object on the garment in Image 1 that does not exist on the product in Image 2 (check the waistband, back, hem and seams carefully)." if reference_image else "never report this code."}
For every "store_tag_visible" and "added_label" finding, add its bounding box on Image 1 as box_2d [ymin, xmin, ymax, xmax] normalized to 0-1000.
Return JSON: {{"defects": ["code", ...], "boxes": [{{"code": "added_label", "box_2d": [ymin, xmin, ymax, xmax]}}]}}.
Return {{"defects": [], "boxes": []}} if the photo is clean."""
    schema = {
        "type": "OBJECT",
        "properties": {
            "defects": {"type": "ARRAY", "items": {"type": "STRING", "enum": list(VISUAL_QC_ISSUES)}},
            "boxes": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                "code": {"type": "STRING"},
                "box_2d": {"type": "ARRAY", "items": {"type": "INTEGER"}},
            }}},
        },
        "required": ["defects"],
    }
    parsed = _gemini_json(gemini_api_key, prompt, generated_image, schema=schema, timeout=timeout,
                          deterministic=True, extra_images=[reference_image] if reference_image else None)
    if parsed is None:
        return None
    codes = [c for c in (parsed.get('defects') or []) if c in VISUAL_QC_ISSUES]
    boxes = [b for b in (parsed.get('boxes') or [])
             if isinstance(b, dict) and isinstance(b.get('box_2d'), list) and len(b['box_2d']) == 4]
    return {'codes': codes, 'issues': [VISUAL_QC_ISSUES[c] for c in codes], 'boxes': boxes}


def _default_analysis():
    """Analiz yapilamadiysa varsayilan dondurulen degerler."""
    return {
        'garmentType': 'Kiyafet',
        'garmentTypeEn': 'garment',
        'clothingCategory': 'tops',
        'primaryColor': '',
        'fabricType': '',
        'collarType': '',
        'sleeveType': '',
        'hasGraphic': False,
        'graphicDescriptionEn': '',
        'garmentLength': 'standard',
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
