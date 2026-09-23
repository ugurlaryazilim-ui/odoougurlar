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

SKIRT_KW = ['etek', 'skirt']

SHORTS_KW = ['şort', 'sort', 'shorts', 'bermuda']

BOTTOMS_SAFE_KW = [
    'pantolon', 'jean', 'jeans', 'tayt', 'eşofman altı',
    'alt giyim', 'bermuda', 'capri', 'jogger',
]

BOTTOMS_RISKY_KW = ['şort', 'sort', 'etek']

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

# Türkçe false positive temizleme listesi (tişört içinde şort vb.)
FALSE_POSITIVE_CLEAN_KW = ['tişört', 'tisort', 'tısört', 'tısort', 'tshirt', 't-shirt', 't shirt']


# ═══════════════════════════════════════════════════════════════════════════
# SEEDREAM PROMPT ŞABLONLARI
# Her şablon: 40-65 kelime hedef, < 500 karakter
# Seedream v5 Pro optimal: 2-4 cümle, < 50 kelime, doğal dil
# ═══════════════════════════════════════════════════════════════════════════

# Bacak kuralları — kıyafet uzunluğuna göre
LEG_RULES = {
    'dress': {
        'mini':    'Natural bare legs visible from mid-thigh down to shoes.',
        'midi':    'Natural bare legs visible from mid-calf down to shoes.',
        'knee':    'Natural bare legs visible from knee down to shoes.',
        'maxi':    'Dress hemline near ankles, only feet and shoes visible.',
        'default': 'Natural bare legs below dress hemline.',
    },
    'skirt': {
        'mini':    'Natural bare legs visible from mid-thigh down to shoes.',
        'midi':    'Natural bare legs visible from mid-calf down to shoes.',
        'knee':    'Natural bare legs visible from knee down to shoes.',
        'maxi':    'Skirt hemline near ankles, only feet and shoes visible.',
        'default': 'Natural bare legs below skirt hemline.',
    },
    'shorts': {
        'default': 'Natural bare legs below shorts hemline.',
    },
}

# El pozları — view'e göre
HAND_POSES = {
    'front': 'One hand resting on hip, other arm relaxed at side.',
    'back':  '',
    'side':  'Arms relaxed naturally at sides.',
    'detail': '',
}


# ── SEEDREAM PROMPT TEMPLATES ──
# Key: (sub_type, photo_type)
# sub_type: 'dress', 'tops', 'bottoms', 'skirt', 'shorts'
# photo_type: 'front', 'back', 'side', 'detail'
# Placeholders: {color}, {fabric}, {garment_type}, {leg_rule}, {hand_pose},
#               {graphic_note}, {collar_note}, {extra_prompt}

