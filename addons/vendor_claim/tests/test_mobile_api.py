import base64
from unittest.mock import patch

from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user

from .common import VcCase

# 1x1 PNG
PIXEL = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='


@tagged('post_install', '-at_install')
class TestVendorClaimMobileApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('sms_system.test_mode', 'True')
        icp.set_param('sms_system.turatel_originator', 'TEST')
        new_test_user(cls.env, login='vc_mobile', password='vc_mobile_pw1', groups='base.group_user')
        new_test_user(cls.env, login='vc_portal', password='vc_portal_pw1', groups='base.group_portal')
        attr = cls.env['product.attribute'].create({'name': 'Tedarikçi', 'create_variant': 'no_variant'})
        value = cls.env['product.attribute.value'].create({'name': 'Mobil Tedarik', 'attribute_id': attr.id})
        tmpl = cls.env['product.template'].create({
            'name': 'Mobil Ayakkabı', 'default_code': 'AYK-1',
            'attribute_line_ids': [(0, 0, {'attribute_id': attr.id, 'value_ids': [(6, 0, value.ids)]})],
        })
        tmpl.product_variant_id.barcode = '8690000000202'

    def _rpc(self, route, **params):
        return self.make_jsonrpc_request(route, params)

    def test_portal_user_blocked(self):
        self.authenticate('vc_portal', 'vc_portal_pw1')
        with self.assertRaises(Exception):
            self._rpc('/vendor_claim/stats')

    def test_mobile_flow(self):
        self.authenticate('vc_mobile', 'vc_mobile_pw1')
        detail = {'invoice_no': 'UGR-3003', 'invoice_date': '2026-10-03', 'customer_code': 'C-9',
                  'customer_name': 'Deniz Kaya', 'sales_person': 'Ece', 'customer_mobile': '05551112233',
                  'items': [{'barcode': '8690000000202', 'product_code': 'AYK-1', 'quantity': 1}]}
        connector = self.env.registry['ugurlar.tailor.mssql.connector']
        with patch.object(connector, 'get_invoice_detail', return_value=dict(detail)):
            inv = self._rpc('/vendor_claim/invoice_detail', invoice_no='UGR-3003')
        self.assertEqual(inv['items'][0]['vendor'], 'Mobil Tedarik')
        self.assertEqual(inv['existing'], [])

        self.assertIn('error', self._rpc('/vendor_claim/create', data={'customer_name': 'X'}))
        res = self._rpc('/vendor_claim/create', data={
            'invoice_no': 'UGR-3003', 'invoice_date': '2026-10-03', 'invoice_items': inv['items'],
            'customer_code': 'C-9', 'customer_name': 'Deniz Kaya', 'customer_mobile': '5551112233',
            'product_barcode': '8690000000202', 'quantity': 1, 'defect_description': 'Taban ayrıldı',
            'customer_request': 'replace',
        }, photos=['data:image/png;base64,' + PIXEL, 'not-a-photo'])
        self.assertTrue(res['name'].startswith('INC-'))
        self.assertEqual(res['vendor'], 'Mobil Tedarik')
        claim = self.env['vendor.claim'].browse(res['id'])
        self.assertEqual(len(claim.photo_ids), 1)
        self.assertEqual(claim.photo_ids.res_id, claim.id)
        self.assertEqual(claim.customer_mobile, '05551112233')

        found = self._rpc('/vendor_claim/find', code='8690000000202')
        self.assertEqual(found['id'], claim.id)
        listed = self._rpc('/vendor_claim/list', search='Deniz', status='open')
        self.assertEqual([c['id'] for c in listed['items']], [claim.id])

        d = self._rpc('/vendor_claim/action', claim_id=claim.id, action='send',
                      vals={'out_carrier': 'Aras', 'out_tracking': 'A123'})
        self.assertEqual(d['state'], 'sent')
        self.assertEqual(d['out_tracking'], 'A123')
        # sonuçsuz dönüş reddedilir, durum değişmez
        self.assertIn('error', self._rpc('/vendor_claim/action', claim_id=claim.id, action='return', vals={}))
        d = self._rpc('/vendor_claim/action', claim_id=claim.id, action='note', vals={'note': 'Tedarikçi arandı'})
        self.assertEqual(d['state'], 'sent')
        self.assertIn('Tedarikçi arandı', [n['body'] for n in d['notes_log']])

        bulk = self._rpc('/vendor_claim/bulk', claim_ids=[claim.id, 999999], action='return',
                         vals={'result': 'replaced', 'in_tracking': 'B9'})
        self.assertEqual([r['ok'] for r in bulk['results']], [True, False])
        claim.invalidate_recordset()
        self.assertEqual(claim.state, 'returned')
        self.assertEqual(claim.result, 'replaced')

        self.assertTrue(self._rpc('/vendor_claim/send_sms', claim_id=claim.id).get('ok'))
        d = self._rpc('/vendor_claim/action', claim_id=claim.id, action='deliver')
        self.assertEqual(d['state'], 'delivered')
        stats = self._rpc('/vendor_claim/stats')
        self.assertEqual(stats['returned'], 0)

        # Müşteri fişi PDF yerine HTML olarak render edilebiliyor mu (wkhtmltopdf testte yok olabilir)
        resp = self.url_open('/report/html/vendor_claim.report_vendor_claim_slip/%s' % claim.id)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(claim.name, resp.text)


@tagged('post_install', '-at_install')
class TestMobileSmsGuards(VcCase):
    """B6: mobil SMS ucunun kilit/koruma davranışı (kabul testlerini tamamlar)."""

    def test_satir_kilidi_alinamazsa_hata_ve_sifir_kayit(self):
        claim = self.make_claim()
        with patch.object(self.env.registry['vendor.claim'], '_lock_for_manual_sms', return_value=False):
            res = self.controller('send_sms', claim_id=claim.id)
        self.assertIn('SMS işlemi sürüyor', res.get('error', ''))
        self.assertFalse(self.claim_sms(claim))

    def test_gercek_satir_kilidi_alinir(self):
        claim = self.make_claim()
        self.assertTrue(claim._lock_for_manual_sms())

    def test_canli_modda_hatirlatma_kuyruga_alininca_da_sayac_artar(self):
        self.set_param('test_mode', 'False')
        claim = self.make_claim()
        self.force_state(claim, 'returned', sms_returned_sent=True, returned_at=self.ago(days=1))
        res = self.controller('send_sms', claim_id=claim.id)
        self.assertTrue(res.get('ok'), res)
        self.assertEqual(res['sms']['state'], 'queued')
        claim.invalidate_recordset()
        self.assertEqual(claim.reminder_count, 1)

    def test_hata_yolunda_sayac_artmaz(self):
        self.set_param('user_daily_limit', '1')
        first = self.make_claim(customer_mobile='05321234560')
        self.assertTrue(self.controller('send_sms', claim_id=first.id).get('ok'))
        claim = self.make_claim(customer_mobile='05321234561')
        self.force_state(claim, 'returned', sms_returned_sent=True, returned_at=self.ago(days=1))
        res = self.controller('send_sms', claim_id=claim.id)
        self.assertIn('Günlük elle SMS sınırınız doldu', res.get('error', ''))
        claim.invalidate_recordset()
        self.assertEqual(claim.reminder_count, 0)

    def test_yanit_sms_durumu_tasir(self):
        claim = self.make_claim()
        res = self.controller('send_sms', claim_id=claim.id)
        self.assertEqual(res['sms'], {'state': 'test', 'error': ''})
