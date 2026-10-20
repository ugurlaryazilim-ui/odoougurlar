"""Toplu SMS metin alanındaki yer tutucu çipleri: görünümde verilen liste yalnız sunucunun çözebildiği adları içerir."""
import ast
import os

from lxml import etree
from odoo.tests.common import tagged
from odoo.tools import file_path

from .common import SmsTestCase
from .test_campaign import CampaignMixin

SAMPLE_NAME = 'Ayşe Yılmaz'


@tagged('post_install', '-at_install')
class TestPlaceholderWidget(CampaignMixin, SmsTestCase):

    def _body_field(self):
        arch = self.Campaign.get_view(view_type='form')['arch']
        fields = etree.fromstring(arch).xpath("//field[@name='body']")
        self.assertEqual(len(fields), 1)
        return fields[0]

    def test_govde_alani_widget_ve_secenekleri(self):
        node = self._body_field()
        self.assertEqual(node.get('widget'), 'sms_placeholder_text')
        options = ast.literal_eval(node.get('options'))
        self.assertTrue(options['placeholders'])
        for item in options['placeholders']:
            self.assertTrue(item['label'])
            self.assertRegex(item['value'], r'^\w+$', 'süslü parantezsiz, yalnız ad olmalı')

    def test_cipler_yalniz_sunucunun_cozdugu_yer_tutucular(self):
        """Çip olarak sunulan her ad önizlemede/gönderimde gerçekten çözülür (desteklenmeyen çip yok)."""
        lst = self.make_list()
        placeholders = ast.literal_eval(self._body_field().get('options'))['placeholders']
        for item in placeholders:
            with self.subTest(yer_tutucu=item['value']):
                camp = self.make_campaign(lst, state='draft', body='Sayın {%s}, merhaba' % item['value'])
                self.assertTrue(camp.personalized)
                self.assertIn(SAMPLE_NAME, camp.final_body, 'yer tutucu önizlemede çözülmedi')
                self.assertNotIn('{', camp.final_body)

    def test_varliklar_manifestte_ve_dosyalar_var(self):
        with open(file_path('sms_system/__manifest__.py'), encoding='utf-8') as fh:
            files = ast.literal_eval(fh.read())['assets']['web.assets_backend']
        self.assertIn('sms_system/static/src/js/sms_placeholder_text.js', files)
        for path in files:
            self.assertTrue(os.path.exists(file_path(path)), path)
