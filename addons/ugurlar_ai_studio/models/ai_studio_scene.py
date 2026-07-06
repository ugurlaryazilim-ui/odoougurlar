from odoo import models, fields

class AiStudioScene(models.Model):
    _name = 'ai.studio.scene'
    _description = 'AI Stüdyo Çekim Sahnesi / Konsepti'
    _order = 'sequence, name'

    name = fields.Char(string='Sahne Adı', required=True, translate=True)
    sequence = fields.Integer(string='Sıra', default=10)
    active = fields.Boolean(string='Aktif', default=True)
    
    prompt_additions = fields.Text(
        string='Sahne Prompt Ekleri', 
        help='Örn: Paris streets, sunny day, cinematic lighting, 8k',
        translate=True
    )
    negative_prompt_additions = fields.Text(
        string='Negatif Prompt Ekleri', 
        help='Bu sahnede kesinlikle olmaması gerekenler',
        translate=True
    )
