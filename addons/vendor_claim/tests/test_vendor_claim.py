from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


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
