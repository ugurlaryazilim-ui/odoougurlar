# -*- coding: utf-8 -*-
"""Merkezi kategori sabitleri ve Seedream prompt şablonları.

Tüm keyword listeleri, kategori eşleştirmeleri ve prompt şablonları tek dosyada.
garment_analyzer.py, fal_provider.py ve ai_studio_session.py bu dosyadan import eder.
3 dosyada tekrar yerine tek kaynak (DRY prensibi).
"""

# ═══════════════════════════════════════════════════════════════════════════
# KATEGORI KEYWORD LISTELERİ
# ═══════════════════════════════════════════════════════════════════════════

TOPS_AND_OUTERWEAR_KW = [
    'manto', 'kaban', 'palto', 'mont', 'ceket', 'jacket', 'coat',
    'trenchcoat', 'trençkot', 'trench', 'pardösü', 'pardesu',
    'parka', 'anorak', 'blazer', 'bluz', 'blouse', 'gömlek', 'gomlek',
    'shirt', 'tişört', 'tisort', 't-shirt', 'tshirt',
    'kazak', 'sweater', 'hırka', 'hirka', 'cardigan', 'süveter', 'suveter',
    'yelek', 'vest', 'sweatshirt', 'hoodie', 'tunik', 'tunic',
    'atlet', 'tank top', 'crop top', 'bustiyer', 'büstiyer',
    'üst giyim', 'body', 'rüzgarlık',
]

OUTERWEAR_ONLY_KW = [
    'manto', 'kaban', 'palto', 'mont', 'ceket', 'coat', 'jacket',
    'trençkot', 'trenchcoat', 'trench', 'pardösü', 'pardesu',
    'parka', 'anorak', 'blazer', 'rüzgarlık', 'yağmurluk', 'yagmurluk',
]

ONE_PIECE_KW = ['elbise', 'dress', 'tulum', 'jumpsuit', 'overall', 'abiye', 'tek parça']

# Tek parça ama bacakları kapatan (elbise bacak kurallarını ALMAMALI)
JUMPSUIT_KW = ['tulum', 'jumpsuit', 'overall', 'romper', 'salopet']

SKIRT_KW = ['etek', 'skirt']

SHORTS_KW = ['şort', 'sort', 'shorts', 'bermuda']

BOTTOMS_SAFE_KW = [
    'pantolon', 'jean', 'jeans', 'tayt', 'eşofman altı',
    'alt giyim', 'bermuda', 'capri', 'jogger',
]


BAGS_KW = ['çanta', 'canta', 'bag', 'bags', 'clutch', 'el çantası', 'sırt çantası', 'valiz', 'portföy']

SHOES_KW = [
    'ayakkabı', 'ayakkabi', 'shoe', 'shoes', 'bot', 'çizme', 'cizme',
    'terlik', 'sandalet', 'sneaker', 'spor ayakkabı', 'topuklu',
    'loafer', 'babet', 'slip-on', 'slipper', 'mule', 'stiletto',
]

ACCESSORIES_KW = [
    'aksesuar', 'accessory', 'accessories', 'kemer', 'belt', 'şal', 'sal',
    'fular', 'atkı', 'atki', 'bere', 'şapka', 'sapka', 'gözlük', 'gozluk',
    'saat', 'watch', 'bileklik', 'kolye', 'küpe', 'kupe', 'yüzük', 'yuzuk',
    'cüzdan', 'cuzdan', 'eldiven',
]

def normalize_tr(text):
    """Türkçe-güvenli küçük harf: 'ELBİSE'.lower() birleşik noktalı i üretir,
    'AYAKKABI' ise 'ayakkabi' olur — eşleşme için ı/i farkını da kaldırır."""
    return (text or '').replace('İ', 'i').lower().replace('i̇', 'i').replace('ı', 'i')


