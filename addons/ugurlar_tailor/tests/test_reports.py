"""Terzi etiketi/fişi gerçek PDF'te Türkçe karakterleri bozmadan basar (div.article yoksa wkhtmltopdf Latin-1 okur)."""
import io

from odoo.tests.common import TransactionCase, tagged
from odoo.tools.pdf import PdfFileReader


def pdf_text(pdf):
    return '\n'.join(page.extract_text() for page in PdfFileReader(io.BytesIO(pdf)).pages)


@tagged('post_install', '-at_install')
class TestTailorReports(TransactionCase):

    def test_etiket_ve_fis_turkce_karakter(self):
        tailor = self.env['ugurlar.tailor'].create({'name': 'Şükrü Terzi'})
        order = self.env['ugurlar.tailor.order'].create({
            'product_barcode': '8690000000001', 'customer_name': 'Ayşe Yılmaz', 'tailor_id': tailor.id})
        Report = self.env['ir.actions.report'].with_context(force_report_rendering=True)
        for xmlid in ('ugurlar_tailor.action_report_tailor_label', 'ugurlar_tailor.action_report_tailor_slip'):
            text = pdf_text(Report._render_qweb_pdf(xmlid, order.ids)[0])
            self.assertIn('Şükrü Terzi' if xmlid.endswith('slip') else 'Ayşe Yılmaz', text, xmlid)
            self.assertNotIn('Ã', text, '%s: UTF-8 metin Latin-1 okunmuş' % xmlid)
