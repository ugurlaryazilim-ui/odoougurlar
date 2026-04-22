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

    @api.model
    def find_nebim_codes(self, odoo_state_name, odoo_city_name):
        """
        Odoo'daki il ve ilçe adlarını kullanarak Nebim kodlarını bulur.
        Sonuçlar cache'lenir — aynı il/ilçe tekrar sorgulanmaz.
        """
        empty = {'state_code': '', 'city_code': '', 'district_code': ''}

        if not odoo_state_name and not odoo_city_name:
            return empty

        cache_key = ((odoo_state_name or '').strip().lower(),
                     (odoo_city_name or '').strip().lower())
        if cache_key in self._district_cache:
            return self._district_cache[cache_key]

        result = dict(empty)

        # Önce ilçe adıyla ara (en spesifik)
        if odoo_city_name:
            domain = [('district_name', 'ilike', odoo_city_name.strip())]
            if odoo_state_name:
                domain.append(('city_name', 'ilike', odoo_state_name.strip()))

            match = self.search(domain, limit=1)
            if match:
                result['state_code'] = match.state_code or ''
                result['city_code'] = match.city_code or ''
                result['district_code'] = match.district_code or ''
                self._district_cache[cache_key] = result
                return result

        # İlçe bulunamadıysa sadece il adıyla ara
        if odoo_state_name:
            match = self.search([('city_name', 'ilike', odoo_state_name.strip())], limit=1)
            if match:
                result['state_code'] = match.state_code or ''
                result['city_code'] = match.city_code or ''
                result['district_code'] = match.district_code or ''
                self._district_cache[cache_key] = result
                return result

        self._district_cache[cache_key] = result
        return result