def _kw_regex(keywords, whole_word):
    """Anahtar kelime listesinden regex üret.

    whole_word=False: kelime başı eşleşmesi — Türkçe ekleri yakalar
        (elbise → elbiseler, pantolon → pantolonu).
    whole_word=True: tam kelime (+ yaygın çoğul/iyelik eki) — 'kemer' ≠ 'kemerli',
        'bot' ≠ 'bottom', 'sal' ≠ 'salaş', 'bag' ≠ 'baggy'.
    """
    import re
    parts = sorted({re.escape(normalize_tr(k)) for k in keywords}, key=len, reverse=True)
    body = '|'.join(parts)
    if whole_word:
        return re.compile(r'(?<!\w)(?:%s)(?:ler|lar|leri|lari|si|i)?(?!\w)' % body)
    return re.compile(r'(?<!\w)(?:%s)' % body)


# (kategori, anahtar kelimeler, tam_kelime) — SIRA ÖNEMLİ: giysi kelimeleri önce.
# Ürün adında giysi kelimesi varsa ("Kemerli Elbise", "Bot Paça Jean",
# "Şal Yaka Ceket") aksesuar/ayakkabı kelimeleri yok sayılır.
_GARMENT_RULES = [
    ('one_piece', ONE_PIECE_KW, False),
    ('tops', OUTERWEAR_ONLY_KW, False),
    ('tops', [k for k in TOPS_AND_OUTERWEAR_KW if k not in ('atlet', 'body', 'vest')], False),
    ('tops', ['atlet', 'body', 'bodysuit', 'vest'], True),
    ('bottoms', BOTTOMS_SAFE_KW + ['pantalon', 'palazzo', 'şalvar', 'salvar'], False),
    ('bottoms', SKIRT_KW + SHORTS_KW, False),
    ('bags', BAGS_KW, True),
    ('shoes', SHOES_KW, True),
    ('accessories', ACCESSORIES_KW, True),
]
_GARMENT_RULES_COMPILED = None


def classify_garment_text(text):
    """Serbest metinden (ürün adı + kategori + attribute) giysi tipi çıkar.

    Returns:
        (category, matched_keyword) veya (None, None). category:
        'one_piece' | 'tops' | 'bottoms' | 'bags' | 'shoes' | 'accessories'
    """
    global _GARMENT_RULES_COMPILED
    if _GARMENT_RULES_COMPILED is None:
        _GARMENT_RULES_COMPILED = [(cat, _kw_regex(kws, whole)) for cat, kws, whole in _GARMENT_RULES]
    norm = normalize_tr(text)
    for cat, rx in _GARMENT_RULES_COMPILED:
        m = rx.search(norm)
        if m:
            return cat, m.group(0)
    return None, None




# ═══════════════════════════════════════════════════════════════════════════
# SEEDREAM PROMPT ŞABLONLARI
#
# Seedream v5 Pro Edit negative_prompt / seed DESTEKLEMEZ — tek kaldıraç
# pozitif prompt'tur. Kurallar:
#   * Sadece İngilizce, 60-90 kelime, istenen sonucu TARİF ET.
#   * İstenmeyen nesneyi tekrar tekrar anma ("NO pants" ×9 modeli pantolona
#     çeker); gerekiyorsa tek bir "replace ... including trousers" cümlesi.
#   * Görsel rolleri sabittir (fal_provider sırasıyla eşleşir):
#       Image 1 = manken referansı (kimlik, poz, vücut)
#       Image 2 = ürün fotoğrafı
#       Image 3 = ön görünüm sonucu (sadece back/side ve varsa)
# ═══════════════════════════════════════════════════════════════════════════

# Bacak tarifleri — kıyafet uzunluğuna göre (pozitif dil)
LEG_RULES = {
    'dress': {
        'mini':    'The mini hem ends at mid-thigh, with bare legs visible below it.',
        'knee':    'The hem ends at the knee, with bare lower legs visible below it.',
        'midi':    'The midi hem ends at mid-calf, with bare lower legs visible below it.',
        'maxi':    'The maxi hem falls to the ankles.',
        'default': 'Bare legs are visible below the hem.',
    },
    'skirt': {
        'mini':    'The mini skirt ends at mid-thigh, with bare legs visible below it.',
        'knee':    'The skirt ends at the knee, with bare lower legs visible below it.',
        'midi':    'The midi skirt ends at mid-calf, with bare lower legs visible below it.',
        'maxi':    'The maxi skirt falls to the ankles.',
        'default': 'Bare legs are visible below the skirt hem.',
    },
    'shorts': {
        'default': 'Bare legs are visible below the shorts.',
    },
}

