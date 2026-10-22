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
* ``create_session`` -> ``token`` (Mail Order: Direct POST oturumu; hata/zaman aşımı/token yok ->
  ``ok=False``, belirsizlik yoktur)
* ``direct_post_url`` -> kart formunun gönderileceği adres ya da ``None`` (çağrı yapmaz)
* ``query_installments`` -> ``options`` (``[{'count': int, 'networks': [str], 'rate': float,
  'systems': [{'keys': [str], 'rate': float}]}]``) + ``system_keys`` (tüm sistem kimlikleri);
  hata -> ``ok=False``, ``options=[]``)
* ``resend``       -> -
* ``cancel_link``  -> ``already_closed``
* ``find_link``    -> ``found``, ``token``, ``status`` (+ ``ambiguous``)
* ``query_status`` -> ``transactions`` (``ref, kind, status, amount, currency, time,
  installment_count, payment_system, card_last4``)
* ``void`` / ``refund`` -> ``ref``
* ``parse_notification(params)`` -> ödeme numarası ya da ``None``

Yeni sağlayıcı eklemek: ``sanal.pos.payment.provider`` alanına ``selection_add``,
bu arayüzü uygulayan bir ``sanal.pos.provider.<kod>`` AbstractModel'i ve ayar alanları.
"""
import logging

from odoo import api, models
from odoo.exceptions import UserError

from .. import tools

_logger = logging.getLogger(__name__)

# Log gövdesi sınırı (KK-39): ~20 KB
LOG_BODY_LIMIT = 20 * 1024


class SanalPosProvider(models.AbstractModel):
    _name = 'sanal.pos.provider'
    _description = 'Sanal POS Sağlayıcı Arayüzü'

    # ---------------------------------------------------------------- arayüz
    # Arayüz metotları @api.private: RPC (call_kw) ile ÇAĞRILAMAZ; yalnız sunucu kodu çağırır.
    # Aksi halde dış çağrı (VOID/REFUND dahil) tetiklenebilirdi. Yeni sağlayıcı da aynısını yapmalı.
    @api.private
    def create_link(self, payment):
        raise NotImplementedError()

    @api.private
    def create_session(self, payment):
        """Mail Order: kart sayfası için ödeme oturumu (token) açar. Kart verisi almaz."""
        raise NotImplementedError()

    @api.private
    def direct_post_url(self, payment):
        """Kart formunun doğrudan sağlayıcıya gönderileceği adres; token yoksa ``None``."""
        raise NotImplementedError()

    @api.private
    def query_installments(self, payment):
        """İşyerinin taksit seçenekleri (kart verisi gönderilmez)."""
        raise NotImplementedError()

    @api.private
    def resend(self, payment, channels):
        raise NotImplementedError()

    @api.private
    def cancel_link(self, payment):
        raise NotImplementedError()

    @api.private
    def find_link(self, payment):
        raise NotImplementedError()

    @api.private
    def query_status(self, payment):
        raise NotImplementedError()

    @api.private
    def void(self, payment, refund_line):
        raise NotImplementedError()

    @api.private
    def refund(self, payment, refund_line):
        raise NotImplementedError()

    @api.private
    def test_connection(self, environment, credentials, api_url):
        """Ayar ekranından kimlik denemesi -> ek anahtarlar ``reached, authenticated, problem``."""
        raise NotImplementedError()

    @api.model
    @api.private
    def parse_notification(self, params):
        raise NotImplementedError()

    @api.private
    def _link_url(self, payment, token):
        """Ödeme sayfası adresi; sağlayıcı biçimi bilmiyorsa None (alan boş kalır)."""
        return None

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
        """``sanal.pos.log`` satırı yazar (KK-39). Sırlar ÇAĞIRANDA maskelenmiş olmalıdır;
        kart numarası (Luhn-geçerli PAN) ise burada MERKEZİ olarak maskelenir.

        Log yazımı başarısız olsa bile iş akışı kesilmez (dış çağrıdan sonra raise yok);
        hata yalnız istisna sınıf adıyla loglanır (gövde/sır içermesin).
        """
        # NEDEN: Mail Order'da kart verisi Odoo'ya hiç girmemeli (bkz. KARARLAR K-13); yanıt gövdesi
        # ya da istisna metni yanlışlıkla PAN taşısa bile her sağlayıcı için tek noktada maskelenir.
        # DIKKAT: maske kırpmadan ÖNCE uygulanır; yoksa sınırda ikiye bölünen PAN Luhn'a takılmaz.
        request_body = tools.mask_card_data(request_body)
        response_body = tools.mask_card_data(response_body)
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
