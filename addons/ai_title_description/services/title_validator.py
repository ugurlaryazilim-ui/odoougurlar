# -*- coding: utf-8 -*-
"""Title validator for E-commerce titles."""
import re

class TitleValidator:
    BANNED_WORDS = [
        'en ucuz', 'kampanya', 'fırsat', 'şok fiyat', 'garantili', 
        'orijinal', 'kargo bedava', 'hızlı kargo', 'tükeniyor', 
        'süper', 'muhteşem', 'trending', 'trend', '1. kalite', 
        'ücretsiz', 'hediyeli', 'indirimli', 'en iyi', 
        'en kaliteli', 'lüks', 'premium',
        # Tekrarlayan / Basmakalıp Dolgu İfadeler (YASAK)
        'şık ve konforlu tasarım', 'şık ve konforlu', 'şık ve zarif', 
        'modern ve şık', 'şık ve modern', 'şık tasarım', 'şık', 'konforlu', 'göz alıcı',
        'vazgeçilmez', 'eşsiz', 'muazzam', 'harika', 'mükemmel'
    ]
    BANNED_CHARS = set("!@#$%^&*()_+={}[]|\\:;\"'<>,.?/~`😊😂👍❤️✨🔥🎉")

    def validate_and_fix(self, title, platform='trendyol'):
        warnings = []
        original_title = title or ""
        fixed_title = original_title

        # 0. Başlığın sonundaki "- Şık ve Konforlu", "- Şık Tasarım" gibi ekleri temizle
        fixed_title = re.sub(r'\s*[-–—]\s*(şık|konforlu|şık ve konforlu|şık ve konforlu tasarım|zarif|modern|göz alıcı).*$', '', fixed_title, flags=re.IGNORECASE)
        
        # 1. Remove emojis and symbols
        cleaned_chars = []
        has_banned_chars = False
        for char in fixed_title:
            if char in self.BANNED_CHARS:
                has_banned_chars = True
            else:
                cleaned_chars.append(char)
        if has_banned_chars:
            fixed_title = "".join(cleaned_chars)
            warnings.append("Yasaklı karakterler veya emojiler temizlendi.")

        # 2. Banned words filtering
        fixed_title_lower = self.tr_lower(fixed_title)
        for banned_word in self.BANNED_WORDS:
            if banned_word in fixed_title_lower:
                pattern = re.compile(r'\b' + re.escape(banned_word) + r'\b', re.IGNORECASE)
                if pattern.search(fixed_title):
                    fixed_title = pattern.sub('', fixed_title)
                    warnings.append(f"Basmakalıp/yasaklı kelime silindi: {banned_word}")

        # 3. Clean multiple spaces and stray dashes
        fixed_title = re.sub(r'\s*-\s*$', '', fixed_title)
        fixed_title = " ".join(fixed_title.split())

        # 4. Repeated words
        words = fixed_title.split()
        seen = set()
        dedup_words = []
        for w in words:
            wl = self.tr_lower(w)
            if wl not in seen:
                seen.add(wl)
                dedup_words.append(w)
            else:
                warnings.append(f"Tekrarlanan kelime çıkarıldı: {w}")
        fixed_title = " ".join(dedup_words)

        # 5. Title Case
        fixed_title = self.tr_title_case(fixed_title)

        # 6. Length and word count checks
        char_count = len(fixed_title)
        word_count = len(fixed_title.split())

        if char_count > 100:
            fixed_title = fixed_title[:100].rsplit(' ', 1)[0]
            warnings.append("Başlık 100 karakter sınırına göre kırpıldı.")
            char_count = len(fixed_title)
            word_count = len(fixed_title.split())

        score = 100
        if platform == 'trendyol':
            if not (9 <= word_count <= 13):
                warnings.append("Kelime sayısı ideal aralığın (9-13) dışında.")
                score -= 10
            
            score -= len(warnings) * 5

        return {
            'valid': len(warnings) == 0,
            'score': max(0, score),
            'warnings': warnings,
            'original_title': original_title,
            'fixed_title': fixed_title,
            'char_count': char_count,
            'word_count': word_count
        }

    @staticmethod
    def tr_lower(text):
        if not text:
            return ""
        text = text.replace('I', 'ı').replace('İ', 'i')
        return text.lower()

    @staticmethod
    def tr_upper(text):
        if not text:
            return ""
        text = text.replace('i', 'İ').replace('ı', 'I')
        return text.upper()

    @staticmethod
    def tr_title_case(text):
        if not text:
            return ""
        words = text.split()
        title_words = []
        for word in words:
            if not word:
                continue
            first_char = TitleValidator.tr_upper(word[0])
            rest = TitleValidator.tr_lower(word[1:])
            title_words.append(first_char + rest)
        return " ".join(title_words)
