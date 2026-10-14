# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Liste fiyatları (USD / 1M token). Gemini çıkışına "thinking" token'ları dahildir.
PRICES = {
    'gemini-2.5-flash': (0.30, 2.50),
    'gpt-4o-mini': (0.15, 0.60),
}


class SocialAIUsage(models.Model):
    """Her AI çağrısı için bir satır: token, maliyet, durum (ayrı transaction'da yazılır)."""
    _name = 'social.media.ai.usage'
    _description = 'Sosyal Medya AI Kullanım Kaydı'
    _order = 'id desc'
    _rec_name = 'model'

    provider = fields.Selection([
        ('gemini', 'Gemini'),
        ('openai', 'OpenAI'),
        ('ollama', 'Ollama'),
    ], string='Sağlayıcı', required=True, index=True)
    model = fields.Char(string='Model')
    input_tokens = fields.Integer(string='Giriş Token')
    output_tokens = fields.Integer(string='Çıkış Token', help='"Thinking" token\'ları dahil')
    duration = fields.Float(string='Süre (sn)')
    status = fields.Selection([
        ('ok', 'Başarılı'),
        ('timeout', 'Zaman aşımı'),
        ('error', 'Hata'),
    ], string='Durum', default='ok', required=True,
        help='Zaman aşımı / hata: istek gönderilmiş olabilir ama token bilgisi yok; maliyeti bilinmiyor.')
    cost = fields.Float(string='Maliyet (USD)', digits=(16, 6))

    @api.model
    def _record(self, provider, model, input_tokens=0, output_tokens=0, duration=0.0, status='ok'):
        """Kullanımı ayrı cursor'da yazar: cron'un rollback'i harcama kaydını silmesin."""
        in_price, out_price = PRICES.get(model, (0.0, 0.0))
        cost = (input_tokens * in_price + output_tokens * out_price) / 1e6
        try:
            with self.env.registry.cursor() as cr:
                self.with_env(self.env(cr=cr)).sudo().create({
                    'provider': provider, 'model': model, 'input_tokens': input_tokens,
                    'output_tokens': output_tokens, 'duration': duration, 'status': status, 'cost': cost,
                })
        except Exception as e:
            _logger.warning('AI kullanım kaydı yazılamadı (%s): %s', provider, e)
