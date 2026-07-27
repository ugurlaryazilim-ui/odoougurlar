from odoo import api, fields, models

class MarketplaceQuestionAnswer(models.Model):
    _name = 'marketplace.question.answer'
    _description = 'Pazaryeri Soru Cevap Geçmişi'
    _order = 'sent_date desc'

    question_id = fields.Many2one('marketplace.question', string='Soru', required=True, ondelete='cascade')
    answer_text = fields.Text('Cevap', required=True)
    answer_type = fields.Selection([
        ('sent', 'Gönderildi'), 
        ('rejected', 'Reddedildi'), 
        ('draft', 'Taslak')
    ], string='Cevap Tipi', default='sent', required=True)
    
    external_answer_id = fields.Char('Pazaryeri Cevap ID')
    rejection_reason = fields.Text('Red Sebebi')
    sent_date = fields.Datetime('Gönderim Tarihi', default=fields.Datetime.now)
    sent_by = fields.Many2one('res.users', string='Gönderen', default=lambda self: self.env.user)
