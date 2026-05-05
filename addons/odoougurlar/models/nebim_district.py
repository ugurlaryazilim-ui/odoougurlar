# -*- coding: utf-8 -*-
"""
Nebim Bölge/İl/İlçe mapping tablosu.
sp_GetDistrict_Hamurlabs SP'sinden çekilen verilerle Odoo'daki
il/ilçe adlarını Nebim kodlarına çevirir.
"""
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


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
            }
            
            if existing:
                existing.write(vals)
                updated += 1
            else:
                self.create(vals)
                created += 1
        
        self.env.cr.commit()
        _logger.info("İlçe sync tamamlandı: %d yeni, %d güncellendi", created, updated)
        return {'created': created, 'updated': updated}

    # In-memory cache for district lookups (worker-scoped)
    _district_cache = {}

    @staticmethod
    def _normalize_turkish(text):
        """Türkçe karakterleri normalize et — ILIKE uyumsuzluğunu çöz."""
        if not text:
            return ''
        # Türkçe → ASCII-benzeri (arama kolaylığı için)
        tr_map = {
            'İ': 'I', 'ı': 'i',
            'Ğ': 'G', 'ğ': 'g',
            'Ü': 'U', 'ü': 'u',
            'Ş': 'S', 'ş': 's',
            'Ö': 'O', 'ö': 'o',
            'Ç': 'C', 'ç': 'c',
        }
        result = text.strip()
        for tr_char, ascii_char in tr_map.items():
            result = result.replace(tr_char, ascii_char)
        return result

    @api.model
    def find_nebim_codes(self, odoo_state_name, odoo_city_name):
        """
        Odoo'daki il ve ilçe adlarını kullanarak Nebim kodlarını bulur.
        Türkçe karakter uyumsuzluğunu handle eder (İ/I, ı/i, ş/s, vb.)
        Sonuçlar cache'lenir — aynı il/ilçe tekrar sorgulanmaz.
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

        result = dict(empty)

        # Arama stratejisi: 3 aşamalı
        # 1. Normal ILIKE (tam Türkçe karakter eşleşmesi)
        # 2. Tüm kayıtlarda Python-level Türkçe normalize karşılaştırma
        # 3. Sadece il ile eşleştirme (ilçe kodu en az il kodu dönsün)

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

        # ─── Aşama 2: Türkçe normalize arama (İ/I farkı çözümü) ───
        norm_city = self._normalize_turkish(city_name) if city_name else ''
        norm_state = self._normalize_turkish(state_name) if state_name else ''

        if norm_city:
            # Nebim verilerini çek ve Python'da normalize karşılaştır
            candidates = self.search([])  # tüm kayıtlar (cache'li olduğu için hızlı)
            for rec in candidates:
                rec_district = self._normalize_turkish(rec.district_name)
                rec_city = self._normalize_turkish(rec.city_name)
                if norm_city.lower() in rec_district.lower():
                    if not norm_state or norm_state.lower() in rec_city.lower():
                        _logger.info("Türkçe normalize eşleşme bulundu: %s/%s → %s/%s",
                                     city_name, state_name, rec.district_name, rec.city_name)
                        return rec

        # ─── Aşama 3: Sadece il ile eşleştir (en az il kodu dönsün) ───
        if state_name:
            match = self.search([('city_name', 'ilike', state_name.strip())], limit=1)
            if match:
                _logger.info("İlçe bulunamadı, il bazlı eşleşme: %s → city_code=%s",
                             state_name, match.city_code)
                return match

            # Türkçe normalize il araması
            if norm_state:
                candidates = self.search([])
                for rec in candidates:
                    if norm_state.lower() in self._normalize_turkish(rec.city_name).lower():
                        _logger.info("Türkçe normalize il eşleşme: %s → %s",
                                     state_name, rec.city_name)
                        return rec

        return False

