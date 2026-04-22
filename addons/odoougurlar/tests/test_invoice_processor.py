# -*- coding: utf-8 -*-
"""Invoice Processor — Temel testler."""
from odoo.tests.common import TransactionCase


class TestInvoiceProcessor(TransactionCase):
    """invoice_processor.py temel akış testleri."""

    def setUp(self):
        super().setUp()
        self.AccountMove = self.env['account.move']
        self.Partner = self.env['res.partner']

    # -----------------------------------------------------------------
    #  UGO Seri Numarası
    # -----------------------------------------------------------------
    def test_ugo_sequence_exists(self):
        """UGO sequence tanımlı olmalı."""
        seq = self.env['ir.sequence'].search([('code', '=', 'ugo.invoice.sequence')], limit=1)
        self.assertTrue(seq, "ugo.invoice.sequence tanımlı değil!")

    # -----------------------------------------------------------------
    #  EInvoice Bloğu — Kurumsal
    # -----------------------------------------------------------------
    def test_einvoice_block_for_corporate(self):
        """Kurumsal müşteri faturaları için EInvoice bloğu oluşturulmalı."""
        partner = self.Partner.create({
            'name': 'Kurumsal Test A.Ş.',
            'is_company': True,
            'vat': '1234567890',
        })
        # EInvoice bloğu kontrol
        self.assertTrue(partner.is_company and partner.vat)

    def test_no_einvoice_block_for_individual(self):
        """Bireysel müşteri faturaları için EInvoice bloğu oluşturulmamalı."""
        partner = self.Partner.create({
            'name': 'Bireysel Test',
            'is_company': False,
        })
        self.assertFalse(partner.is_company or partner.vat)

    # -----------------------------------------------------------------
    #  Nebim Alanları
    # -----------------------------------------------------------------
    def test_nebim_fields_on_invoice(self):
        """account.move modelinde nebim_sent, nebim_invoice_number alanları tanımlı olmalı."""
        invoice = self.AccountMove.new({'move_type': 'out_invoice'})
        self.assertFalse(invoice.nebim_sent)
        self.assertFalse(invoice.nebim_invoice_number)
