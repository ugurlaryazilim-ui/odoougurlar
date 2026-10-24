# -*- coding: utf-8 -*-
"""G9: ``ups_tr_cargo_send|cancel|find|cod_code`` sağlayıcı kancaları (sözleşme 02-tasarim §4.5).

NEDEN: kancalar çekirdek akışı (G4 action_*) olmadan doğrudan çağrılır; akış testleri kabul dosyasındadır.
HTTP ``kabul_taban.UpsCase`` yönlendiricisiyle sentetik yanıtlanır; gerçek ağ yok.
"""
import base64
import logging
from unittest.mock import patch

import requests

from odoo.tests import tagged

from ..services import ups_soap
from .kabul_taban import (
    LINK_WITH_KEY, SECRETS, URL_LIVE, URL_QUERY, URL_TEST, UpsCase, cancel_result, create_err, create_ok, envelope,
    find_text, login_err, make_label_png, make_response, operation, parse, query_error, query_packages,
)
from .test_kabul_ups_soap import SECRET_VALUES, LogTap

SEND_KEYS = {'status', 'tracking_ref', 'labels', 'error_code', 'error_message'}
CANCEL_KEYS = {'status', 'error_code', 'error_message'}
FIND_KEYS = {'status', 'tracking_ref', 'count', 'error_message'}