# Ayakkabı tarifleri — elbise/etek için zarif; maxi'de ayak çoğunlukla gizli
SHOE_RULES = {
    'default': 'She wears simple nude high-heeled pumps.',
    'maxi': 'Only the toes of simple nude heeled sandals show below the hem.',
}

# El pozları — view'e göre
# NOT: "one hand on hip" gibi detaylı poz talimatları Seedream'de
# fazla/kaynaşmış parmak sorununa yol açar. Basit tutulmalı.
# Duruş/ifade cümlesi: mankenin kaskatı, simetrik pozu ve donuk ifadesi aynen
# kopyalanmasın diye ağırlık aktarımı ve gevşek omuz istenir (el pozu yine basit).
HAND_POSES = {
    'front': ('Relaxed, natural stance with the weight on one leg, loose shoulders and a calm, '
              'natural expression. Arms hang loosely with natural hands.'),
    'back':  'Relaxed, natural stance with the weight shifted slightly onto one leg.',
    'side':  'Relaxed, natural stance with loose shoulders. Arms hang loosely at the sides.',
    'detail': '',
}

# Varsayılan arka plan (sahne seçilmediyse)
DEFAULT_BACKGROUND = 'Clean white studio background with soft, even lighting.'

# Üst giyim çekimlerinde sabit alt kombin (tüm açılarda aynı kalmalı)
DEFAULT_BOTTOMS = 'dark tailored full-length trousers'
# Alt giyim / etek / şort çekimlerinde sabit üst kombin
DEFAULT_TOP = 'a plain fitted neutral top'
# Üst giyimde kumaş pantolonla uyumlu ayakkabı (manken spor ayakkabı giyiyor olabilir)
DEFAULT_TOPS_SHOES = 'simple dark leather shoes'

# Temiz ürün: mağaza etiketleri Image 2'den zaten silinmiş olarak gelir. Cümle nesne
# adı İÇERMEZ — "no tags/labels" gibi olumsuzlamalar modele o nesneleri hatırlatıp
# bel bandına etiket/yama çizdiriyordu. Yalnızca Image 2'deki detaylar istenir.
# Değişmezlik: ürün detayları nesne nesne SAYILMAZ (sayılan nesneyi model başka yere de
# çiziyordu: kotun arkasına ön fermuar/perçin). "closures, hardware" gibi genel nesne adları
# da kapaması olmayan ürünün arkasına fermuar çizdiriyordu: cümlede hiç parça adı yok.
CLEAN_PRODUCT = (
    "The garment is exactly the item in Image 2, part for part: nothing added, nothing removed. "
    "A clean, finished retail product."
)

_FRONT_INTRO = (
    "Image 1 shows the model. Image 2 shows the {garment} product. "
    "Photograph the same model from Image 1, with the same face, hair and body, "
    "wearing the {desc} from Image 2 and reproducing its exact color, fabric, pattern and construction details. "
)
_BACK_INTRO = (
    "Image 1 shows the model from behind. Image 2 shows the back of the {garment} product. "
    "Back view of the same model, facing away from the camera, "
    "wearing the {desc} from Image 2. "
    "{front_ref}{hand_pose} "
)
_SIDE_INTRO = (
    "Image 1 shows the model. Image 2 shows the {garment} product. "
    "Three-quarter side view, about 45 degrees, of the same model "
    "wearing the {desc} from Image 2, showing its side profile and drape. {front_ref}{hand_pose} "
)
_OUTRO = CLEAN_PRODUCT + " E-commerce catalog photo, full body. {background} {extra_prompt}"

