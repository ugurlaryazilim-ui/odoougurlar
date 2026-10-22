# -*- coding: utf-8 -*-
"""Mail Order sihirbazı (K-14): fatura seçimi, kayıt oluşturma, kart sayfasına yönlendirme.

Link sihirbazını miras alır: fatura getirme, tutar kilidi, korumalı alanlar, engel mesajı ve
adım 1-6 (``_create_sending_payment``) ortaktır. Farklar:

* SMS/e-posta kanalı ve geçerlilik süresi YOKTUR (SESSIONTOKEN kimseye mesaj göndermez, oturum
  sabit 1 saat); istemciden gelen değerler yok sayılır.
* Telefon ve e-posta zorunlu değildir (müşteri yanımızda, kanal yok); girilmişse biçim denetlenir.
* Kart bilgisi bu sihirbazda ALINMAZ ve hiçbir modelde saklanmaz: kart sayfası ayrı bir
  sayfadır ve kart alanlarını tarayıcı doğrudan Paratika'ya gönderir (K-13).
"""
from odoo import models
from odoo.exceptions import UserError

from ..models.sanal_pos_payment import FIELD_MAX_LENGTH, MAIL_ORDER_EXPIRY_HOURS
from ..tools import normalize_phone, validate_email
from .payment_create_wizard import PHONE_MSG


class SanalPosMailOrderWizard(models.TransientModel):
    _name = 'sanal.pos.mail.order.wizard'
    _inherit = 'sanal.pos.payment.create.wizard'
    _description = 'Sanal POS: Mail Order'
    _sanal_pos_payment_method = 'mail_order'

    def _reopen_action(self):
        action = super()._reopen_action()
        action['name'] = 'Mail Order'
        return action

    def _validated_values(self):
        """Ad zorunlu; telefon/e-posta isteğe bağlı ama girilmişse geçerli. Kanal ve süre sabit."""
        self.ensure_one()
        errors = []
        values = self._validated_base(errors)
        phone_raw = (self.customer_phone or '').strip()
        phone = normalize_phone(phone_raw) or ''
        if phone_raw and not phone:
            errors.append(PHONE_MSG)
        email = (self.customer_email or '').strip()
        limit = FIELD_MAX_LENGTH['customer_email']
        if len(email) > limit:
            errors.append('Müşteri e-postası en çok %d karakter olabilir.' % limit)
        elif email and not validate_email(email):
            errors.append('Geçerli bir e-posta adresi girin.')
        if errors:
            raise UserError('\n'.join(errors))
        values.update({
            'customer_phone': phone or False,
            'customer_email': email or False,
            # NEDEN: kanal/süre istemciden alınmaz (formda alan yok, RPC ile gelse de yok sayılır);
            # kayıt link alanlarıyla tutarlı kalsın diye sabit değerler yazılır (bkz. KARARLAR K-14).
            'channel_sms': False,
            'channel_email': False,
            'expiry_hours': MAIL_ORDER_EXPIRY_HOURS,
        })
        for key in ('customer_address', 'customer_city', 'customer_zip'):
            values[key] = values[key] or False
        return values

    def action_create_link(self):
        raise UserError('Bu sihirbazdan link oluşturulamaz; "Kart Bilgisi Gir" düğmesini kullanın.')

    def _open_sending(self, values, info):
        """K-15: Paratika oturumu canlı olabilecek önceki deneme varsa aynı MPID ile yeniden açılır.

        DIKKAT: yeni MPID'li kayıt açmak açık bir kart/banka sekmesiyle çift tahsilata yol açar
        ("Kapat" Paratika oturumunu sonlandıramaz). Bu dal kaldırılmamalı (bkz. KARARLAR K-15).
        """
        prior = self.env['sanal.pos.payment']._live_mail_order_prior(values['invoice_no'])
        if prior:
            return prior._reopen_mail_order(values)
        return super()._open_sending(values, info)

    def action_create_mail_order(self):
        """Kontroller -> 'Gönderiliyor' + commit -> SESSIONTOKEN -> sonuç + commit -> kart sayfası."""
        self.ensure_one()
        payment = self._create_sending_payment('mail_order')
        if payment.state != 'sending':
            # K-15: önceki oturumda ödeme bulundu; yeni token alınmadı
            return payment._mail_order_reuse_notification()
        return payment._run_create_session()
