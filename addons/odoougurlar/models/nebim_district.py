# -*- coding: utf-8 -*-
"""
Nebim Bölge/İl/İlçe mapping tablosu.
sp_GetDistrict_Hamurlabs SP'sinden çekilen verilerle Odoo'daki
il/ilçe adlarını Nebim kodlarına çevirir.
"""
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Türkçe → ASCII normalize mapping (İ/I, ı/i, ş/s, ç/c farkını çözer)
_TR_NORMALIZE_MAP = str.maketrans({
    'İ': 'I', 'ı': 'i',
    'Ğ': 'G', 'ğ': 'g',
    'Ü': 'U', 'ü': 'u',
    'Ş': 'S', 'ş': 's',
    'Ö': 'O', 'ö': 'o',
    'Ç': 'C', 'ç': 'c',
})


def _normalize_turkish(text):
    """Türkçe karakterleri ASCII karşılığına çevir."""
    if not text:
        return ''
    return text.strip().translate(_TR_NORMALIZE_MAP)


class NebimDistrictMapping(models.Model):
    _name = 'odoougurlar.nebim.district'
    _description = 'Nebim Bölge/İl/İlçe Eşleştirme'
    _order = 'state_code, city_code, district_code'

    # Nebim Kodları
    country_code = fields.Char('Ülke Kodu', index=True)          # TR, RU, SA...
    state_code = fields.Char('Bölge Kodu (StateCode)', index=True)  # TR.MR, TR.AK...
    city_code = fields.Char('İl Kodu (CityCode)', index=True)       # TR.16, TR.34...
    district_code = fields.Char('İlçe Kodu (DistrictCode)', index=True) # TR.01615...

    # Nebim Açıklamaları  
    state_name = fields.Char('Bölge Adı')            # Marmara, Akdeniz...
    city_name = fields.Char('İl Adı')                # Bursa, İstanbul...
    district_name = fields.Char('İlçe Adı')          # Nilüfer, Şişli...

    # Normalize edilmiş isimler (SQL-level Türkçe-safe arama için)
    normalized_city_name = fields.Char('İl Adı (Normalize)', index=True)
    normalized_district_name = fields.Char('İlçe Adı (Normalize)', index=True)

    # Odoo eşleştirmesi (opsiyonel, hızlı lookup için)
    odoo_state_id = fields.Many2one('res.country.state', 'Odoo İl', ondelete='set null')

    def sync_from_nebim(self):
        """sp_GetDistrict_Hamurlabs SP'sini çağırarak mapping tablosunu günceller."""
        connector = self.env['odoougurlar.nebim.connector']
        
        _logger.info("Nebim İlçe verisi çekiliyor (sp_GetDistrict_Hamurlabs)...")
        try:
            result = connector.run_proc('sp_GetDistrict_Hamurlabs')
        except Exception as e:
            _logger.error("SP çağrı hatası: %s", e)
            return {'error': str(e)}
        
        if not isinstance(result, list):
            _logger.warning("Beklenmeyen SP yanıtı: %s", type(result))
            return {'error': 'Beklenmeyen yanıt formatı'}

        created = 0
        updated = 0
        
        for row in result:
            # SP'den dönen alan adları (Hamurlabs formatı)
            country = row.get('CountryCode', '') or row.get('countryCode', '') or ''
            state = row.get('StateCode', '') or row.get('stateCode', '') or ''
            city = row.get('CityCode', '') or row.get('cityCode', '') or ''
            district = row.get('DistrictCode', '') or row.get('districtCode', '') or ''
            state_nm = row.get('StateName', '') or row.get('stateName', '') or row.get('StateDescription', '') or ''
            city_nm = row.get('CityName', '') or row.get('cityName', '') or row.get('CityDescription', '') or ''
            district_nm = row.get('DistrictName', '') or row.get('districtName', '') or row.get('DistrictDescription', '') or ''
            
            if not district:
                continue
                
            existing = self.search([('district_code', '=', district)], limit=1)
            vals = {
                'country_code': country,
                'state_code': state,
                'city_code': city,
                'district_code': district,
                'state_name': state_nm,
                'city_name': city_nm,
                'district_name': district_nm,
                # Normalize edilmiş alan (Türkçe İ/I sorununu SQL-level çözer)
                'normalized_city_name': _normalize_turkish(city_nm).lower(),
                'normalized_district_name': _normalize_turkish(district_nm).lower(),
            }
            
            if existing:
                existing.write(vals)
                updated += 1
            else:
                self.create(vals)
                created += 1
        
        self.env.cr.commit()
        # Cache'i temizle — yeni veri geldi
        self._district_cache.clear()
        _logger.info("İlçe sync tamamlandı: %d yeni, %d güncellendi (toplam: %d)",
                     created, updated, created + updated)
        return {'created': created, 'updated': updated}

    # In-memory cache for district lookups (worker-scoped)
    _district_cache = {}

    @api.model
    def find_nebim_codes(self, odoo_state_name, odoo_city_name):
        """
        Odoo'daki il ve ilçe adlarını kullanarak Nebim kodlarını bulur.
        
        3 aşamalı arama:
        1. SQL ILIKE (hızlı, ama İ/I problemi olabilir)
        2. Normalize field ile SQL arama (İ→I dönüşümlü, hızlı)
        3. Sadece il bazlı eşleşme (en azından bölge/il kodu dönsün)
        
        Sonuçlar cache'lenir.
        """
        empty = {'state_code': '', 'city_code': '', 'district_code': ''}

        if not odoo_state_name and not odoo_city_name:
            return empty

        cache_key = ((odoo_state_name or '').strip().lower(),
                     (odoo_city_name or '').strip().lower())
        if cache_key in self._district_cache:
            return self._district_cache[cache_key]

         # Tablo boşluk kontrolü
        total = self.search_count([])
        if total == 0:
            _logger.error(
                "⚠ Nebim İlçe tablosu BOŞ! "
                "Ayarlar > Nebim > 'İlçe Senkronizasyonu' çalıştırın. "
                "İl/İlçe kodları gönderilemeyecek."
            )
            self._district_cache[cache_key] = empty
            return empty

        # Normalize alanları boşsa otomatik doldur (ilk kez veya güncelleme sonrası)
        empty_norm = self.search_count([('normalized_city_name', '=', False)])
        if empty_norm > 0:
            _logger.info("Normalize alanları dolduruluyor (%d kayıt)...", empty_norm)
            records = self.search([('normalized_city_name', '=', False)])
            for rec in records:
                rec.write({
                    'normalized_city_name': _normalize_turkish(rec.city_name).lower() if rec.city_name else '',
                    'normalized_district_name': _normalize_turkish(rec.district_name).lower() if rec.district_name else '',
                })
            _logger.info("Normalize alanları dolduruldu.")

        result = dict(empty)
        match = self._search_district_match(odoo_state_name, odoo_city_name)

        if match:
            result['state_code'] = match.state_code or ''
            result['city_code'] = match.city_code or ''
            result['district_code'] = match.district_code or ''
            _logger.info("Nebim İl/İlçe eşleşti: %s/%s → state=%s, city=%s, district=%s",
                         odoo_state_name, odoo_city_name,
                         result['state_code'], result['city_code'], result['district_code'])
        else:
            _logger.warning(
                "Nebim İl/İlçe eşleşMEDİ: il='%s', ilçe='%s' — "
                "Nebim tablosunda %d kayıt var ama eşleşen bulunamadı.",
                odoo_state_name, odoo_city_name, total
            )

        self._district_cache[cache_key] = result
        return result

    def _search_district_match(self, state_name, city_name):
        """İlçe eşleştirmesini 3 aşamalı arama ile yapar."""
        
        # ─── Aşama 1: ILIKE ile doğrudan arama ───
        if city_name:
            domain = [('district_name', 'ilike', city_name.strip())]
            if state_name:
                domain.append(('city_name', 'ilike', state_name.strip()))
            match = self.search(domain, limit=1)
            if match:
                return match

        # ─── Aşama 2: Normalize field ile SQL arama (İ→I dönüşümlü) ───
        norm_city = _normalize_turkish(city_name).lower() if city_name else ''
        norm_state = _normalize_turkish(state_name).lower() if state_name else ''

        if norm_city:
            domain = [('normalized_district_name', 'ilike', norm_city)]
            if norm_state:
                domain.append(('normalized_city_name', 'ilike', norm_state))
            match = self.search(domain, limit=1)
            if match:
                _logger.info("Türkçe normalize SQL eşleşme: %s/%s → %s/%s (dist_code=%s)",
                             city_name, state_name, match.district_name, match.city_name,
                             match.district_code)
                return match

        # ─── Aşama 3: Sadece il ile eşleştir (en azından bölge+il kodu dönsün) ───
        if state_name:
            # Önce normal ILIKE
            match = self.search([('city_name', 'ilike', state_name.strip())], limit=1)
            if match:
                _logger.info("İlçe bulunamadı, il bazlı eşleşme: %s → city_code=%s, state_code=%s",
                             state_name, match.city_code, match.state_code)
                return match

            # Normalize field ile
            if norm_state:
                match = self.search([('normalized_city_name', 'ilike', norm_state)], limit=1)
                if match:
                    _logger.info("Türkçe normalize il eşleşme: %s → %s (city_code=%s)",
                                 state_name, match.city_name, match.city_code)
                    return match

        return False
