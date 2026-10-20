import re
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user

from .common import PIXEL, VcCase


@tagged('post_install', '-at_install')
class TestVendorClaim(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('sms_system.test_mode', 'True')
        icp.set_param('sms_system.turatel_originator', 'TEST')
        for event in ('received', 'sent', 'returned', 'delivered', 'reminder'):
            icp.set_param('vendor_claim.sms_%s_enabled' % event, 'True')
        cls.user = new_test_user(cls.env, login='vc_user', groups='base.group_user')
        attr = cls.env['product.attribute'].create({'name': 'Tedarikçi', 'create_variant': 'no_variant'})
        value = cls.env['product.attribute.value'].create({'name': 'ABC Tekstil', 'attribute_id': attr.id})
        cls.template = cls.env['product.template'].create({
            'name': 'Test Ceket', 'default_code': 'CKT-1',
            'attribute_line_ids': [(0, 0, {'attribute_id': attr.id, 'value_ids': [(6, 0, value.ids)]})],
        })
        cls.product = cls.template.product_variant_id
        cls.product.barcode = '8690000000011'
        cls.Claim = cls.env['vendor.claim'].with_user(cls.user)

    def _claim(self, **vals):
        base = {'customer_name': 'Ali Veli', 'customer_mobile': '05321234567', 'defect_description': 'Fermuar bozuk',
                'product_barcode': '8690000000011'}
        base.update(vals)
        return self.Claim.create(base)

    def _sms(self, claim):
        return self.env['sms.system.message'].sudo().search(
            [('res_model', '=', 'vendor.claim'), ('res_id', '=', claim.id)])

    def test_create_resolves_product_and_vendor(self):
        claim = self._claim()
        self.assertTrue(claim.name.startswith('INC-'))
        self.assertEqual(claim.product_id, self.product)
        self.assertEqual(claim.vendor_name, 'ABC Tekstil')
        self.assertEqual(claim.vendor_id.name, 'ABC Tekstil')
        self.assertTrue(claim.vendor_id.supplier_rank > 0)
        # Aynı tedarikçi için ikinci kayıt aynı kartı kullanır
        self.assertEqual(self._claim().vendor_id, claim.vendor_id)
        self.assertEqual(claim.vendor_id.vendor_claim_count, 2)

    def test_full_flow_and_sms_once_per_state(self):
        claim = self._claim()
        self.assertTrue(claim.sms_received_sent)
        claim.action_send_to_vendor()
        self.assertEqual(claim.state, 'sent')
        self.assertTrue(claim.sent_at and claim.sms_sent_sent)
        with self.assertRaises(UserError):  # sonuç seçilmeden dönüş yok
            claim.action_mark_returned()
        claim.result = 'repaired'
        claim.action_mark_returned()
        self.assertEqual(claim.state, 'returned')
        self.assertTrue(claim.sms_returned_sent)
        claim.action_send_to_vendor()   # tekrar gönderim: aynı SMS bir daha gitmez
        claim.result = 'replaced'
        claim.action_mark_returned()
        claim.action_mark_delivered()
        self.assertEqual(claim.state, 'delivered')
        self.assertTrue(claim.sms_delivered_sent)
        self.assertEqual(len(self._sms(claim)), 4)
        self.assertIn(claim.name, self._sms(claim)[0].body)

    def test_transitions_for_user(self):
        claim = self._claim()
        with self.assertRaises(UserError):
            claim.action_mark_delivered()
        with self.assertRaises(UserError):
            claim.write({'state': 'returned'})
        claim.action_send_to_vendor()
        claim.result = 'rejected'
        claim.action_mark_returned()
        claim.action_mark_delivered()
        with self.assertRaises(UserError):  # teslim edilen kaydı yalnız yönetici değiştirir
            claim.action_reset_to_received()
        claim.with_user(self.env.ref('base.user_admin')).action_reset_to_received()
        self.assertEqual(claim.state, 'received')

    def test_send_requires_vendor(self):
        claim = self._claim(product_barcode=False, product_id=False)
        self.assertFalse(claim.vendor_id)
        with self.assertRaises(UserError):
            claim.action_send_to_vendor()

    def test_sms_disabled_and_invalid_number(self):
        self.env['ir.config_parameter'].sudo().set_param('vendor_claim.sms_received_enabled', 'False')
        claim = self._claim()
        self.assertFalse(claim.sms_received_sent)
        self.assertFalse(self._sms(claim))
        bad = self._claim(customer_mobile='02121234567')   # sabit hat: durum ilerler, SMS gitmez
        bad.action_send_to_vendor()
        self.assertEqual(bad.state, 'sent')
        self.assertFalse(bad.sms_sent_sent)

    def test_fetch_invoice(self):
        detail = {
            'invoice_no': 'UGR-1001', 'invoice_date': '2026-10-01 00:00:00', 'customer_code': 'C-77',
            'customer_name': 'Ayşe Yılmaz', 'sales_person': 'Mehmet', 'customer_mobile': '5329876543',
            'items': [{'barcode': '8690000000011', 'product_code': 'CKT-1', 'quantity': 1},
                      {'barcode': '8690000000099', 'product_code': 'XX-9', 'quantity': 2}],
        }
        connector = self.env.registry['ugurlar.tailor.mssql.connector']
        with patch.object(connector, 'get_invoice_detail', return_value=dict(detail)):
            claim = self.Claim.create({'customer_name': '-', 'defect_description': 'Söküldü',
                                       'invoice_no': 'UGR-1001', 'product_barcode': '8690000000011'})
            claim.action_fetch_invoice()
        self.assertEqual(claim.customer_name, 'Ayşe Yılmaz')
        self.assertEqual(claim.customer_code, 'C-77')
        self.assertEqual(claim.customer_mobile, '05329876543')
        self.assertEqual(str(claim.invoice_date), '2026-10-01')
        self.assertEqual(len(claim.invoice_items), 2)
        self.assertEqual(claim.product_id, self.product)
        self.assertEqual(claim.vendor_id.name, 'ABC Tekstil')
        self.assertIn('XX-9', claim.invoice_items_html)
        with patch.object(connector, 'get_invoice_detail', return_value=None):
            with self.assertRaises(UserError):
                claim.action_fetch_invoice()

    def test_return_reminder_cron(self):
        claim = self._claim()
        claim.action_send_to_vendor()
        claim.result = 'repaired'
        claim.action_mark_returned()
        claim.sudo().returned_at = fields.Datetime.now() - timedelta(days=5)
        Claim = self.env['vendor.claim']
        # Cron kayıt başına commit eder; TransactionCase'te commit yasak
        with patch.object(self.env.registry['ir.cron'], '_commit_progress',
                          lambda cron, processed=0, **kw: cron.env.flush_all() or 1000.0):
            Claim._cron_return_reminders()
            self.assertEqual(claim.reminder_count, 1)
            Claim._cron_return_reminders()   # aynı gün tekrar gönderilmez
            self.assertEqual(claim.reminder_count, 1)

    def test_overdue_alert_once(self):
        claim = self._claim()
        claim.action_send_to_vendor()
        claim.sudo().sent_at = fields.Datetime.now() - timedelta(days=20)
        self.assertTrue(claim.is_overdue)
        self.assertIn(claim, self.env['vendor.claim'].search([('is_overdue', '=', True)]))
        Claim = self.env['vendor.claim']
        Claim._cron_overdue_alerts()
        Claim._cron_overdue_alerts()
        self.assertTrue(claim.overdue_notified)
        self.assertEqual(len(claim.activity_ids), 1)
        self.assertEqual(claim.activity_ids.user_id, self.user)
        claim.result = 'refund'
        claim.action_mark_returned()   # dönünce aktivite kapanır
        self.assertFalse(claim.activity_ids)

    def test_reports_render(self):
        claim = self._claim()
        for xmlid in ('vendor_claim.action_report_vendor_claim_form', 'vendor_claim.action_report_vendor_claim_slip'):
            html = self.env['ir.actions.report']._render_qweb_html(xmlid, claim.ids)[0]
            self.assertIn(claim.name.encode(), html)

    def test_slip_pdf_turkce_karakter(self):
        """Fiş gerçek PDF'te Türkçe basılır: div.article yoksa Odoo charset'siz HTML verir, wkhtmltopdf Latin-1 okur."""
        import io
        from odoo.tools.pdf import PdfFileReader
        claim = self._claim()
        pdf = self.env['ir.actions.report'].with_context(force_report_rendering=True)._render_qweb_pdf(
            'vendor_claim.action_report_vendor_claim_slip', claim.ids)[0]
        text = '\n'.join(p.extract_text() for p in PdfFileReader(io.BytesIO(pdf)).pages)
        self.assertIn('Ürün İnceleme Teslim Fişi', text)
        self.assertIn('Şikayet', text)
        self.assertNotIn('Ã', text, 'UTF-8 metin Latin-1 okunmuş')
        self.assertIn('Tarih:', text)

    def test_slip_barcode_invoice_or_name(self):
        """Fişteki barkod: fatura varsa fatura no (listede okutulunca bulunur), yoksa takip no."""
        Report = self.env['ir.actions.report']
        slip = 'vendor_claim.action_report_vendor_claim_slip'
        with_inv = self._claim(invoice_no='UGR2026000012388')
        html = Report._render_qweb_html(slip, with_inv.ids)[0]
        self.assertIn(b'/report/barcode/Code128/UGR2026000012388?', html)
        self.assertIn(with_inv.name.encode(), html)
        no_inv = self._claim()
        html = Report._render_qweb_html(slip, no_inv.ids)[0]
        self.assertIn(('/report/barcode/Code128/%s?' % no_inv.name).encode(), html)

    def test_form_onchange_invoice(self):
        from odoo.tests import Form
        detail = {
            'invoice_no': 'UGR-2002', 'invoice_date': '2026-10-02', 'customer_code': 'C-88',
            'customer_name': 'Can Demir', 'sales_person': 'Zeynep', 'customer_mobile': '',
            'items': [{'barcode': '8690000000011', 'product_code': 'CKT-1', 'quantity': 1}],
        }
        connector = self.env.registry['ugurlar.tailor.mssql.connector']
        with patch.object(connector, 'get_invoice_detail', return_value=dict(detail)):
            form = Form(self.Claim)
            form.invoice_no = 'UGR-2002'
            self.assertEqual(form.customer_name, 'Can Demir')
            self.assertEqual(form.product_barcode, '8690000000011')
            self.assertEqual(form.vendor_name, 'ABC Tekstil')
            form.defect_description = 'Dikiş açıldı'
            claim = form.save()
        self.assertEqual(claim.product_id, self.product)
        self.assertEqual(claim.vendor_id.name, 'ABC Tekstil')   # kart kayıtta oluşur
        self.assertFalse(claim.customer_mobile)


@tagged('post_install', '-at_install')
class TestVendorClaimMultiItem(VcCase):
    """Mobil 'Yeni İnceleme': fatura ürünlerinden çoklu seçim → ürün başına kayıt, tek SMS, tek fiş."""

    SLIP = 'vendor_claim.action_report_vendor_claim_slip'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        attr = cls.env['product.attribute'].search([('name', '=', 'Tedarikçi')], limit=1)
        value = cls.env['product.attribute.value'].create({'name': 'XYZ Deri', 'attribute_id': attr.id})
        cls.product2 = cls.env['product.template'].create({
            'name': 'Test Çanta', 'default_code': 'CNT-T2',
            'attribute_line_ids': [(0, 0, {'attribute_id': attr.id, 'value_ids': [(6, 0, value.ids)]})],
        }).product_variant_id
        cls.product2.barcode = '8690000000328'

    def setUp(self):
        super().setUp()
        self.icp.set_param('vendor_claim.sms_received_enabled', 'True')

    def _data(self, **extra):
        data = {'invoice_no': 'UGR-5005', 'invoice_date': '2026-10-05', 'customer_code': 'C-5',
                'customer_name': 'Ayşe Çelik', 'customer_mobile': '05321234567', 'sales_person': 'Ece'}
        data.update(extra)
        return data

    def _items(self):
        return [
            {'product_barcode': '8690000000311', 'product_code': 'CKT-T1', 'quantity': 1,
             'defect_description': 'Fermuar bozuk', 'customer_request': 'repair',
             'photos': ['data:image/png;base64,' + PIXEL]},
            {'product_barcode': '8690000000328', 'product_code': 'CNT-T2', 'quantity': 2,
             'defect_description': 'Sap kopmuş', 'customer_request': 'replace',
             'photos': ['data:image/png;base64,' + PIXEL, 'data:image/png;base64,' + PIXEL]},
            {'product_barcode': '8690000000311', 'product_code': 'CKT-T1', 'quantity': 1,
             'defect_description': 'Dikiş açık'},
        ]

    def _all_sms(self, claims):
        return self.env['sms.system.message'].sudo().search(
            [('res_model', '=', 'vendor.claim'), ('res_id', 'in', claims.ids)])

    def _sms_count(self):
        return self.env['sms.system.message'].sudo().search_count([('res_model', '=', 'vendor.claim')])

    def _create(self, items=None, data=None):
        res = self.controller('create_claim', data=data or self._data(), items=items or self._items())
        self.assertNotIn('error', res, res)
        return res, self.Claim.browse([c['id'] for c in res['claims']])

    def _html(self, claims):
        return self.env['ir.actions.report']._render_qweb_html(self.SLIP, claims.ids)[0].decode()

    def test_coklu_urun_n_kayit_acar(self):
        res, claims = self._create()
        self.assertEqual(len(claims), 3)
        self.assertEqual(len(set(claims.mapped('name'))), 3)
        self.assertTrue(all(n.startswith('INC-') for n in claims.mapped('name')))
        # ürün başına kendi şikayeti / talebi / tedarikçisi / fotoğrafı
        self.assertEqual(claims.mapped('defect_description'), ['Fermuar bozuk', 'Sap kopmuş', 'Dikiş açık'])
        self.assertEqual(claims.mapped('customer_request'), ['repair', 'replace', 'inspect'])
        self.assertEqual([c.vendor_id.name for c in claims], ['ABC Tekstil', 'XYZ Deri', 'ABC Tekstil'])
        self.assertEqual([len(c.photo_ids) for c in claims], [1, 2, 0])
        self.assertEqual(claims.mapped('quantity'), [1.0, 2.0, 1.0])
        # müşteri / fatura ortak
        self.assertEqual(set(claims.mapped('customer_name')), {'Ayşe Çelik'})
        self.assertEqual(set(claims.mapped('invoice_no')), {'UGR-5005'})
        # yanıt: tüm kayıtlar + tek fiş URL'si
        self.assertEqual([c['name'] for c in res['claims']], claims.mapped('name'))
        self.assertEqual(res['claims'][1]['vendor'], 'XYZ Deri')
        self.assertEqual(res['id'], claims[0].id)
        self.assertEqual(res['slip_url'], '/report/pdf/vendor_claim.report_vendor_claim_slip/%s'
                         % ','.join(map(str, claims.ids)))

    def test_tek_sms_ve_takip_nolar_birlesik(self):
        res, claims = self._create()
        messages = self._all_sms(claims)
        self.assertEqual(len(messages), 1, 'müşteriye tek SMS')
        self.assertIn(', '.join(claims.mapped('name')), messages.body)
        self.assertEqual(res['sms']['state'], messages.state)
        self.assertEqual(messages.state, 'test')
        # diğer kayıtların bayrağı da işaretli: sonradan tekrar SMS gitmez
        self.assertTrue(all(claims.mapped('sms_received_sent')))
        claims._notify_state_sms(group=True)
        claims._notify_state_sms()
        self.assertEqual(len(self._all_sms(claims)), 1)

    def test_tek_sms_canli_modda_kuyrukta_tek_kayit(self):
        self.set_param('test_mode', 'False')
        res, claims = self._create()
        messages = self._all_sms(claims)
        self.assertEqual(len(messages), 1)
        self.assertEqual((messages.state, res['sms']['state']), ('queued', 'queued'))
        self.assertEqual(self.net.turatel_calls, [], 'istek içinde sağlayıcı çağrısı yok')

    def test_sms_yer_tutuculari_coklu(self):
        _res, claims = self._create()
        values = claims._sms_values()
        self.assertEqual(values['urun'], '3 ürün')
        self.assertEqual(values['takip'], ', '.join(claims.mapped('name')))
        self.assertEqual(values['tedarikci'], '', 'farklı tedarikçiler: boş (ilki diğerleri için yanlış olur)')
        self.assertEqual(values['musteri'], 'Ayşe Çelik')
        same = (claims[0] | claims[2])._sms_values()
        self.assertEqual((same['urun'], same['tedarikci']), ('2 ürün', 'ABC Tekstil'))
        single = claims[1]._sms_values()   # tek kayıt: eski davranış
        self.assertEqual((single['takip'], single['tedarikci']), (claims[1].name, 'XYZ Deri'))

    def test_bir_oge_hataliysa_hic_kayit_ve_sms_yok(self):
        before = self.Claim.search_count([])
        sms_before = self._sms_count()
        items = self._items()
        items[1]['defect_description'] = '   '   # ikinci ürünün şikayeti boş
        res = self.controller('create_claim', data=self._data(), items=items)
        self.assertIn('2. ürün', res.get('error', ''))
        self.assertEqual(self.Claim.search_count([]), before)
        self.assertEqual(self._sms_count(), sms_before)
        items = self._items()
        items[2]['product_barcode'] = ''
        self.assertIn('3. ürün', self.controller('create_claim', data=self._data(), items=items).get('error', ''))
        self.assertEqual(self.Claim.search_count([]), before)

    def test_kayit_asamasinda_hata_tum_kayitlari_ve_smsi_geri_alir(self):
        """Üçüncü ürünün fotoğraf adımı patlarsa ilk ikisi ve SMS de kalmaz (tek savepoint)."""
        from odoo.addons.vendor_claim.controllers.vendor_claim_controller import VendorClaimController
        real = VendorClaimController._attach_photos
        calls = []

        def flaky(ctrl, claim, photos):
            calls.append(claim.id)
            if len(calls) == 3:
                raise ValueError('disk dolu')
            return real(ctrl, claim, photos)

        before = self.Claim.search_count([])
        sms_before = self._sms_count()
        with patch.object(VendorClaimController, '_attach_photos', flaky):
            res = self.controller('create_claim', data=self._data(), items=self._items())
        self.assertIn('error', res)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.Claim.search_count([]), before)
        self.assertEqual(self._sms_count(), sms_before)

    def test_ortak_not_tum_kayitlara_yazilir(self):
        """Mobil ortak 'Not' alanını `data.notes` ile yollar; çoklu yolda tüm kayıtlara yazılmalı."""
        _res, claims = self._create(data=self._data(notes='  Müşteri acil istiyor  '))
        self.assertEqual(claims.mapped('notes'), ['Müşteri acil istiyor'] * 3)
        # ürünün kendi notu varsa ortak not onu ezmez
        items = self._items()
        items[1]['notes'] = 'Sadece bu ürün'
        _res, claims = self._create(data=self._data(notes='Ortak', invoice_no='UGR-5006'), items=items)
        self.assertEqual(claims.mapped('notes'), ['Ortak', 'Sadece bu ürün', 'Ortak'])

    def test_uzun_takip_listesi_kisaltilir_sms_yine_gider(self):
        """20 ürün: {takip} birleşimi sınırı aşarsa 'INC-1, INC-2 ve N kayıt daha'; SMS kaydı oluşur."""
        from odoo.addons.sms_system.services.turatel_json import MAX_TEXT_LENGTH
        self.configure_json(test_mode='True')
        template = self.env['sms.system.template'].get_by_code('vendor_claim_received')
        template.body += ' Ürününüzün durumunu öğrenmek için mağazamızı arayabilir veya mağazaya uğrayabilirsiniz.' * 2
        items = [dict(self._items()[0]) for _i in range(20)]
        res, claims = self._create(items=items)
        self.assertEqual(len(claims), 20)
        messages = self._all_sms(claims)
        self.assertEqual(len(messages), 1, 'sınır aşılsa da müşteriye SMS gider')
        self.assertEqual((res['sms']['state'], res['sms']['error']), ('test', ''))
        self.assertEqual(messages.state, res['sms']['state'])
        self.assertLessEqual(len(messages.body), MAX_TEXT_LENGTH)
        self.assertRegex(messages.body, r'%s.* ve \d+ kayıt daha' % claims[0].name)
        self.assertNotIn(claims[-1].name, messages.body)
        self.assertTrue(all(claims.mapped('sms_received_sent')))
        # kısaltma payı: gösterilen + "N kayıt daha" = toplam
        shown = messages.body.count('INC-')
        more = int(re.search(r've (\d+) kayıt daha', messages.body).group(1))
        self.assertEqual(shown + more, 20)

    def test_kisa_takip_listesi_oldugu_gibi_kalir(self):
        _res, claims = self._create()
        self.assertNotIn('kayıt daha', self._all_sms(claims).body)
        self.assertEqual(claims._sms_values_fit('vendor_claim_received')['takip'], ', '.join(claims.mapped('name')))

    def test_eski_modda_parca_siniri(self):
        """Eski (XML) modda sınır 7 parça: aşılırsa yine kısaltılır."""
        self.set_param('api_mode', 'legacy_xml')
        template = self.env['sms.system.template'].get_by_code('vendor_claim_received')
        template.body += ' Ürününüzün durumunu öğrenmek için mağazamızı arayabilir.' * 14
        items = [dict(self._items()[0]) for _i in range(20)]
        res, claims = self._create(items=items)
        messages = self._all_sms(claims)
        self.assertEqual(len(messages), 1)
        self.assertEqual((res['sms']['state'], res['sms']['error']), ('test', ''))
        self.assertIn('kayıt daha', messages.body)

    def test_metin_olmayan_degerler_500_vermez(self):
        # sayı gelen alanlar metne çevrilir (JS'ten barkod/telefon sayı olarak gelebilir)
        items = [{'product_barcode': 8690000000311, 'defect_description': 12345, 'notes': 7}]
        res = self.controller('create_claim', data=self._data(customer_name=777, customer_mobile=5321234567),
                              items=items)
        self.assertNotIn('error', res, res)
        claim = self.Claim.browse(res['id'])
        self.assertEqual((claim.customer_name, claim.defect_description, claim.notes, claim.product_barcode),
                         ('777', '12345', '7', '8690000000311'))
        # liste/sözlük/None: istisna değil, dostça hata; kayıt yok
        before = self.Claim.search_count([])
        for data, items in (
                (self._data(customer_name=None), self._items()),
                (self._data(customer_name=['x']), [{}]),
                ('metin', self._items()),
                (self._data(), [None, 5]),
                (self._data(), [{'product_barcode': {'a': 1}, 'defect_description': 'Y'}]),
                (self._data(), [{'product_barcode': '8690000000311', 'defect_description': {'a': 1}}])):
            res = self.controller('create_claim', data=data, items=items)
            self.assertIn('error', res, (data, items))
        self.assertEqual(self.Claim.search_count([]), before)

    def test_urun_ve_musteri_zorunlu_alanlar(self):
        self.assertIn('error', self.controller('create_claim', data=self._data(), items=[]))
        self.assertIn('error', self.controller('create_claim', data=self._data(customer_name=' '),
                                               items=self._items()))
        too_many = [dict(self._items()[0]) for _i in range(21)]
        self.assertIn('error', self.controller('create_claim', data=self._data(), items=too_many))

    def test_tek_kayitli_eski_cagri_calisir(self):
        data = self._data(product_barcode='8690000000311', product_code='CKT-T1', quantity=1,
                          defect_description='Taban ayrıldı', customer_request='replace', notes='iç not')
        res = self.controller('create_claim', data=data, photos=['data:image/png;base64,' + PIXEL, 'foto-degil'])
        self.assertNotIn('error', res, res)
        claim = self.Claim.browse(res['id'])
        self.assertEqual((res['name'], res['vendor']), (claim.name, 'ABC Tekstil'))
        self.assertEqual((claim.defect_description, claim.customer_request, claim.notes),
                         ('Taban ayrıldı', 'replace', 'iç not'))
        self.assertEqual(len(claim.photo_ids), 1)
        self.assertEqual(res['claims'], [{'id': claim.id, 'name': claim.name, 'vendor': 'ABC Tekstil',
                                          'product_name': claim.product_name}])
        self.assertEqual(res['slip_url'], '/report/pdf/vendor_claim.report_vendor_claim_slip/%s' % claim.id)
        self.assertEqual(len(self.claim_sms(claim)), 1)
        self.assertEqual(res['sms']['state'], 'test')
        self.assertTrue(claim.sms_received_sent)
        self.assertIn(claim.name, self.claim_sms(claim).body)
        # eski çağrıda şikayet boşsa hata, kayıt yok
        before = self.Claim.search_count([])
        bad = self.controller('create_claim', data=dict(data, defect_description=''))
        self.assertIn('Ayıp / şikayet', bad['error'])
        self.assertEqual(self.Claim.search_count([]), before)

    def test_coklu_fis_html_tek_fis(self):
        _res, claims = self._create()
        html = self._html(claims)
        for claim in claims:
            self.assertIn(claim.name, html)
        self.assertEqual(html.count('Ayşe Çelik'), 1, 'müşteri bilgisi bir kez')
        self.assertEqual(html.count('class="article"'), 1)
        self.assertEqual(html.count('Müşteri İmza'), 1)
        self.assertEqual(html.count('Teslim Alan'), 1)
        self.assertEqual(html.count('/report/barcode/Code128/UGR-5005?'), 1)
        for text in ('Fermuar bozuk', 'Sap kopmuş', 'Dikiş açık', '8690000000328', 'Tamir', 'Değişim'):
            self.assertIn(text, html)

    def test_coklu_fis_faturasizda_ilk_takip_no_barkod(self):
        _res, claims = self._create(data=self._data(no_invoice=True))
        html = self._html(claims)
        self.assertEqual(html.count('/report/barcode/Code128/'), 1)
        self.assertIn('/report/barcode/Code128/%s?' % claims[0].name, html)

    def test_farkli_musteriler_ayri_fis(self):
        _r1, first = self._create()
        _r2, second = self._create(data=self._data(customer_name='Burak Aydın', customer_mobile='05559998877',
                                                   invoice_no='UGR-6006'), items=self._items()[:2])
        html = self._html(first | second)
        self.assertEqual(html.count('class="article"'), 2)
        self.assertEqual(html.count('Ayşe Çelik'), 1)
        self.assertEqual(html.count('Burak Aydın'), 1)
        # her takip no kendi müşterisinin fişinde
        first_slip = html.split('class="article"')[1]
        self.assertTrue(all(n in first_slip for n in first.mapped('name')))
        self.assertFalse(any(n in first_slip for n in second.mapped('name')))

    def test_ayni_fatura_farkli_gunlerde_ayri_fis(self):
        _r1, first = self._create()
        _r2, second = self._create(items=self._items()[:1])   # aynı müşteri, aynı fatura
        self.assertEqual(self._html(first | second).count('class="article"'), 1, 'aynı gün/kişi: tek fiş')
        # ikincisi başka günde açılmış gibi (create_date magic alan: SQL ile)
        self.env.cr.execute("UPDATE vendor_claim SET create_date = create_date - interval '3 days' WHERE id = %s",
                            [second.id])
        second.invalidate_recordset(['create_date'])
        html = self._html(first | second)
        self.assertEqual(html.count('class="article"'), 2)
        self.assertEqual(len((first | second)._slip_groups()), 2)

    def test_farkli_sorumlu_ayri_fis(self):
        _r1, first = self._create()
        _r2, second = self._create(items=self._items()[:1])
        other = self.env['res.users'].search([('id', '!=', first.user_id.id)], limit=1)
        second.user_id = other
        self.assertEqual(self._html(first | second).count('class="article"'), 2)

    def test_gun_kullanici_saat_diliminde_hesaplanir(self):
        """23:30 UTC ile 00:30 UTC, İstanbul'da (UTC+3) aynı gün: tek fiş; İstanbul gece yarısını aşan ayrı gün."""
        self.env.user.tz = 'Europe/Istanbul'
        _r1, first = self._create(items=self._items()[:1])
        _r2, second = self._create(items=self._items()[:1])
        stamp = "UPDATE vendor_claim SET create_date = %s WHERE id = %s"
        self.env.cr.execute(stamp, ['2026-10-05 20:30:00', first.id])    # İstanbul 23:30 (5 Ekim)
        self.env.cr.execute(stamp, ['2026-10-05 21:30:00', second.id])   # İstanbul 00:30 (6 Ekim)
        (first | second).invalidate_recordset(['create_date'])
        self.assertEqual(len((first | second)._slip_groups()), 2)
        self.env.cr.execute(stamp, ['2026-10-05 21:30:00', first.id])    # ikisi de 6 Ekim (İstanbul)
        first.invalidate_recordset(['create_date'])
        self.assertEqual(len((first | second)._slip_groups()), 1)

    def test_faturasiz_telefonsuz_ayni_istekteki_kayitlar_tek_fis(self):
        """Kimliksiz (faturasız + telefonsuz/kodsuz) kayıtlar aynı istekte açıldıysa tek fiş."""
        data = self._data(no_invoice=True, customer_mobile='', customer_code='')
        _res, multi = self._create(data=data)
        self.assertEqual(len(multi), 3)
        self.assertFalse(any(multi.mapped('customer_mobile') + multi.mapped('customer_code')
                             + multi.mapped('invoice_no')))
        self.assertEqual(len(set(multi.mapped('create_date'))), 1, 'aynı istek: aynı create_date')
        html = self._html(multi)
        self.assertEqual(html.count('class="article"'), 1)
        self.assertEqual(html.count('Ayşe Çelik'), 1)
        self.assertEqual(html.count('Müşteri İmza'), 1)
        self.assertEqual(html.count('/report/barcode/Code128/'), 1)
        for claim in multi:
            self.assertIn(claim.name, html)

    def test_faturasiz_telefonsuz_ayni_adli_farkli_istekler_ayri_fis(self):
        data = self._data(no_invoice=True, customer_mobile='', customer_code='')
        _r1, first = self._create(data=data, items=self._items()[:1])
        _r2, second = self._create(data=data, items=self._items()[:1])
        self.assertFalse(first.customer_mobile or first.customer_code or first.invoice_no)
        # testte iki çağrı tek işlemde: create_date aynı → farklı istek simülasyonu için SQL ile ayır
        self.env.cr.execute("UPDATE vendor_claim SET create_date = create_date + interval '5 seconds' WHERE id = %s",
                            [second.id])
        second.invalidate_recordset(['create_date'])
        self.assertEqual(self._html(first | second).count('class="article"'), 2)
        self.assertEqual(len((first | second)._slip_groups()), 2)
        # aynı zamanlı ama farklı kullanıcının kaydı da ayrışır
        self.env.cr.execute("UPDATE vendor_claim SET create_date = (SELECT create_date FROM vendor_claim WHERE id = %s)"
                            " WHERE id = %s", [first.id, second.id])
        second.invalidate_recordset(['create_date'])
        self.assertEqual(len((first | second)._slip_groups()), 1)
        self.env.cr.execute("UPDATE vendor_claim SET create_uid = %s WHERE id = %s", [self.user2.id, second.id])
        second.invalidate_recordset(['create_uid'])
        self.assertEqual(len((first | second)._slip_groups()), 2)

    def test_faturali_telefonsuz_tek_fis(self):
        # fatura kimlik sayılır
        _r, inv = self._create(data=self._data(customer_mobile='', customer_code='', invoice_no='UGR-7007'))
        self.assertEqual(self._html(inv).count('class="article"'), 1)

    def test_musteri_talebi_metin_olmayan_deger_500_vermez(self):
        for bad in (['repair'], {'a': 1}, 5, None, 'yok-boyle-secenek'):
            items = self._items()
            items[0]['customer_request'] = bad
            res, claims = self._create(items=items, data=self._data(invoice_no='UGR-%s' % id(bad)))
            self.assertEqual(claims[0].customer_request, 'inspect', bad)   # geçersiz → varsayılan, hata yok
        # eski tek kayıtlı çağrı (ortak data yolu) da aynı korumadan geçer
        res = self.controller('create_claim', data=self._data(
            product_barcode='8690000000311', defect_description='X', customer_request=['replace']))
        self.assertNotIn('error', res, res)
        self.assertEqual(self.Claim.browse(res['id']).customer_request, 'inspect')

    def test_coklu_fis_pdf_turkce(self):
        import io
        from odoo.tools.pdf import PdfFileReader
        _res, claims = self._create()
        pdf = self.env['ir.actions.report'].with_context(force_report_rendering=True)._render_qweb_pdf(
            self.SLIP, claims.ids)[0]
        text = '\n'.join(p.extract_text() for p in PdfFileReader(io.BytesIO(pdf)).pages)
        self.assertIn('Ürün İnceleme Teslim Fişi', text)
        self.assertIn('Ayşe Çelik', text)
        self.assertIn('Dikiş açık', text)
        for name in claims.mapped('name'):
            self.assertIn(name, text)
        self.assertNotIn('Ã', text)