SEEDREAM_TEMPLATES = {
    # ══════════════════════════════════════════
    # DRESS — FRONT
    # ══════════════════════════════════════════
    ('dress', 'front'): (
        "Dress the model in Figure 2 with the {garment_type} from Figure 1. "
        "This is a {color} {fabric} {garment_type}. "
        "Replace both top and bottom of Figure 2 with this {garment_type}. "
        "{leg_rule} "
        "Keep face, hair, body proportions from Figure 2. "
        "Professional e-commerce photo, white studio, even lighting. "
        "{hand_pose} "
        "{collar_note}{graphic_note}"
        "Remove any store tags or security pins from garment. "
        "{extra_prompt}"
    ),
    # DRESS — BACK
    ('dress', 'back'): (
        "Back view of the model from Figure 3 wearing the {garment_type} from Figure 1. "
        "Model facing away from camera, showing back of this {color} {fabric} {garment_type}. "
        "Same model, hair, shoes as Figure 3. {leg_rule} "
        "White studio background, even lighting. "
        "Remove any store tags. "
        "{extra_prompt}"
    ),
    # DRESS — SIDE
    ('dress', 'side'): (
        "45-degree side view of the model from Figure 3 wearing the {garment_type} from Figure 1. "
        "Show side profile of this {color} {fabric} {garment_type}. "
        "Same model, hair, shoes as Figure 3. {leg_rule} "
        "White studio background, even lighting. "
        "{extra_prompt}"
    ),

    # ══════════════════════════════════════════
    # TOPS / OUTERWEAR — FRONT
    # ══════════════════════════════════════════
    ('tops', 'front'): (
        "Dress the model in Figure 2 with the {garment_type} from Figure 1. "
        "This is a {color} {fabric} {garment_type}. "
        "Replace upper clothing of Figure 2 with Figure 1. "
        "Model wears dark tailored trousers covering entire legs down to shoes. "
        "Keep face, hair, shoes from Figure 2. "
        "Professional e-commerce photo, white studio, even lighting. "
        "{hand_pose} "
        "{collar_note}{graphic_note}"
        "Remove any store tags or security pins from garment. "
        "{extra_prompt}"
    ),
    # TOPS — BACK
    ('tops', 'back'): (
        "Back view of the model from Figure 3 wearing the {garment_type} from Figure 1. "
        "Model facing away from camera, showing back of this {color} {fabric} {garment_type}. "
        "Same dark trousers and shoes as Figure 3. "
        "Show single back panel only, ignore any hanger fold-over at shoulders. "
        "White studio background, even lighting. "
        "Remove any store tags. "
        "{extra_prompt}"
    ),
    # TOPS — SIDE
    ('tops', 'side'): (
        "45-degree side view of the model from Figure 3 wearing the {garment_type} from Figure 1. "
        "Same inner top, dark trousers and shoes as Figure 3. "
        "Show collar, sleeves, pockets from side angle. "
        "White studio background, even lighting. "
        "{extra_prompt}"
    ),

    # ══════════════════════════════════════════
    # BOTTOMS (PANTOLON/JEAN) — FRONT
    # ══════════════════════════════════════════
    ('bottoms', 'front'): (
        "Dress the model in Figure 2 with the {garment_type} from Figure 1. "
        "This is {color} {fabric} {garment_type}. "
        "Replace bottom clothing of Figure 2 with Figure 1. "
        "Full trouser length visible from waist to ankle hem at shoes. "
        "Neutral fitted top on upper body. Keep face, hair from Figure 2. "
        "Professional e-commerce photo, white studio, even lighting. "
        "{hand_pose} "
        "Remove any store tags. "
        "{extra_prompt}"
    ),
    # BOTTOMS — BACK
    ('bottoms', 'back'): (
        "Back view of the model from Figure 3 wearing the {garment_type} from Figure 1. "
        "Model facing away, showing back of this {color} {fabric} {garment_type}. "
        "Same top and shoes as Figure 3. Back waistband clean with no extra hardware. "
        "White studio background, even lighting. "
        "Remove any store tags. "
        "{extra_prompt}"
    ),
    # BOTTOMS — SIDE
    ('bottoms', 'side'): (
        "45-degree side view of the model from Figure 3 wearing the {garment_type} from Figure 1. "
        "Same top and shoes as Figure 3. "
        "Show waistband, pockets, fabric drape from side angle. "
        "White studio background, even lighting. "
        "{extra_prompt}"
    ),

    # ══════════════════════════════════════════
    # SKIRT — FRONT
    # ══════════════════════════════════════════
    ('skirt', 'front'): (
        "Dress the model in Figure 2 with the skirt from Figure 1. "
        "This is a {color} {fabric} skirt. "
        "Replace bottom clothing of Figure 2 with this skirt only. "
        "{leg_rule} "
        "Neutral fitted top on upper body. Keep face, hair, shoes from Figure 2. "
        "Professional e-commerce photo, white studio, even lighting. "
        "{hand_pose} "
        "Remove any store tags. "
        "{extra_prompt}"
    ),
    # SKIRT — BACK
    ('skirt', 'back'): (
        "Back view of the model from Figure 3 wearing the skirt from Figure 1. "
        "Model facing away, showing back of this {color} {fabric} skirt. "
        "Same top and shoes as Figure 3. {leg_rule} "
        "White studio background, even lighting. "
        "Remove any store tags. "
        "{extra_prompt}"
    ),
    # SKIRT — SIDE
    ('skirt', 'side'): (
        "45-degree side view of the model from Figure 3 wearing the skirt from Figure 1. "
        "Same top and shoes as Figure 3. {leg_rule} "
        "White studio background, even lighting. "
        "{extra_prompt}"
    ),

    # ══════════════════════════════════════════
    # SHORTS — FRONT
    # ══════════════════════════════════════════
    ('shorts', 'front'): (
        "Dress the model in Figure 2 with the shorts from Figure 1. "
        "This is {color} {fabric} shorts. "
        "Replace bottom clothing of Figure 2 with these shorts only. "
        "Natural bare legs below shorts hemline. "
        "Neutral fitted top on upper body. Keep face, hair, shoes from Figure 2. "
        "Professional e-commerce photo, white studio, even lighting. "
        "{hand_pose} "
        "Remove any store tags. "
        "{extra_prompt}"
    ),
    # SHORTS — BACK
    ('shorts', 'back'): (
        "Back view of the model from Figure 3 wearing the shorts from Figure 1. "
        "Model facing away, showing back of these {color} {fabric} shorts. "
        "Same top and shoes as Figure 3. Natural bare legs below shorts. "
        "White studio background, even lighting. "
        "Remove any store tags. "
        "{extra_prompt}"
    ),
    # SHORTS — SIDE
    ('shorts', 'side'): (
        "45-degree side view of the model from Figure 3 wearing the shorts from Figure 1. "
        "Same top and shoes as Figure 3. Natural bare legs below shorts. "
        "White studio background, even lighting. "
        "{extra_prompt}"
    ),
}

