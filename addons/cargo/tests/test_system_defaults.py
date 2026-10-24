# -*- coding: utf-8 -*-
"""K1 (05-inceleme, DERSLER 21): sistem alanları kişisel ``ir.default`` ile doldurulamaz.

PoC: kargo kullanıcısı kendine ``ir.default`` yazar (``label_pdf_id`` = yabancı ek, ``picking_id`` = başka transfer).
Gönderi hangi yoldan açılırsa açılsın (form, transfer düğmesi, create_and_send, kopya) bu değerler alınmaz; gönderim
sonrası yabancı ekin içeriği ve yabancı transferin takip numarası değişmez.
"""
from unittest.mock import patch

from odoo.tests import tagged

from .test_kabul_picking import PickingBase

_SYSTEM_DEFAULTS = (
    ('label_missing', True), ('tracking_ref', '1ZSAHTE'), ('error_message', 'sahte'), ('source_model', 'res.partner'),
    ('source_id', 7), ('error_code', 'X'), ('sent_at', '2026-01-01 00:00:00'),
)


@tagged('post_install', '-at_install', 'cargo')
class TestSystemFieldDefaults(PickingBase):

    def setUp(self):
        super().setUp()
        # NEDEN: canlı mod; test modunda takip no transfere hiç yazılmaz ve PoC'un transfer yolu görünmez (K-26).
        self.carrier.prod_environment = True
        Attachment = self.env['ir.attachment']
        self.victim = Attachment.create({'name': 'kurban.pdf', 'raw': b'KURBAN-PDF', 'mimetype': 'application/pdf'})
        self.victim_png = Attachment.create({'name': 'kurban.png', 'raw': b'KURBAN-PNG', 'mimetype': 'image/png'})
        self.other_picking = self.make_picking()
        Default = self.env['ir.default'].with_user(self.user)
        Default.set('cargo.shipment', 'label_pdf_id', self.victim.id, user_id=True)
        Default.set('cargo.shipment', 'label_png_ids', [self.victim_png.id], user_id=True)
        Default.set('cargo.shipment', 'picking_id', self.other_picking.id, user_id=True)
        for field, value in _SYSTEM_DEFAULTS:
            Default.set('cargo.shipment', field, value, user_id=True)
        # Ön koşul: kişisel varsayılanlar gerçekten kullanıcıya uygulanıyor (PoC geçerli).
        defaults = self.env['ir.default'].with_user(self.user)._get_model_defaults('cargo.shipment')
        self.assertEqual(defaults.get('label_pdf_id'), self.victim.id)
        self.assertEqual(defaults.get('picking_id'), self.other_picking.id)

    def assert_clean(self, shipment, picking=None):
        shipment = shipment.sudo()
        self.assertEqual(shipment.state, 'draft')
        self.assertNotEqual(shipment.label_pdf_id, self.victim)
        self.assertNotIn(self.victim_png, shipment.label_png_ids)
        self.assertEqual(shipment.picking_id, picking or self.env['stock.picking'])
        if not picking:
            self.assertFalse(shipment.source_model)
            self.assertFalse(shipment.source_id)
        self.assertFalse(shipment.tracking_ref)
        self.assertFalse(shipment.error_message)
        self.assertFalse(shipment.error_code)
        self.assertFalse(shipment.sent_at)
        self.assertFalse(shipment.label_missing)

    def assert_victims_untouched(self):
        self.victim.invalidate_recordset()
        self.assertEqual(self.victim.raw, b'KURBAN-PDF', 'yabancı ek sudo ile ezilmemeli')
        self.assertFalse(self.other_picking.carrier_tracking_ref, 'yabancı transfere takip yazılmamalı')
        self.assertFalse(self.other_picking.carrier_id)

    def test_ir_default_default_get_sistem_alani_vermez(self):
        Shipment = self.env['cargo.shipment'].with_user(self.user)
        names = list(Shipment._fields)
        for env_model in (Shipment, Shipment.sudo()):
            defaults = env_model.default_get(names)
            self.assertEqual(defaults.get('state'), 'draft')
            for field in ('label_pdf_id', 'label_png_ids', 'picking_id') + tuple(f for f, _v in _SYSTEM_DEFAULTS):
                self.assertNotIn(field, defaults)
        # bağlam yolu da aynı yerden kapanır (DERSLER 21)
        defaults = Shipment.with_context(default_state='created', default_label_pdf_id=self.victim.id).default_get(names)
        self.assertEqual(defaults.get('state'), 'draft')
        self.assertNotIn('label_pdf_id', defaults)
        # kullanıcı alanlarının ir.default'u çalışmaya devam eder
        self.env['ir.default'].with_user(self.user).set('cargo.shipment', 'description', 'Varsayilan esya', user_id=True)
        self.assertEqual(Shipment.default_get(['description'])['description'], 'Varsayilan esya')

    def test_ir_default_form_yolu(self):
        shipment = self.mk()
        self.assert_clean(shipment)
        shipment.with_user(self.user).action_send()
        self.assertEqual(shipment.state, 'created')
        self.assertTrue(shipment.label_pdf_id)
        self.assertEqual((shipment.label_pdf_id.res_model, shipment.label_pdf_id.res_id), ('cargo.shipment', shipment.id))
        self.assert_victims_untouched()
        shipment.with_user(self.user).action_print_label()
        self.assert_victims_untouched()

    def test_ir_default_transfer_yolu(self):
        picking = self.make_picking()
        self.open_action(picking)
        shipment = self.shipment_of(picking)
        self.assert_clean(shipment, picking=picking)
        self.assertEqual((shipment.source_model, shipment.source_id), ('stock.picking', picking.id))
        shipment.with_user(self.user).action_send()
        self.assertEqual(picking.carrier_tracking_ref, shipment.tracking_ref)
        self.assert_victims_untouched()

    def test_ir_default_api_yolu(self):
        shipment = self.env['cargo.shipment'].with_user(self.user).create_and_send(
            recipient_name='Ali Veli', phone='05321234567', street='Ataturk Mah. Gul Sk. No:5', state=self.st('06'),
            district='Cankaya', reference='K1-API')
        self.assertEqual(shipment.state, 'created')
        self.assertFalse(shipment.sudo().picking_id)
        self.assertFalse(shipment.sudo().source_model)
        self.assertNotEqual(shipment.sudo().label_pdf_id, self.victim)
        self.assert_victims_untouched()

    def test_ir_default_kopya(self):
        shipment = self.mk()
        copy = shipment.with_user(self.user).copy()
        self.assert_clean(copy)

    def test_bilinmeyen_varsayilan_kaynagi_create_sonrasi_sifirlanir(self):
        """İkinci savunma (tasarım §4.5): default_get dışında bir yoldan gelen sistem değeri create sonunda silinir."""
        Shipment = type(self.env['cargo.shipment'])
        leaked = {'label_pdf_id': self.victim.id, 'picking_id': self.other_picking.id, 'label_missing': True,
                  'label_png_ids': [self.victim_png.id], 'tracking_ref': '1ZSIZDI', 'state': 'draft'}
        original = Shipment.default_get

        def default_get(this, fields):
            values = original(this, fields)
            # NEDEN: sudo'suz create'te m2m bağlantısı Odoo'nun ek okuma denetimine takılır (zaten AccessError);
            # sızıntı yalnız sudo yolunda (create_and_send) anlamlıdır.
            values.update({key: value for key, value in leaked.items()
                           if key in fields and (this.env.su or key != 'label_png_ids')})
            return values
        with patch.object(Shipment, 'default_get', default_get):
            shipment = self.mk()
            api_shipment = self.env['cargo.shipment'].with_user(self.user).create_and_send(
                recipient_name='Ali Veli', phone='05321234567', street='Ataturk Mah. Gul Sk. No:5',
                state=self.st('06'), district='Cankaya', reference='K1-SIZINTI')
        self.assert_clean(shipment)
        self.assertNotEqual(api_shipment.sudo().label_pdf_id, self.victim)
        self.assertNotIn(self.victim_png, api_shipment.sudo().label_png_ids)
        self.assertFalse(api_shipment.sudo().picking_id)
        self.assert_victims_untouched()

    def test_etiket_pdf_yalniz_kendi_ekini_yeniden_yazar(self):
        """Ek savunma: label_pdf_id bir şekilde yabancı eke işaret ederse PDF yeni eke yazılır."""
        shipment = self.mk()
        shipment.with_user(self.user).action_send()
        shipment.sudo().label_pdf_id = self.victim
        pdf = shipment.with_user(self.user)._cargo_build_label_pdf()
        self.assertNotEqual(pdf, self.victim)
        self.assertEqual((pdf.res_model, pdf.res_id), ('cargo.shipment', shipment.id))
        self.assertEqual(shipment.label_pdf_id, pdf)
        self.assert_victims_untouched()
