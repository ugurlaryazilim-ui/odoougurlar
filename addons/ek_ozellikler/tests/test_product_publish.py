import base64

from odoo.tests import TransactionCase, tagged

# 1x1 PNG
_PNG = base64.b64encode(
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
    b'\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82'
)


@tagged('post_install', '-at_install')
class TestPublishEcommerce(TransactionCase):
    """action_publish_ecommerce: product_template'te image_1920 kolonu yok; görselsiz ürün SQL hatası vermemeli."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.no_img = cls.env['product.template'].create({'name': 'Yayın Görselsiz'})
        cls.with_img = cls.env['product.template'].create({'name': 'Yayın Görselli', 'image_1920': _PNG})
        cls.with_img.flush_recordset()

    def test_imageless_product_does_not_raise_and_is_skipped(self):
        res = self.no_img.action_publish_ecommerce()
        self.assertIn('görsel bulunamadı', res['params']['message'])
        self.assertFalse(self.no_img.is_published)

    def test_mixed_selection_publishes_only_imaged(self):
        res = (self.no_img | self.with_img).action_publish_ecommerce()
        self.assertTrue(self.with_img.is_published)
        self.assertFalse(self.no_img.is_published)
        self.assertIn('1 görselsiz atlandı', res['params']['message'])