@tagged('post_install', '-at_install', 'cargo_ups')
class TestUpsProvider(UpsCase):

    def shipment(self, **over):
        shipment = self.env['cargo.shipment'].create(self.ups_vals(**over))
        shipment.name = 'KG-G9-%s' % shipment.id
        return shipment

    def created(self, test_mode=True, **over):
        shipment = self.shipment(**over)
        shipment.write({'tracking_ref': '1ZG9IPTAL', 'test_mode': test_mode})
        return shipment

    def create_info(self):
        return parse(self.ups_requests('CreateShipment_Type3')[-1])

    def test_send_sozluk_anahtarlari(self):
        shipment = self.shipment(package_count=2)
        result = self.ups.ups_tr_cargo_send(shipment)
        self.assertEqual(set(result), SEND_KEYS)
        self.assertEqual((result['status'], result['tracking_ref'], result['error_code'], result['error_message']),
                         ('ok', '1ZFIXTURE0001', '', ''))
        self.assertEqual(result['labels'], [make_label_png(0), make_label_png(1)])
        self.assertEqual(find_text(self.create_info(), 'CustomerReferance'), shipment.name)
        self.plan['Login_Type1'] = login_err(100, 'Kimlik reddedildi')
        result = self.ups.ups_tr_cargo_send(shipment)
        self.assertEqual(set(result), SEND_KEYS)
        self.assertEqual((result['status'], result['error_code'], result['labels']), ('error', '100', []))
        self.assertIn('Kimlik reddedildi', result['error_message'])
        self.assertEqual(set(self.ups.ups_tr_cargo_cancel(shipment)), CANCEL_KEYS)
        self.assertEqual(set(self.ups.ups_tr_cargo_find(shipment)), FIND_KEYS)

    def test_send_odp_ve_odp_yok(self):
        cases = (
            ({'cod_amount': 1249.9, 'cod_method': 'cash'}, ('1249.90', 'TL', '1')),
            ({'cod_amount': 0.0}, ('0', '', '0')),
            ({'cod_amount': 0.004, 'cod_method': 'cash'}, ('0', '', '0')),
        )
        for over, expected in cases:
            with self.subTest(**over):
                self.assertEqual(self.ups.ups_tr_cargo_send(self.shipment(**over))['status'], 'ok')
                root = self.create_info()
                self.assertEqual(tuple(find_text(root, name) for name in (
                    'ValueOfGoods', 'ValueOfGoodsCurrency', 'ValueOfGoodsPaymentType')), expected)
                self.assertEqual(find_text(root, 'InsuranceValue'), '0')
                self.assertEqual(find_text(root, 'Weight'), '1.500')
                self.assertFalse(find_text(root, 'DeliveryNotificationEmail'), 'KVKK: UPS alıcıya e-posta atmaz')

    def test_cod_code(self):
        self.assertEqual([self.ups.ups_tr_cargo_cod_code(m) for m in ('cash', 'check', 'card', 'havale', False)],
                         ['1', '2', '3', '', ''])
        # tahsil şekli olmayan ODP UPS'e gitmez (çekirdek doğrulamasını aşan veri savunması)
        result = self.ups.ups_tr_cargo_send(self.shipment(cod_amount=100.0, cod_method=False))
        self.assertEqual(result['status'], 'error')
        self.assertEqual(self.net.requests, [])

    def test_send_gonderici_gonderinin_sirketinden(self):
        """Çok şirket: gönderici env.company değil gönderinin şirketidir."""
        other = self.env['res.company'].create({
            'name': 'G9 Ikinci Sirket', 'street': 'Ankara Cad. 5', 'city': 'Cankaya', 'state_id': self.st('06').id,
            'country_id': self.env.ref('base.tr').id, 'phone': '+90 532 111 22 33', 'email': 'iki@example.com'})
        self.assertNotEqual(self.env.company, other)
        self.ups.ups_tr_cargo_send(self.shipment(company_id=other.id))
        root = self.create_info()
        self.assertEqual(find_text(root, 'ShipperName'), 'G9 Ikinci Sirket')
        self.assertEqual(find_text(root, 'ShipperAddress'), 'Ankara Cad. 5')
        self.assertEqual(find_text(root, 'ShipperAreaCode'), str(self.ups_cankaya.area_code))
        self.assertEqual((find_text(root, 'ShipperMobilePhoneNumber'), find_text(root, 'ShipperPhoneNumber')),
                         ('905321112233', ''))
        self.ups.ups_tr_cargo_send(self.shipment())
        root = self.create_info()
        self.assertEqual(find_text(root, 'ShipperAreaCode'), str(self.ups_kadikoy.area_code))
        self.assertEqual(find_text(root, 'ShipperAddress'), 'Test Cad. No:1 Kat 2')
        self.assertEqual(find_text(root, 'ShipperPhoneNumber'), '02161234567')

    def test_send_istisna_firlatmaz(self):
        shipment = self.shipment()
        cases = (
            ('_ups_tr_shipment_info', type(self.ups), RuntimeError('hazirlik'), 'error', 0),
            ('login', ups_soap.UpsClient, KeyError('login'), 'error', 0),
            ('create_shipment', ups_soap.UpsClient, KeyError('create'), 'uncertain', 1),
        )
        for name, owner, exc, status, http in cases:
            with self.subTest(name=name), patch.object(owner, name, side_effect=exc):
                self.net.requests.clear()
                result = self.ups.ups_tr_cargo_send(shipment)
                self.assertEqual((result['status'], len(self.net.requests)), (status, http))
                self.assertEqual(set(result), SEND_KEYS)
                self.assertNotIn(str(exc), result['error_message'])
        with patch.object(ups_soap.UpsClient, 'cancel', side_effect=KeyError('c')):
            self.assertEqual(self.ups.ups_tr_cargo_cancel(self.created())['status'], 'uncertain')
        with patch.object(ups_soap.UpsClient, 'find_by_reference', side_effect=KeyError('f')):
            self.assertEqual(self.ups.ups_tr_cargo_find(self.created(test_mode=False))['status'], 'error')

    def test_send_barkod_eksik_bozuk(self):
        """Kısmi etiket: bozuk base64 ve PNG olmayan veri atlanır, gönderi yine 'ok' (UPS'te açıldı)."""
        good = base64.b64encode(make_label_png(0)).decode()
        bad = base64.b64encode(b'GIF89a-degil-png').decode()
        body = create_ok(n=1).replace(good, good + '</string><string>%%%bozuk%%%</string><string>' + bad)
        self.plan['CreateShipment_Type3'] = body
        result = self.ups.ups_tr_cargo_send(self.shipment(package_count=3))
        self.assertEqual((result['status'], result['labels']), ('ok', [make_label_png(0)]))
        self.plan['CreateShipment_Type3'] = create_ok().replace('<ShipmentNo>1ZFIXTURE0001</ShipmentNo>', '<ShipmentNo />')
        result = self.ups.ups_tr_cargo_send(self.shipment())
        self.assertEqual((result['status'], result['tracking_ref']), ('uncertain', ''),
                         'ErrorCode 0 ama takip no yok: failed olursa mükerrer gönderi açılır')

    def test_cancel_takipsiz_http_yok(self):
        result = self.ups.ups_tr_cargo_cancel(self.shipment())
        self.assertEqual(result['status'], 'error')
        self.assertEqual(self.net.requests, [])
        self.plan['Cancel_Shipment_V1'] = cancel_result(41, 'Kargoya verilmis')
        result = self.ups.ups_tr_cargo_cancel(self.created())
        self.assertEqual((result['status'], result['error_code']), ('error', '41'))
        self.assertIn('Kargoya verilmis', result['error_message'])

    def test_cancel_uc_gonderinin_test_moduna_bagli(self):
        """Ebeveyn değişimi: firma bayrağı gönderiden sonra değişse de iptal gönderinin açıldığı uca gider."""
        test_shipment = self.created(test_mode=True)
        live_shipment = self.created(test_mode=False)
        self.ups.prod_environment = True
        self.assertEqual(self.ups.ups_tr_cargo_cancel(test_shipment)['status'], 'ok')
        self.assertEqual({r['url'] for r in self.net.requests}, {URL_TEST})
        self.net.requests.clear()
        self.ups.prod_environment = False
        self.assertEqual(self.ups.ups_tr_cargo_cancel(live_shipment)['status'], 'ok')
        self.assertEqual({r['url'] for r in self.net.requests}, {URL_LIVE})
        self.assertEqual(find_text(parse(self.ups_requests('Cancel_Shipment_V1')[0]), 'waybillNumber'), '1ZG9IPTAL')

    def test_find_test_modu_http_yok(self):
        self.ups.prod_environment = True
        result = self.ups.ups_tr_cargo_find(self.created(test_mode=True))
        self.assertEqual(result, {'status': 'not_found', 'tracking_ref': '', 'count': 0, 'error_message': ''})
        self.assertEqual(self.net.requests, [])

    def test_find_cok_paketli_tek_gonderi(self):
        shipment = self.created(test_mode=False)
        self.plan['GetPackageInfoByReferance_V1'] = query_packages(
            [('1ZP1', '1ZGONDERI', shipment.name), ('1ZP2', '1ZGONDERI', shipment.name), ('1ZP3', '1ZGONDERI', shipment.name)])
        result = self.ups.ups_tr_cargo_find(shipment)
        self.assertEqual((result['status'], result['count'], result['tracking_ref']), ('found', 1, '1ZGONDERI'),
                         'paket başına öğe -> yanlış "birden çok kayıt" uyarısı çıkmamalı')
        self.assertEqual({r['url'] for r in self.net.requests}, {URL_QUERY})
        self.plan['GetPackageInfoByReferance_V1'] = make_response(query_error(5, 'yok'))
        result = self.ups.ups_tr_cargo_find(shipment)
        self.assertEqual((result['status'], result['count']), ('error', 0))

    def test_find_takip_kimligi_yedegi(self):
        shipment = self.created(test_mode=False)
        self.ups.ups_tr_cargo_find(shipment)
        self.ups.write({'ups_tr_track_username': False, 'ups_tr_track_password': False})
        self.ups.ups_tr_cargo_find(shipment)
        logins = [parse(r) for r in self.ups_requests('Login_V1')]
        self.assertEqual([(find_text(r, 'UserName'), find_text(r, 'Password')) for r in logins],
                         [(SECRETS['track_user'], SECRETS['track_password']), (SECRETS['user'], SECRETS['password'])])
        self.assertEqual([operation(r) for r in self.net.requests],
                         ['Login_V1', 'GetPackageInfoByReferance_V1'] * 2, 'her sorguda yeni oturum')

    def test_sonuc_ve_log_sir_icermez(self):
        leaky = 'k %(user)s s %(password)s m %(customer)s h %(shipper)s oturum %(session)s t %(track_user)s %(track_password)s' % SECRETS
        fault = envelope('<soap:Fault><faultstring>%s</faultstring></soap:Fault>' % leaky)
        shipment = self.created(test_mode=False, recipient_phone='05329998877')
        calls = (
            ('send', {'CreateShipment_Type3': create_err(9, leaky + ' ' + LINK_WITH_KEY)}),
            ('send', {'CreateShipment_Type3': make_response(fault, 500)}),
            ('send', {'CreateShipment_Type3': requests.ReadTimeout(leaky)}),
            ('send', {'Login_Type1': login_err(5, leaky)}),
            ('send', {}),
            ('cancel', {'Cancel_Shipment_V1': cancel_result(4, leaky)}),
            ('find', {'GetPackageInfoByReferance_V1': query_error(5, leaky)}),
            ('find', {'Login_V1': RuntimeError(leaky)}),
        )
        for op, plan in calls:
            with self.subTest(op=op, plan=list(plan)):
                self.plan.clear()
                self.plan.update(plan)
                with LogTap() as logs:
                    result = getattr(self.ups, 'ups_tr_cargo_%s' % op)(shipment)
                texts = {'log': logs.text, 'sonuc': str({k: v for k, v in result.items() if k != 'labels'})}
                for where, text in texts.items():
                    for secret in SECRET_VALUES + ['LabelKey', SECRETS['customer'][:-2], SECRETS['shipper'][:-2]]:
                        self.assertNotIn(secret, text, '%s sızdı: %s' % (where, secret))
                self.assertNotIn('9998877', logs.text, 'telefon loglanmaz')
                self.assertNotIn('Envelope', logs.text, 'gövde loglanmaz')
                self.assertTrue(any('UPS' in line for line in logs.lines), 'işlem logu yazılır')
        self.assertTrue(logging.getLogger(ups_soap.__name__).name.startswith('odoo.addons.cargo_ups'))