# Key: (sub_type, photo_type)
# sub_type: 'dress', 'jumpsuit', 'tops', 'bottoms', 'skirt', 'shorts'
# Placeholders: {garment}, {desc}, {leg_rule}, {shoe_rule}, {inner_top_note},
#   {hand_pose}, {collar_note}, {graphic_note}, {front_ref}, {background}, {extra_prompt}
SEEDREAM_TEMPLATES = {
    # ── DRESS ──
    ('dress', 'front'): _FRONT_INTRO + (
        "Replace the model's entire original outfit, including any trousers, with this one-piece dress. "
        "{collar_note}{graphic_note}{leg_rule} {shoe_rule} {hand_pose} "
    ) + _OUTRO,
    ('dress', 'back'): _BACK_INTRO + "{leg_rule} {shoe_rule} " + _OUTRO,
    ('dress', 'side'): _SIDE_INTRO + "{leg_rule} {shoe_rule} " + _OUTRO,

    # ── JUMPSUIT (tulum) — bacaklar kapalı, elbise bacak kuralı ALMAZ ──
    ('jumpsuit', 'front'): _FRONT_INTRO + (
        "Replace the model's entire original outfit with this one-piece jumpsuit; "
        "its legs cover the model's legs down to the ankles. "
        "{collar_note}{graphic_note}The same shoes as in Image 1. {hand_pose} "
    ) + _OUTRO,
    ('jumpsuit', 'back'): _BACK_INTRO + "The jumpsuit legs reach the ankles. " + _OUTRO,
    ('jumpsuit', 'side'): _SIDE_INTRO + "The jumpsuit legs reach the ankles. " + _OUTRO,

    # ── TOPS / OUTERWEAR ──
    ('tops', 'front'): _FRONT_INTRO + (
        "{inner_top_note}{collar_note}{graphic_note}"
        "Styled with " + DEFAULT_BOTTOMS + " and " + DEFAULT_TOPS_SHOES + ". {hand_pose} "
    ) + _OUTRO,
    ('tops', 'back'): _BACK_INTRO + (
        "Styled with " + DEFAULT_BOTTOMS + ". Show a single clean back panel. "
    ) + _OUTRO,
    ('tops', 'side'): _SIDE_INTRO + (
        "Styled with " + DEFAULT_BOTTOMS + ". "
    ) + _OUTRO,

    # ── BOTTOMS (pantolon / jean) ──
    ('bottoms', 'front'): _FRONT_INTRO + (
        "The model wears the {garment} from Image 2 in place of the bottoms in Image 1. "
        "The full trouser length is visible from waistband to hem. "
        "Styled with " + DEFAULT_TOP + " tucked in and the same shoes as in Image 1. {hand_pose} "
    ) + _OUTRO,
    ('bottoms', 'back'): _BACK_INTRO + (
        "The model wears the {garment} from Image 2 in place of the bottoms in Image 1. "
        "Styled with " + DEFAULT_TOP + ". "
    ) + _OUTRO,
    ('bottoms', 'side'): _SIDE_INTRO + (
        "The model wears the {garment} from Image 2 in place of the bottoms in Image 1. "
        "Styled with " + DEFAULT_TOP + ". "
    ) + _OUTRO,

    # ── SKIRT ──
    ('skirt', 'front'): _FRONT_INTRO + (
        "Replace the model's original bottoms, including any trousers, with this skirt. "
        "{leg_rule} Styled with " + DEFAULT_TOP + ". {shoe_rule} {hand_pose} "
    ) + _OUTRO,
    ('skirt', 'back'): _BACK_INTRO + "{leg_rule} {shoe_rule} " + _OUTRO,
    ('skirt', 'side'): _SIDE_INTRO + "{leg_rule} {shoe_rule} " + _OUTRO,

    # ── TAKIM (üst + alt tek ürün) ──
    ('coord', 'front'): _FRONT_INTRO + (
        "This product is a matching two-piece set: {set_pieces}. Replace the model's entire original outfit "
        "with both pieces worn together exactly as in Image 2. The bottom piece is separate from the top; "
        "do not merge them into a dress. {collar_note}{graphic_note}"
        "The whole outfit is visible from the neckline to the trouser hems. The same shoes as in Image 1. {hand_pose} "
    ) + _OUTRO,
    ('coord', 'back'): _BACK_INTRO + (
        "Both pieces of the matching set ({set_pieces}) are worn together; the bottom piece is separate from the top. "
    ) + _OUTRO,
    ('coord', 'side'): _SIDE_INTRO + (
        "Both pieces of the matching set ({set_pieces}) are worn together; the bottom piece is separate from the top. "
    ) + _OUTRO,

    # ── SHORTS ──
    ('shorts', 'front'): _FRONT_INTRO + (
        "Replace the model's original bottoms, including any trousers, with these shorts. "
        "{leg_rule} Styled with " + DEFAULT_TOP + " and the same shoes as in Image 1. {hand_pose} "
    ) + _OUTRO,
    ('shorts', 'back'): _BACK_INTRO + "{leg_rule} " + _OUTRO,
    ('shorts', 'side'): _SIDE_INTRO + "{leg_rule} " + _OUTRO,
}

