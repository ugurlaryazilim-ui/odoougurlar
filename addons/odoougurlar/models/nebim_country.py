# -*- coding: utf-8 -*-
"""
Nebim Ülke mapping tablosu.
sp_GetCountry_Hamurlabs SP'sinden çekilen verilerle 
Odoo ülke kodlarını Nebim ülke kodlarına çevirir.
"""
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class NebimCountryMapping(models.Model):
    _name = 'odoougurlar.nebim.country'
    _description = 'Nebim Ülke Eşleştirme'
    _order = 'nebim_code'

    nebim_code = fields.Char('Nebim Ülke Kodu', required=True, index=True)      # TR, SA, AZ...
    nebim_name = fields.Char('Nebim Ülke Adı')            # Türkiye, Suudi Arabistan...
    iso_code = fields.Char('ISO Kodu (2)', index=True)    # TR, SA, AZ...
    
    # Odoo eşleştirmesi
    odoo_country_id = fields.Many2one('res.country', 'Odoo Ülke', ondelete='set null')

    def sync_from_nebim(self):
        """sp_GetCountry_Hamurlabs SP'sini çağırarak ülke tablosunu günceller."""
        connector = self.env['odoougurlar.nebim.connector']
        
        _logger.info("Nebim Ülke verisi çekiliyor (sp_GetCountry_Hamurlabs)...")
        try:
            result = connector.run_proc('sp_GetCountry_Hamurlabs')
        except Exception as e:
            _logger.error("SP çağrı hatası: %s", e)
            return {'error': str(e)}
        
        if not isinstance(result, list):
            _logger.warning("Beklenmeyen SP yanıtı: %s", type(result))
            return {'error': 'Beklenmeyen yanıt formatı'}

        created = 0
        updated = 0
        auto_mapped = 0
        
        for row in result:
            code = row.get('CountryCode', '') or row.get('countryCode', '') or ''
            name = row.get('CountryDescription', '') or row.get('CountryName', '') or row.get('countryName', '') or ''
            
            if not code:
                continue
            
            existing = self.search([('nebim_code', '=', code)], limit=1)
            vals = {
                'nebim_code': code,
                'nebim_name': name,
                'iso_code': code,  # Nebim genelde ISO 2-letter code kullanır
            }
            
            if existing:
                existing.write(vals)
                updated += 1
                rec = existing
            else:
                rec = self.create(vals)
                created += 1
            
            # Otomatik Odoo eşleştirmesi dene
            if not rec.odoo_country_id and code:
                odoo_country = self.env['res.country'].search([('code', '=', code.upper())], limit=1)
                if odoo_country:
                    rec.write({'odoo_country_id': odoo_country.id})
                    auto_mapped += 1
        
        self.env.cr.commit()
        _logger.info("Ülke sync tamamlandı: %d yeni, %d güncellendi, %d otomatik eşleştirildi", created, updated, auto_mapped)
        return {'created': created, 'updated': updated, 'auto_mapped': auto_mapped}

    @api.model
    def find_nebim_country(self, odoo_country_id):
        """Odoo ülke ID'sini Nebim ülke koduna çevirir."""
        if not odoo_country_id:
            return 'TR'
        
        match = self.search([('odoo_country_id', '=', odoo_country_id)], limit=1)
        if match:
            return match.nebim_code
        
        # Eşleşme yoksa Odoo ülke kodunu dene
        country = self.env['res.country'].browse(odoo_country_id)
        if country and country.code:
            return country.code
        
        return 'TR'
