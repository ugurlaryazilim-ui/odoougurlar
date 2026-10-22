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

    @staticmethod
    def sanal_pos_controllers():
        """sanal_pos'un tüm ``http.Controller`` alt sınıfları (yeni controller dosyası da kapsanır)."""
        import importlib
        import pkgutil
        from odoo.addons.sanal_pos import controllers as pkg
        # NEDEN: __init__'e eklenmemiş bir dosya da taransın; yalnız import edilmiş sınıflar görünür
        # (rota kaydı da aynı importa bağlı olduğundan eksik import zaten rota üretmez).
        for info in pkgutil.iter_modules(pkg.__path__):
            importlib.import_module('%s.%s' % (pkg.__name__, info.name))
        found, todo = [], list(http.Controller.__subclasses__())
        while todo:
            cls = todo.pop()
            todo.extend(cls.__subclasses__())
            if cls.__module__.startswith('odoo.addons.sanal_pos.controllers'):
                found.append(cls)
        return found

    def test_rota_imzalarinda_kart_parametresi_yok(self):
        found, offenders = set(), []
        controllers = self.sanal_pos_controllers()
        modules = {c.__module__.rsplit('.', 1)[-1] for c in controllers}
        self.assertTrue({'main', 'mail_order'} <= modules, modules)      # tarayıcı tüm dosyaları görüyor
        for cls in controllers:
            for name, fn in inspect.getmembers(cls, inspect.isfunction):
                routing = getattr(fn, 'original_routing', None)
                if not routing:
                    continue
                routes = routing.get('routes', [])
                found.update(routes)
                params = list(inspect.signature(fn).parameters)
                offenders += ['%s.%s(%s)' % (cls.__name__, name, p) for p in params if is_card_field(p)]
                offenders += ['%s: %s' % (name, r) for r in routes if is_card_field(r.rsplit('/', 1)[-1])]
        # olumlu çapalar: kart rotası (mail_order.py) ve dönüş rotası (main.py) taranmış olmalı
        self.assertIn('/sanal_pos/mail_order/pay/<int:payment_id>', found)
        self.assertIn('/sanal_pos/mail_order/result', found)
        self.assertIn('/sanal_pos/paratika/mo_return', found)
        self.assertEqual(offenders, [])

    def test_saglayici_tum_metotlari_kart_parametresi_gondermez(self):
        provider = self.env['sanal.pos.provider.paratika']
        payment = self.make_mail_order(state='sending', provider_token=False, sent_at=False, expires_at=False)
        provider.create_session(payment)
        provider.query_installments(payment)
        provider.direct_post_url(self.make_mail_order(provider_token='T', invoice_no='PCI-2'))
        provider.query_status(payment)
        # link ve iade yolu da (G5 teslimi: sağlayıcının tüm arayüz metotları)
        link = self.make_payment(state='sending', invoice_no='PCI-3', provider_token=False)
        provider.create_link(link)
        provider.find_link(link)
        provider.resend(link, ['sms'])
        provider.cancel_link(link)
        paid = self.make_paid(self.make_payment(invoice_no='PCI-4'))
        provider.void(paid, self.make_refund_line(paid, paid.amount, kind='void', state='processing'))
        paid2 = self.make_paid(self.make_payment(invoice_no='PCI-5'), tran_ref='T5')
        provider.refund(paid2, self.make_refund_line(paid2, 10.0, state='processing'))
        self.assertGreaterEqual(len(self.mock.calls), 9)
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