# Back/side görünümlerde ön görünüm referansı (Image 3) varsa eklenen cümle
# Image 3 yalnız kimlik / kombin / renk tutarlılığı içindir: ürün detayı (fermuar, düğme,
# perçin) Image 3'ten alınırsa ön yüzün detayları arka görünüme taşınıyordu
FRONT_REF_SENTENCE = (
    "Image 3 is the finished front view: keep the same model, hair, outfit styling, shoes, lighting "
    "and garment color as Image 3. All garment details for this angle come only from Image 2, "
    "never from Image 3. "
)


# ═══════════════════════════════════════════════════════════════════════════
# NEGATİF PROMPTLAR
# DİKKAT: Seedream v5 Pro Edit negative_prompt kabul etmez; bu metinler
# yalnızca destekleyen modeller (nano-banana vb.) için kullanılır.
# ═══════════════════════════════════════════════════════════════════════════

_COMMON_NEG = (
    "security tag, price tag, "
    "extra fingers, fused fingers, missing fingers, deformed hands, extra hand, mutated hands, "
    "mannequin, CGI, plastic skin, blurry, low resolution"
)
SEEDREAM_NEGATIVES = {
    'dress': "pants, trousers, jeans, leggings, tights, covered legs, heavy boots, sneakers, " + _COMMON_NEG,
    'skirt': "pants, trousers, jeans, leggings, tights, covered legs, heavy boots, sneakers, " + _COMMON_NEG,
    'shorts': "long pants, trousers, jeans, leggings, " + _COMMON_NEG,
    'jumpsuit': "bare legs, shorts, " + _COMMON_NEG,
    'tops': "bare chest, exposed stomach, shirtless, bare legs, shorts visible, underwear visible, " + _COMMON_NEG,
    'bottoms': "wrong waistband, altered pockets, changed fabric texture, cropped hemline, " + _COMMON_NEG,
}



# ═══════════════════════════════════════════════════════════════════════════
# FASHN TEMPLATES (minimal — Fashn kendi try-on modelini kullanır)
# ═══════════════════════════════════════════════════════════════════════════

FASHN_VIEW_TEMPLATES = {
    'front': (
        "Professional e-commerce front view photography. "
        "Full-body model facing camera wearing garment. "
        "Standard fit, plain pattern. Clean white studio background, even lighting. "
        "Natural relaxed standing pose, arms at the sides."
    ),
    'back': (
        "Professional e-commerce back view photography. "
        "Full-body model facing away from camera showing the back of garment. "
        "Clean white studio background, even lighting. "
        "Elegant back pose, slight contrapposto."
    ),
    'side': (
        "Professional e-commerce side view photography. "
        "Full-body model turned 45 degrees showing profile of garment. "
        "Clean white studio background, even lighting."
    ),
    'detail': (
        "Professional close-up detail shot of garment texture and construction. "
        "Sharp focus on fabric, stitching, buttons. "
        "Clean white studio background."
    ),
}

FASHN_NEGATIVE = (
    "bare chest, exposed stomach, bare belly, exposed cleavage, shirtless under jacket, naked under vest, shirtless, "
    "boots under dress, heavy boots, combat boots, sneakers under dress, "
    "security tag, alarm tag, anti-theft tag, price tag, "
    "extra fingers, fused fingers, extra arms, "
    "mannequin, CGI, plastic skin, blurry"
)
