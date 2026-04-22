from odoo import models, fields


class TestResultWizard(models.TransientModel):
    """Nebim test sonuçlarını popup olarak gösteren wizard."""
    _name = 'odoougurlar.test.result.wizard'
    _description = 'Nebim Test Sonuç Penceresi'

    title = fields.Char(string='Başlık', readonly=True)
    result_text = fields.Text(string='Sonuç Özeti', readonly=True)
    result_json = fields.Text(string='Ham JSON Verisi', readonly=True)
