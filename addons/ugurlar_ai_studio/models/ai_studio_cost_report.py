from odoo import fields, models, tools

from .ai_studio_usage import USAGE_PROVIDERS, USAGE_STEPS

# DIKKAT: Bu dosya models/__init__.py'de ai_studio_session'dan SONRA import edilmeli.
# Odoo modelleri sınıf tanım sırasıyla kurar (_auto_init + init); view session
# tablosuna JOIN yaptığından taze kurulumda tablo önce oluşmalı. Sınıf eskiden
# ai_studio_usage.py'deydi ve session.py o dosyayı erken import ettiği için
# "relation ai_studio_session does not exist" ile kurulum düşüyordu.


class AiStudioCostReport(models.Model):
    """Ürün başına net maliyet: kullanım kayıtları + üretimlerin fal maliyeti."""
    _name = 'ai.studio.cost.report'
    _description = 'AI Stüdyo Maliyet Analizi'
    _auto = False
    _order = 'date desc'
    _rec_name = 'step'

    date = fields.Datetime(string='Tarih', readonly=True)
    product_id = fields.Many2one('product.product', string='Ürün Varyantı', readonly=True)
    session_id = fields.Many2one('ai.studio.session', string='Oturum', readonly=True)
    user_id = fields.Many2one('res.users', string='Kullanıcı', readonly=True)
    provider = fields.Selection(USAGE_PROVIDERS, string='Sağlayıcı', readonly=True)
    step = fields.Selection(USAGE_STEPS, string='Adım', readonly=True)
    calls = fields.Integer(string='Kayıt Sayısı', readonly=True,
                           help='Gemini: API çağrısı sayısı. fal: üretim kaydı sayısı (bir üretim kendi içinde '
                                'arka plan silme, etiket silme, giydirme ve yeniden denemeleri toplar).')
    input_tokens = fields.Integer(string='Giriş Token', readonly=True)
    output_tokens = fields.Integer(string='Çıkış Token', readonly=True)
    cost = fields.Float(string='Maliyet (USD)', digits=(16, 4), readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW ai_studio_cost_report AS (
                SELECT u.id * 2 AS id, u.create_date AS date, u.product_id, u.session_id, u.user_id,
                       u.provider, u.step, 1 AS calls, u.input_tokens, u.output_tokens, u.cost
                  FROM ai_studio_usage u
                UNION ALL
                SELECT g.id * 2 + 1, g.create_date, g.product_id, g.session_id, s.user_id,
                       CASE WHEN g.fal_endpoint LIKE 'fashn/%%' THEN 'fashn' ELSE 'fal' END,
                       'generation', 1, 0, 0, g.cost
                  FROM ai_studio_generation g
                  LEFT JOIN ai_studio_session s ON s.id = g.session_id
                 WHERE COALESCE(g.cost, 0) > 0
            )
        """)
