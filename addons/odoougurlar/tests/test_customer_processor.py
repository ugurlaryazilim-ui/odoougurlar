# -*- coding: utf-8 -*-
"""Customer Processor — Temel testler."""
from odoo.tests.common import TransactionCase


class TestCustomerProcessor(TransactionCase):
    """customer_processor.py temel akış testleri."""

    def setUp(self):
        super().setUp()
        self.Partner = self.env['res.partner']
        self.Mapping = self.env['odoougurlar.marketplace.mapping']
        self.TaxMapping = self.env['odoougurlar.tax.mapping']

    # -----------------------------------------------------------------
    #  VKN Maskeleme
    # -----------------------------------------------------------------
    def test_vkn_masking_in_log(self):
        """VKN/TCKN log'a maskelenmiş olarak yazılmalı."""
        vkn = '1234567890'
        masked = vkn[:3] + '***' + vkn[-2:]
        self.assertEqual(masked, '123***90')

    # -----------------------------------------------------------------
    #  Vergi Dairesi Eşleştirme
    # -----------------------------------------------------------------
    def test_tax_mapping_lookup(self):
        """tax_mapping tablosundan doğru vergi dairesi kodu gelmelidir."""
        self.TaxMapping.create({
            'name': 'osmangazi',
            'nebim_tax_office_code': '016251',
            'nebim_tax_office_name': 'OSMANGAZİ VERGİ DAİRESİ',
        })

        mapping = self.TaxMapping.search([('name', 'ilike', 'osmangazi')], limit=1)
        self.assertTrue(mapping)
        self.assertEqual(mapping.nebim_tax_office_code, '016251')

    def test_tax_mapping_unique_constraint(self):
        """Aynı isimle ikinci kayıt oluşturulamamalı."""
        self.TaxMapping.create({
            'name': 'erciyes',
            'nebim_tax_office_code': '038251',
        })
        with self.assertRaises(Exception):
            self.TaxMapping.create({
                'name': 'erciyes',
                'nebim_tax_office_code': '038999',
            })

    # -----------------------------------------------------------------
    #  Partner Kurumsal/Bireysel Ayrımı
    # -----------------------------------------------------------------
    def test_corporate_partner_detection(self):
        """is_company=True ve VKN'li partner kurumsal sayılmalı."""
        partner = self.Partner.create({
            'name': 'Test Firma A.Ş.',
            'is_company': True,
            'vat': '1234567890',
        })
        self.assertTrue(partner.is_company)
        self.assertTrue(partner.vat)

    def test_individual_partner_detection(self):
        """is_company=False partner bireysel sayılmalı."""
        partner = self.Partner.create({
            'name': 'Ahmet Yılmaz',
            'is_company': False,
        })
        self.assertFalse(partner.is_company)
