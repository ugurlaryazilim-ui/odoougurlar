# -*- coding: utf-8 -*-
"""Mail Order PCI statik testleri (KK-17): kart verisi için kalıcı alan, rota parametresi veya
sağlayıcı çağrı parametresi yoktur.

Eşleştirici (``is_card_field``) kendi birim testiyle sınanır; "olumlu çapa" olarak yeni
``sanal.pos.mail.order.wizard`` modelinin ve kart sayfası rotasının varlığı denetlenir.
"""
import inspect
import re

from odoo import http
from odoo.tests import tagged

from .common import SanalPosCase

ALLOWED = {'card_last4', 'expires_at', 'expiry_hours'}
TOKEN_RES = [re.compile(p) for p in (
    r'(^|_)(pan|cvv|cvc|cvv2)(_|$)', r'card_?(no|number|owner|holder|pan|cvv|token)',
    r'expiry_?(month|year|date)', r'name_?on_?card', r'cardholder', r'(^|_)card_?exp')]


def is_card_field(name):
    if name in ALLOWED:
        return False
    return any(rx.search(name.lower()) for rx in TOKEN_RES)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestPciStatic(SanalPosCase):

    def sanal_models(self):
        return [m for name, m in self.env.registry.items() if name.startswith('sanal.pos.')]

    def test_eslestirici_birimi(self):
        for bad in ('pan', 'cvv', 'cvc', 'card_pan', 'card_number', 'card_owner', 'card_holder', 'cardholder_name',
                    'expiry_month', 'expiryYear', 'name_on_card', 'customer_pan', 'cvv2', 'card_no'):
            self.assertTrue(is_card_field(bad), bad)
        for good in ('company_id', 'card_last4', 'expires_at', 'expiry_hours', 'panel_id', 'span', 'company_ids',
                     'customer_name', 'provider_token', 'paid_amount', 'installment_count', 'channel_sms'):
            self.assertFalse(is_card_field(good), good)

    def test_modellerde_kart_alani_yok(self):
        names = sorted(m._name for m in self.sanal_models())
        self.assertIn('sanal.pos.mail.order.wizard', names)        # olumlu çapa: yeni model var
        self.assertIn('sanal.pos.payment', names)
        offenders = []
        for model in self.sanal_models():
            offenders += ['%s.%s' % (model._name, f) for f in model._fields if is_card_field(f)]
        self.assertEqual(offenders, [])

    def test_veritabani_sutunlarinda_kart_alani_yok(self):
        self.env.cr.execute("""SELECT table_name, column_name FROM information_schema.columns
                                WHERE table_schema = 'public' AND table_name LIKE 'sanal_pos_%'""")
        rows = self.env.cr.fetchall()
        self.assertTrue([r for r in rows if r[0] == 'sanal_pos_payment'])
        self.assertEqual(['%s.%s' % r for r in rows if is_card_field(r[1])], [])

    def test_rota_imzalarinda_kart_parametresi_yok(self):
        from odoo.addons.sanal_pos.controllers import main as ctrl_module
        found, offenders = set(), []
        for cls in vars(ctrl_module).values():
            if not (inspect.isclass(cls) and issubclass(cls, http.Controller)):
                continue
            for name, fn in inspect.getmembers(cls, inspect.isfunction):
                routing = getattr(fn, 'original_routing', None)
                if not routing:
                    continue
                routes = routing.get('routes', [])
                found.update(routes)
                params = list(inspect.signature(fn).parameters)
                offenders += ['%s(%s)' % (name, p) for p in params if is_card_field(p)]
        self.assertIn('/sanal_pos/mail_order/pay/<int:payment_id>', found)
        self.assertEqual(offenders, [])

    def test_saglayici_tum_metotlari_kart_parametresi_gondermez(self):
        provider = self.env['sanal.pos.provider.paratika']
        payment = self.make_mail_order(state='sending', provider_token=False, sent_at=False, expires_at=False)
        provider.create_session(payment)
        provider.query_installments(payment)
        provider.direct_post_url(self.make_mail_order(provider_token='T', invoice_no='PCI-2'))
        provider.query_status(payment)
        self.assertGreaterEqual(len(self.mock.calls), 3)
        for call in self.mock.calls:
            for key in call.params:
                self.assertFalse(key.upper().startswith('CARD'), key)
                self.assertNotIn(key.upper(), ('PAN', 'CVV', 'CVC', 'NAMEONCARD', 'EXPIRYMONTH', 'EXPIRYYEAR'))

    def test_manifest_surumu_ve_kart_icerigi_yok(self):
        import ast
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '__manifest__.py')
        with open(path, encoding='utf-8') as fh:
            manifest = ast.literal_eval(fh.read())
        self.assertEqual(manifest['version'], '19.0.1.3.0')
