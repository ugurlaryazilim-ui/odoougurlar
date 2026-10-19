# -*- coding: utf-8 -*-
"""Sanal POS sağlayıcı arayüzü (tasarım §5, NFR-1).

Çekirdek (ödeme talebi, durum makinesi, sihirbazlar) yalnız bu arayüzü ve
NORMALİZE sonuç sözlüklerini bilir; sağlayıcıya özgü kodlar (Paratika AP/FA/VD,
ERRxxxxx, alan adları) yalnız ``sanal.pos.provider.<kod>`` modelindedir.
Durum KARARI çekirdektedir (``_apply_status``); sağlayıcı yalnız kodları
normalize eder.

Ortak sonuç anahtarları: ``ok``, ``timeout``, ``error_code``, ``error_message``
(Türkçe, kullanıcıya gösterilebilir), ``raw_code``. Metotlara göre ek anahtarlar:

* ``create_link``  -> ``token``, ``url``
* ``resend``       -> -
* ``cancel_link``  -> ``already_closed``
* ``find_link``    -> ``found``, ``token``, ``status`` (+ ``ambiguous``)
* ``query_status`` -> ``transactions`` (``ref, kind, status, amount, currency, time,
  installment_count, card_last4``)
* ``void`` / ``refund`` -> ``ref``
* ``parse_notification(params)`` -> ödeme numarası ya da ``None``

Yeni sağlayıcı eklemek: ``sanal.pos.payment.provider`` alanına ``selection_add``,
bu arayüzü uygulayan bir ``sanal.pos.provider.<kod>`` AbstractModel'i ve ayar alanları.
"""
import logging

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Log gövdesi sınırı (KK-39): ~20 KB
LOG_BODY_LIMIT = 20 * 1024


class SanalPosProvider(models.AbstractModel):
    _name = 'sanal.pos.provider'
    _description = 'Sanal POS Sağlayıcı Arayüzü'

    # ---------------------------------------------------------------- arayüz
    def create_link(self, payment):
        raise NotImplementedError()

    def resend(self, payment, channels):
        raise NotImplementedError()

    def cancel_link(self, payment):
        raise NotImplementedError()

    def find_link(self, payment):
        raise NotImplementedError()

    def query_status(self, payment):
        raise NotImplementedError()

    def void(self, payment, refund_line):
        raise NotImplementedError()

    def refund(self, payment, refund_line):
        raise NotImplementedError()

    @api.model
    def parse_notification(self, params):
        raise NotImplementedError()

    # ---------------------------------------------------------------- ortak yardımcılar
    @api.model
    def _result(self, ok=False, timeout=False, error_code=None, error_message=None,
                raw_code=None, **extra):
        """Normalize sonuç sözlüğü (ortak anahtarlar her zaman bulunur)."""
        result = {
            'ok': bool(ok),
            'timeout': bool(timeout),
            'error_code': error_code or None,
            'error_message': error_message or None,
            'raw_code': raw_code,
        }
        result.update(extra)
        return result

    def _log_call(self, payment, action, provider, environment, duration_ms=0,
                  http_status=0, response_code=None, error_code=None, success=False,
                  request_body=None, response_body=None, is_financial=False):
        """``sanal.pos.log`` satırı yazar (KK-39). Gövdeler ÇAĞIRANDA maskelenmiş olmalıdır.

        Log yazımı başarısız olsa bile iş akışı kesilmez (dış çağrıdan sonra raise yok);
        hata yalnız istisna sınıf adıyla loglanır (gövde/sır içermesin).
        """
        if response_body and len(response_body) > LOG_BODY_LIMIT:
            response_body = response_body[:LOG_BODY_LIMIT] + '...[kırpıldı]'
        values = {
            'action': action,
            'provider': provider,
            'environment': environment if environment in ('test', 'live') else False,
            'payment_id': payment.id or False,
            'duration_ms': int(duration_ms),
            'http_status': int(http_status or 0),
            'response_code': response_code,
            'error_code': error_code,
            'success': bool(success),
            'request_body': request_body,
            'response_body': response_body,
            'is_financial': bool(is_financial),
        }
        try:
            with self.env.cr.savepoint():
                self.env['sanal.pos.log'].sudo().create(values)
        except Exception as exc:  # noqa: BLE001 - log yazımı akışı bozmamalı
            _logger.warning('sanal_pos: işlem kaydı yazılamadı (%s)', type(exc).__name__)


class SanalPosPaymentProviderLookup(models.Model):
    """``payment._provider()``: sağlayıcıyı ``provider`` alanından bulur (tasarım §5)."""
    _inherit = 'sanal.pos.payment'

    def _provider(self):
        self.ensure_one()
        model_name = 'sanal.pos.provider.%s' % (self.provider or '')
        if model_name not in self.env:
            raise UserError('Bilinmeyen ödeme sağlayıcısı: %s' % (self.provider or '-'))
        return self.env[model_name]
