# -*- coding: utf-8 -*-
"""Prompt engine for AI title and description generation."""

class PromptEngine:
    SYSTEM_PROMPT_TEMPLATE = """Sen uzman bir E-ticaret ve SEO uzmanısın. 
Görevin, sağlanan ürün verilerini kullanarak mükemmel başlıklar, açıklamalar ve SEO metadataları oluşturmak.

TRENDYOL BAŞLIK KURALLARI (Kesinlikle Uymalısın):
1. İdeal başlık uzunluğu 9-13 kelime arasıdır.
2. Maksimum 200 karakter olabilir (güvenli sınır: 100 karakter).
3. İlk harfler daima büyük olmalıdır (Title Case).
4. Başlık içinde aynı kelime tekrarlanmamalıdır.
5. Emoji, sembol veya tamamen büyük harflerle yazılmış kelimeler YASAKTIR.
6. Marka, barkod, beden ve renk bilgileri ayrı alanlara girilmeli, sadece marka başlığın en başında yer alabilir.
7. Promosyonel ifadeler YASAKTIR: "en ucuz", "kampanya", "fırsat", "şok fiyat", "garantili", "orijinal", "kargo bedava".
8. Kelimelerde kısaltma kullanılmamalıdır.

KATEGORİ BAŞLIK ŞABLONLARI:
Eğer kategori belli ise aşağıdaki formüllere sadık kal:
- Giyim: [Marka] [Cinsiyet] [Kalıp] [Ürün Tipi] [Materyal] [Renk]
- Ayakkabı: [Marka] [Cinsiyet] [Ürün Tipi] [Model] [Renk]
- Elektronik: [Marka] [Model] [Ürün Tipi] [Özellik]
- Kozmetik: [Marka] [Ürün Tipi] [Etki] [Hacim]
- Ev Tekstili: [Marka] [Boyut] [Ürün Tipi] [Materyal] [Renk]
- Aksesuar: [Marka] [Ürün Tipi] [Materyal] [Detay]

AÇIKLAMA KURALLARI:
1. Semantik HTML kullan. İzin verilen etiketler: <h3>, <p>, <ul>, <li>, <strong>.
2. Kullanıcının ürünü satın alması için fayda odaklı, ikna edici bir dil kullan.

GENEL KURALLAR:
1. Sadece verilen bilgilere ve (varsa) görsel analizine dayanarak içerik üret.
2. Üründe olmayan bir özelliği kesinlikle UYDURMA (Halüsinasyon YASAK).
"""

    CATEGORY_TEMPLATES = {
        'giyim': "{marka} {cinsiyet} {kalip} {urun_tipi} {materyal} {renk}",
        'ayakkabi': "{marka} {cinsiyet} {urun_tipi} {model} {renk}",
        'elektronik': "{marka} {model} {urun_tipi} {ozellik}",
        'kozmetik': "{marka} {urun_tipi} {etki} {hacim}",
        'ev_tekstili': "{marka} {boyut} {urun_tipi} {materyal} {renk}",
        'aksesuar': "{marka} {urun_tipi} {materyal} {detay}",
    }

    def build_system_prompt(self):
        return self.SYSTEM_PROMPT_TEMPLATE

    def build_user_prompt(self, payload, seo_keywords=None, image_included=False, mode='both'):
        import json
        prompt_parts = ["Aşağıdaki ürün verilerini kullanarak istenen formatta içerik üret:\n"]
        
        # Ürün bilgileri — Türkçe etiketler
        label_map = {
            'raw_name': 'Ürün Adı',
            'brand': 'Marka',
            'category': 'Kategori',
            'attributes': 'Nitelikler',
            'list_price': 'Fiyat (TL)',
            'default_code': 'Stok Kodu',
        }
        for key, label in label_map.items():
            value = payload.get(key)
            if value:
                if isinstance(value, dict):
                    value = json.dumps(value, ensure_ascii=False)
                prompt_parts.append(f"- {label}: {value}")
                
        if seo_keywords:
            prompt_parts.append(f"\nSEO Anahtar Kelimeleri (Bunları doğal bir şekilde kullanmaya çalış):\n- " + ", ".join(seo_keywords))
            
        category = str(payload.get('category', '')).lower()
        template = self._detect_category_template(category)
        if template:
            prompt_parts.append(f"\nBaşlık Formülü Önerisi: {template}")
            
        if image_included:
            prompt_parts.append("\nEklenen ürün görselini analiz et. Görselden çıkarabileceğin detayları içeriğe yansıt. Görselde görünmeyen özellikleri UYDURMA.")
            
        return "\n".join(prompt_parts)

    def _detect_category_template(self, category_name):
        category_name_lower = category_name.lower()
        for key, template in self.CATEGORY_TEMPLATES.items():
            if key in category_name_lower:
                return template
        return None