# Detail view — tüm kategoriler için ortak
SEEDREAM_DETAIL_TEMPLATE = (
    "Close-up detail shot of the {garment_type} from Figure 1 being worn by the model. "
    "Sharp focus on fabric texture, stitching, and construction details. "
    "Model wearing complete outfit. White studio background. "
    "Remove any store tags. "
    "{extra_prompt}"
)


# ═══════════════════════════════════════════════════════════════════════════
# SEEDREAM NEGATİF PROMPTLARI
# Kategori-bazlı, max 20 terim (Seedream optimal: 15-25 spesifik terim)
# Kural: "no" kelimesi KULLANMA, sadece artifact listele
# ═══════════════════════════════════════════════════════════════════════════

SEEDREAM_NEGATIVES = {
    'dress': (
        "pants underneath, trousers underneath, leggings underneath, jeans underneath, "
        "tights under dress, double-layered bottoms, "
        "security tag, alarm pin, price tag, "
        "extra fingers, fused fingers, extra arms, missing fingers, "
        "mannequin, CGI, plastic skin, blurry, low resolution"
    ),
    'skirt': (
        "pants underneath, trousers underneath, leggings underneath, "
        "tights under skirt, double-layered bottoms, "
        "security tag, alarm pin, price tag, "
        "extra fingers, fused fingers, extra arms, missing fingers, "
        "mannequin, CGI, plastic skin, blurry, low resolution"
    ),
    'shorts': (
        "long pants underneath, trousers underneath, leggings underneath, "
        "security tag, alarm pin, price tag, "
        "extra fingers, fused fingers, extra arms, missing fingers, "
        "mannequin, CGI, plastic skin, blurry, low resolution"
    ),
    'tops': (
        "bare legs, exposed thighs, shorts visible, underwear visible, "
        "missing pants, "
        "security tag, alarm pin, price tag, "
        "extra fingers, fused fingers, extra arms, missing fingers, "
        "mannequin, CGI, plastic skin, blurry, low resolution"
    ),
    'bottoms': (
        "wrong waistband, altered pockets, changed fabric texture, "
        "cropped hemline, "
        "security tag, alarm pin, price tag, "
        "extra fingers, fused fingers, extra arms, missing fingers, "
        "mannequin, CGI, plastic skin, blurry, low resolution"
    ),
}

# Fotorealizm kalite cümlesi — prompt sonuna eklenir (tek kısa cümle)
QUALITY_SUFFIX = "Hasselblad editorial photography, natural human skin, seamless white cyclorama."


# ═══════════════════════════════════════════════════════════════════════════
# FASHN TEMPLATES (minimal — Fashn kendi try-on modelini kullanır)
# ═══════════════════════════════════════════════════════════════════════════

FASHN_VIEW_TEMPLATES = {
    'front': (
        "Professional e-commerce front view photography. "
        "Full-body model facing camera wearing garment. "
        "Standard fit, plain pattern. Clean white studio background, even lighting. "
        "Confident fashion pose, one hand on hip."
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
    "security tag, alarm tag, anti-theft tag, price tag, "
    "extra fingers, fused fingers, extra arms, "
    "mannequin, CGI, plastic skin, blurry"
)


# ═══════════════════════════════════════════════════════════════════════════
# FASHN CATEGORY MAPPING
# ═══════════════════════════════════════════════════════════════════════════

FASHN_CATEGORY_MAP = {
    'tops': 'tops',
    'bottoms': 'bottoms',
    'dress': 'full-body',
    'outerwear': 'tops',
    'knitwear': 'tops',
    'one_piece': 'full-body',
    'full-body': 'full-body',
}

GARMENT_TYPE_TO_FASHN = {
    # Üst giyim / Dış giyim
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
    # Tam vücut
    'elbise': 'full-body', 'tulum': 'full-body', 'overall': 'full-body',
    'dress': 'full-body', 'jumpsuit': 'full-body', 'romper': 'full-body',
    'gown': 'full-body', 'abiye': 'full-body',
}
