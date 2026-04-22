import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class TaxMapping(models.Model):
    _name = 'odoougurlar.tax.mapping'
    _description = 'Vergi No / Cari Eşleştirmeleri'
    _order = 'name'

    name = fields.Char(string='Pazaryeri Vergi Dairesi Adı', required=True, help='Örn: osmangazi')
    nebim_tax_office_code = fields.Char(string='Nebim Vergi Dairesi Kodu', required=True, help='Örn: 016251')
    nebim_tax_office_name = fields.Char(string='Nebim Vergi Dairesi Adı', help='Örn: OSMANGAZİ VERGİ DAİRESİ')
    
    _sql_constraints = [
        ('name_unique', 'unique(name)', 'Bu vergi dairesi için zaten bir eşleştirme var!')
    ]

    @api.model
    def sync_from_nebim(self):
        """Nebim'den vergi dairesi listesini çeker ve eşleştirme tablosunu günceller."""
        connector = self.env['odoougurlar.nebim.connector']
        
        _logger.info("Nebim Vergi Dairesi verisi çekiliyor...")
        try:
            # Nebim'de sp_GetTaxOffice veya benzeri SP dene
            sp_names = ['sp_GetTaxOffice_Hamurlabs', 'sp_GetTaxOffice', 'sp_Get_TaxOffice']
            result = None
            used_sp = None
            for sp in sp_names:
                try:
                    result = connector.run_proc(sp)
                    if result:
                        used_sp = sp
                        break
                except Exception:
                    continue
            
            if not result:
                return {'error': 'Nebim\'de vergi dairesi SP\'si bulunamadı. Manuel olarak ekleyebilirsiniz.'}
            
            items = result if isinstance(result, list) else [result]
            
            created = 0
            updated = 0
            
            for row in items:
                code = (row.get('TaxOfficeCode', '') or row.get('Code', '') or '').strip()
                name = (row.get('TaxOfficeDescription', '') or row.get('TaxOfficeName', '') or row.get('Description', '') or '').strip()
                
                if not code or not name:
                    continue
                
                # Kısa ad oluştur (büyük harflerden küçük harfe, VERGİ DAİRESİ kaldır)
                short_name = name.replace('VERGİ DAİRESİ', '').replace('VERGI DAIRESI', '').strip().lower()
                
                existing = self.search([('nebim_tax_office_code', '=', code)], limit=1)
                if existing:
                    existing.write({
                        'nebim_tax_office_name': name,
                    })
                    updated += 1
                else:
                    try:
                        self.create({
                            'name': short_name or name.lower(),
                            'nebim_tax_office_code': code,
                            'nebim_tax_office_name': name,
                        })
                        created += 1
                    except Exception as e:
                        _logger.warning("Vergi dairesi oluşturma hatası (%s - %s): %s", code, name, e)
            
            _logger.info("Vergi dairesi sync tamamlandı (SP: %s): %d yeni, %d güncellendi", used_sp, created, updated)
            return {'created': created, 'updated': updated, 'sp_used': used_sp}
            
        except Exception as e:
            _logger.error("Vergi dairesi sync hatası: %s", e)
            return {'error': str(e)}
