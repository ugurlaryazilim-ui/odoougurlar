# -*- coding: utf-8 -*-
"""KABUL: KK-API (create_and_send), KK-4/5 (API), KK-30 (cekirdekte 'ups' yok), KK-31 (genisletilebilirlik).

Yesile donecegi gorev: G7 (G1-G6'ya bagli).
"""
import base64
import inspect
import os
import re

from odoo.exceptions import AccessError
from odoo.service.model import call_kw
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from .kabul_taban import CargoKabulCase

MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED_UI_TEXT = 'UPS/kargo gönderisi'     # 02-tasarim 4.6 onay metni; KK-30 ile celisiyor -> rapora yazildi


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulApi(CargoKabulCase):
    PROVIDER_TYPES = ('fixed', 'base_on_rule')

    def call(self, user=None, **over):
        kwargs = dict(recipient_name='Ali Veli', phone='05321234567', street='Ataturk Mah. Gul Sk. No:5',
                      state=self.st('06'), district='Cankaya')
        kwargs.update(over)
        return self.env['cargo.shipment'].with_user(user or self.user).create_and_send(**kwargs)

    def test_basarili_cagri(self):
        """KK-API-1."""
        shipment = self.call(package_count=2, weight=2.5, reference='API-1', invoice_no='F-9',
                             cod_amount=300.0, cod_method='cash', email='a@example.com')
        self.assertEqual(shipment.state, 'created')
        self.assertTrue(shipment.tracking_ref)
        self.assertFalse(shipment.error_message)
        self.assertTrue(shipment.label_pdf_id)
        self.assertEqual(base64.b64decode(shipment.label_pdf_id.datas)[:5], b'%PDF-')
        self.assertEqual((shipment.package_count, shipment.package_weight, shipment.origin_ref, shipment.invoice_no),
                         (2, 2.5, 'API-1', 'F-9'))
        self.assertEqual(shipment.cod_amount, 300.0)
        self.assertEqual(shipment.carrier_id, self.carrier, 'KK-4: firma verilmezse sirket varsayilani')
        self.assertEqual(self.provider.count('send'), 1)

    def test_varsayilan_agirlik(self):
        self.company.cargo_default_weight = 3.5
        shipment = self.call()
        self.assertEqual(shipment.package_weight, 3.5)

    def test_firma_ve_kaynak(self):
        source = self.env['res.partner'].create({'name': 'Kaynak kayit'})
        shipment = self.call(carrier=self.carrier_y, source=source)
        self.assertEqual(shipment.carrier_id, self.carrier_y)
        self.assertEqual(shipment.source_id, source.id)
        self.assertEqual(shipment.source_model, 'res.partner')
        self.assertEqual(self.provider.of('send')[0]['carrier_id'], self.carrier_y.id)

    def test_saglayici_hatasi_istisna_degil(self):
        self.provider.plan['send'] = self.provider.err_send('9001', 'Adres hatali')
        shipment = self.call()
        self.assertEqual(shipment.state, 'failed')
        self.assertIn('Adres hatali', shipment.error_message)
        self.provider.plan['send'] = self.provider.uncertain_send()
        shipment = self.call()
        self.assertEqual(shipment.state, 'uncertain')

    def test_ayni_referans_mevcut_kaydi_doner(self):
        """KK-API-2."""
        first = self.call(reference='API-DUP')
        again = self.call(reference='API-DUP')
        self.assertEqual(again, first)
        self.assertEqual(self.provider.count('send'), 1)
        self.assertEqual(self.env['cargo.shipment'].sudo().search_count([('origin_ref', '=', 'API-DUP')]), 1)

    def test_failed_ve_cancelled_referansi_yeniden_acilir(self):
        self.provider.plan['send'] = [self.provider.err_send(), lambda s: self.provider.ok_send(shipment=s)]
        first = self.call(reference='API-RETRY')
        self.assertEqual(first.state, 'failed')
        second = self.call(reference='API-RETRY')
        self.assertNotEqual(second, first)
        self.assertEqual(second.state, 'created')
        second.action_cancel()
        third = self.call(reference='API-RETRY')
        self.assertNotIn(third, first | second)

    def test_yetkisiz_cagri(self):
        """KK-API-3: grupsuz kullanici (sudo ile bile) AccessError; kayit ve dis cagri yok."""
        before = self.env['cargo.shipment'].sudo().search_count([])
        for user in (self.plain, self.plain_sales):
            with self.assertRaises(AccessError, msg=user.login):
                self.call(user=user)
            with self.assertRaises(AccessError, msg='sudo gercek kullaniciya bakmali: %s' % user.login):
                self.env['cargo.shipment'].with_user(user).sudo().create_and_send(
                    recipient_name='Ali Veli', phone='05321234567', street='Adres 1', state=self.st('06'), district='Cankaya')
        self.assertEqual(self.env['cargo.shipment'].sudo().search_count([]), before)
        self.no_provider_calls()

    def test_rpc_kapali(self):
        """RPC'ye kapali (@api.private): call_kw AccessError verir."""
        with self.assertRaises(AccessError):
            call_kw(self.env['cargo.shipment'].with_user(self.user), 'create_and_send', [], {
                'recipient_name': 'Ali Veli', 'phone': '05321234567', 'street': 'Adres 1',
                'state': self.st('06').id, 'district': 'Cankaya'})
        self.no_provider_calls()

    def test_imza_ve_dikkat_notu(self):
        func = type(self.env['cargo.shipment']).create_and_send
        params = inspect.signature(func).parameters
        keyword_only = [n for n, p in params.items() if p.kind == p.KEYWORD_ONLY]
        for name in ('recipient_name', 'phone', 'street', 'state', 'district', 'package_count', 'weight', 'reference',
                     'invoice_no', 'cod_amount', 'cod_method', 'carrier', 'source', 'email', 'partner'):
            self.assertIn(name, keyword_only, 'create_and_send anahtar-kelime-yalniz parametre: %s' % name)
        self.assertIn('DIKKAT:', inspect.getdoc(func) or '', 'commit uyarisi docstring\'de olmali')

    def test_varsayilan_firma_yok(self):
        """KK-5 (API)."""
        self.company.cargo_default_carrier_id = False
        self.assert_user_error(self.call, r'Varsayılan kargo firması ayarlı değil')
        self.no_provider_calls()
        self.assertEqual(self.env['cargo.shipment'].sudo().search_count([('create_uid', '=', self.user.id)]), 0)

    def test_dogrulama_hatalari_kayit_birakmaz(self):
        """KK-7/8/19b API: UserError, kayit geri alinir, dis cagri yok."""
        before = self.env['cargo.shipment'].sudo().search_count([])
        cases = [
            dict(phone='123'),
            dict(district='Bilinmeyenilce'),
            dict(carrier=self.carrier_nocod, cod_amount=100.0, cod_method='cash'),
            dict(package_count=0),
        ]
        for over in cases:
            with self.subTest(over=sorted(over)):
                self.assert_user_error(lambda: self.call(**over))
        self.no_provider_calls()
        self.assertEqual(self.env['cargo.shipment'].sudo().search_count([]), before, 'hatali cagri kayit birakmamali')

    def test_kapida_odeme_yonetici_bayragi(self):
        shipment = self.call(cod_amount=150.0, cod_method='cash')
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(self.provider.of('send')[0]['cod_amount'], 150.0)


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulCekirdekTemizligi(TransactionCase):

    def test_cekirdekte_ups_yok(self):
        """KK-30: addons/cargo .py/.xml/.csv dosyalarinda (tests/ ve README haric) ups dali/sabiti yok."""
        pattern = re.compile(r'(?i)\bups\b|ups_tr')
        offenders = []
        for root, dirs, files in os.walk(MODULE_DIR):
            dirs[:] = [d for d in dirs if d not in ('tests', '__pycache__', 'static', 'i18n')]
            for fname in files:
                if not fname.endswith(('.py', '.xml', '.csv', '.js', '.scss')):
                    continue
                path = os.path.join(root, fname)
                with open(path, encoding='utf-8', errors='replace') as handle:
                    for number, line in enumerate(handle, 1):
                        if pattern.search(line.replace(ALLOWED_UI_TEXT, '')):
                            offenders.append('%s:%d' % (os.path.relpath(path, MODULE_DIR), number))
        self.assertEqual(offenders, [], 'cekirdek modulde "ups" gecmemeli')

    def test_manifest_bagimliliklari(self):
        import ast
        with open(os.path.join(MODULE_DIR, '__manifest__.py'), encoding='utf-8') as handle:
            manifest = ast.literal_eval(handle.read())
        self.assertNotIn('cargo_ups', manifest.get('depends', []))
        self.assertIn('stock_delivery', manifest['depends'])
        self.assertIn('mail', manifest['depends'])
        for forbidden in ('ugurlar_barcode', 'odoougurlar_nebim'):
            self.assertNotIn(forbidden, manifest['depends'])


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulGenisletilebilirlik(CargoKabulCase):
    """KK-31: yeni saglayici = yalniz arayuz metotlari + kendi il/ilce verisi; cekirdege dokunulmaz."""
    PROVIDER_TYPES = ('fixed', 'base_on_rule')

    def test_iki_saglayici_uctan_uca(self):
        carrier_b = self.make_carrier('Ikinci saglayici', ptype='base_on_rule')
        area_b = self.make_area('06', 'CANKAYA', provider='base_on_rule')
        self.assertNotEqual(area_b.area_code, self.area_cankaya.area_code)
        a = self.sent()
        b = self.sent(carrier_id=carrier_b.id)
        self.assertEqual(a.area_id, self.area_cankaya)
        self.assertEqual(b.area_id, area_b)
        codes = {c['carrier_id']: c['area_code'] for c in self.provider.of('send')}
        self.assertEqual(codes[self.carrier.id], self.area_cankaya.area_code)
        self.assertEqual(codes[carrier_b.id], area_b.area_code)
        for shipment in (a, b):
            action = shipment.action_print_label()
            self.assertTrue(action)
            shipment.action_cancel()
            self.assertEqual(shipment.state, 'cancelled')
        self.assertEqual(self.provider.count('cancel'), 2)

    def test_saglayici_bagimsizligi(self):
        """Bir saglayicinin metotlari digerinin firmasi icin cagrilmaz."""
        carrier_b = self.make_carrier('Ikinci saglayici', ptype='base_on_rule')
        self.make_area('06', 'CANKAYA', provider='base_on_rule')
        self.sent(carrier_id=carrier_b.id)
        self.assertEqual({c['carrier_id'] for c in self.provider.calls}, {carrier_b.id})
