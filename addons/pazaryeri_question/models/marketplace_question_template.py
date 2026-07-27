from odoo import fields, models

class MarketplaceQuestionTemplate(models.Model):
    _name = 'marketplace.question.template'
    _description = 'Pazaryeri Cevap Şablonu'
    _order = 'use_count desc, name'

    name = fields.Char('Şablon Adı', required=True)
    template_text = fields.Text('Şablon Cevap', required=True)
    category = fields.Selection([
        ('kargo', 'Kargo'), 
        ('urun', 'Ürün'), 
        ('iade', 'İade'), 
        ('genel', 'Genel'), 
        ('beden', 'Beden/Ölçü'), 
        ('teslimat', 'Teslimat')
    ], string='Kategori', default='genel', required=True)
    
    marketplace_type = fields.Selection([
        ('all', 'Tümü'), 
        ('trendyol', 'Trendyol'), 
        ('hepsiburada', 'Hepsiburada'), 
        ('pttavm', 'PttAVM'), 
        ('n11', 'N11'), 
        ('pazarama', 'Pazarama'), 
        ('shopify', 'Shopify')
    ], string='Pazaryeri', default='all')
    
    use_count = fields.Integer('Kullanım Sayısı', default=0, readonly=True)
    active = fields.Boolean('Aktif', default=True)
