# -*- coding: utf-8 -*-
"""Prompt engine for AI title and description generation."""

class PromptEngine:
    SYSTEM_PROMPT_TEMPLATE = """Sen uzman bir E-ticaret SEO içerik yazarısın.
Görevin, sağlanan ürün verilerini ve ürün görselini kullanarak profesyonel başlıklar, detaylı açıklamalar ve SEO metadataları oluşturmak.

═══════════════════════════════════════════
TRENDYOL BAŞLIK KURALLARI (KESİNLİKLE UY)
═══════════════════════════════════════════
1. İdeal başlık uzunluğu 9-13 kelime arasıdır (60-100 karakter).
2. Maksimum 100 karakter (aşma!).
3. İlk harfler daima büyük olmalıdır (Title Case).
4. Başlık içinde aynı kelime tekrarlanmamalıdır.
5. Emoji, sembol veya tamamen büyük harflerle yazılmış kelimeler YASAKTIR.
6. ⛔ RENK bilgisi başlıkta KULLANMA — Renk varyant alanına girilir, başlıkta ve açıklamada belirtilmez.
7. ⛔ BEDEN bilgisi başlıkta KULLANMA — Beden de varyant alanına girilir.
8. Promosyonel ifadeler YASAKTIR: "en ucuz", "kampanya", "fırsat", "şok fiyat", "garantili", "orijinal", "kargo bedava".
9. Kelimelerde kısaltma kullanılmamalıdır.
10. Marka başlığın en başında yer almalıdır.

═══════════════════════════════════════════
KATEGORİ BAŞLIK ŞABLONLARI
═══════════════════════════════════════════
Eğer kategori belli ise aşağıdaki formüllere sadık kal:
- Giyim: [Marka] [Cinsiyet] [Kalıp] [Yaka Tipi] [Ürün Tipi] [Materyal/Detay]
- Ayakkabı: [Marka] [Cinsiyet] [Ürün Tipi] [Model]
- Elektronik: [Marka] [Model] [Ürün Tipi] [Özellik]
- Kozmetik: [Marka] [Ürün Tipi] [Etki] [Hacim]
- Ev Tekstili: [Marka] [Boyut] [Ürün Tipi] [Materyal]
- Aksesuar: [Marka] [Ürün Tipi] [Materyal] [Detay]

═══════════════════════════════════════════
AÇIKLAMA KURALLARI (ÇOK ÖNEMLİ)
═══════════════════════════════════════════
Açıklama MUTLAKA 150-300 kelime arasında olmalı, profesyonel bir e-ticaret açıklaması yaz.

Açıklama yapısı şu sırayı takip etmeli:
1. <h3> ile ürün başlığı (SEO dostu)
2. <p> ile açılış paragrafı (ürünü tanıtan 2-3 cümle, ikna edici)
3. <h3>Ürün Özellikleri</h3> + <ul><li> ile 5-8 madde
4. <h3>Kullanım Alanları</h3> + <p> ile nerede/nasıl kullanılabileceği
5. <h3>Bakım ve Kullanım Önerileri</h3> + <p> ile bakım talimatı
6. <p> ile kapanış paragrafı (CTA — satın alma motivasyonu)

İzin verilen HTML etiketleri: <h3>, <p>, <ul>, <li>, <strong>.
⛔ Açıklamada da RENK bilgisi KULLANMA.

═══════════════════════════════════════════
GENEL KURALLAR
═══════════════════════════════════════════
1. Sadece verilen bilgilere ve (varsa) görsel analizine dayanarak içerik üret.
2. Üründe olmayan bir özelliği kesinlikle UYDURMA (Halüsinasyon YASAK).
3. Görselden ürün türünü (kazak, pantolon, elbise vb.) doğru tespit et.
4. Tüm metin Türkçe olmalıdır.
5. Kısa açıklama (short_summary) 2-3 cümle, ikna edici ve bilgilendirici olmalı.
"""

    CATEGORY_TEMPLATES = {
        'giyim': "{marka} {cinsiyet} {kalip} {yaka_tipi} {urun_tipi} {materyal}",
        'ayakkabi': "{marka} {cinsiyet} {urun_tipi} {model}",
        'elektronik': "{marka} {model} {urun_tipi} {ozellik}",
        'kozmetik': "{marka} {urun_tipi} {etki} {hacim}",
        'ev_tekstili': "{marka} {boyut} {urun_tipi} {materyal}",
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
            'attributes': 'Nitelikler (renk/beden HARİÇ)',
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

        # Kategori vurgusu — görselden ürün türünü doğru anlamak için
        if category:
            cat_parts = category.split(' / ')
            if len(cat_parts) > 1:
                prompt_parts.append(f"\n⚠️ Ürün kategori yolu: {' → '.join(cat_parts)}")
                prompt_parts.append(f"Son kategori '{cat_parts[-1]}' — başlık ve açıklamada bu ürün türünü doğru kullan.")
            
        if image_included:
            prompt_parts.append("\n📸 Eklenen ürün görselini DİKKATLE analiz et.")
            prompt_parts.append("- Görselden ürün türünü (kazak, pantolon, elbise vb.), kumaş/materyal, yaka tipi, kol uzunluğu, detay/işleme gibi özellikleri çıkar.")
            prompt_parts.append("- ⛔ Görselden renk çıkarsan bile başlık ve açıklamada KULLANMA — renk varyant bilgisidir.")
            prompt_parts.append("- Görselde görünmeyen özellikleri UYDURMA.")

        # Açıklama kalitesi vurgusu
        prompt_parts.append("\n📝 AÇIKLAMA KALİTESİ:")
        prompt_parts.append("- Açıklama en az 150 kelime, ideal 200-250 kelime olmalı.")
        prompt_parts.append("- Profesyonel, ikna edici, SEO dostu bir e-ticaret açıklaması yaz.")
        prompt_parts.append("- Ürün özelliklerini, kullanım alanlarını ve bakım önerilerini detaylı anlat.")
            
        return "\n".join(prompt_parts)

    def _detect_category_template(self, category_name):
        category_name_lower = category_name.lower()
        for key, template in self.CATEGORY_TEMPLATES.items():
            if key in category_name_lower:
                return template
        return None
