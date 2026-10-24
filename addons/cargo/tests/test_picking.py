# -*- coding: utf-8 -*-
"""stock.picking birim testleri (G6): pazaryeri tespiti (alan yokluğuna dayanıklılık), takip yazım kapısı, düğme
görünümü. Kabul senaryoları test_kabul_picking'dedir; pazaryeri modülleri bc_test'te kurulu olmadığından burada
kayıt listesi, sale.order'da var olan ``client_order_ref`` alanıyla yamalanır.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from .test_kabul_picking import PickingBase

_REGISTRY = 'odoo.addons.cargo.models.stock_picking._CARGO_MARKETPLACES'


@tagged('post_install', '-at_install', 'cargo')
class TestPickingMarketplace(PickingBase):

    def test_kayitli_alan_dolu_ise_pazaryeri_adi(self):
        picking = self.make_picking(client_order_ref='PZ-1')
        with patch(_REGISTRY, (('client_order_ref', 'Deneme Pazar'),)):
            self.assertEqual(picking.sudo().cargo_marketplace_name, 'Deneme Pazar')

    def test_alan_bos_veya_modul_kurulu_degilse_pazaryeri_degil(self):
        picking = self.make_picking()
        with patch(_REGISTRY, (('client_order_ref', 'Deneme Pazar'), ('olmayan_alan_id', 'Yok'))):
            self.assertFalse(picking.sudo().cargo_marketplace_name, 'alan boş')
        picking = self.make_picking(client_order_ref='PZ-2')
        with patch(_REGISTRY, (('olmayan_alan_id', 'Yok'),)):
            self.assertFalse(picking.sudo().cargo_marketplace_name, 'alan yok: hata vermeden atlanır')

    def test_satis_siparisiz_transfer_pazaryeri_degil(self):
        picking_type = self.env.ref('stock.picking_type_out')
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id, 'partner_id': self.cust.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id})
        self.assertFalse(picking.sudo().sale_id)
        self.assertFalse(picking.sudo().cargo_marketplace_name)

    def test_pazaryeri_transferinde_dugme_taslak_acar_takip_yazmaz(self):
        self.carrier.prod_environment = True
        picking = self.make_picking(client_order_ref='PZ-3')
        with patch(_REGISTRY, (('client_order_ref', 'Deneme Pazar'),)):
            self.open_action(picking)
            shipment = self.shipment_of(picking)
            self.assertEqual(shipment.state, 'draft')
            shipment.with_user(self.user).action_send()
            self.assertEqual(shipment.state, 'created')
            self.assertFalse(shipment.sudo()._cargo_picking_tracking_allowed())
        self.assertFalse(picking.carrier_tracking_ref)
        self.assertFalse(picking.carrier_id)

    def test_pazaryeri_olmayanda_takip_izinli_test_modunda_degil(self):
        picking = self.make_picking()
        shipment = self.sent_for(picking, prod=True)
        self.assertTrue(shipment._cargo_picking_tracking_allowed())
        shipment.sudo().test_mode = True
        self.assertFalse(shipment._cargo_picking_tracking_allowed())

    def sent_for(self, picking, prod):
        self.carrier.prod_environment = prod
        self.open_action(picking)
        shipment = self.shipment_of(picking)
        shipment.with_user(self.user).action_send()
        return shipment


@tagged('post_install', '-at_install', 'cargo')
class TestPickingOpen(PickingBase):

    def test_gonderi_sistem_alanlariyla_baglanir(self):
        picking = self.make_picking()
        self.open_action(picking)
        shipment = self.shipment_of(picking)
        self.assertEqual((shipment.source_model, shipment.source_id), ('stock.picking', picking.id))
        self.assertEqual(shipment.company_id, picking.company_id)
        self.assertEqual(shipment.partner_id, self.cust)
        self.assertEqual(shipment.create_uid, self.user, 'sudo ile açılsa da oluşturan gerçek kullanıcı')

    def test_gonderi_kopyalanan_transfere_gecmez(self):
        picking = self.make_picking()
        self.open_action(picking)
        self.assertFalse(picking.sudo().copy().cargo_shipment_ids)

    def test_gonderilmis_gonderi_varken_yeni_taslak_acilmaz(self):
        self.carrier.prod_environment = True
        picking = self.make_picking()
        self.open_action(picking)
        shipment = self.shipment_of(picking)
        shipment.with_user(self.user).action_send()
        action = self.open_action(picking)
        self.assertEqual(action['res_id'], shipment.id)
        self.assertEqual(len(picking.sudo().cargo_shipment_ids), 1)

    def test_ilk_yetkisiz_denemede_dis_cagri_yok(self):
        picking = self.make_picking()
        with self.assertRaises(UserError):
            picking.with_user(self.plain).action_cargo_shipment_open()
        self.no_provider_calls()

    def test_form_dugmeleri_yalniz_pazaryerinde_onayli(self):
        arch = self.env['stock.picking'].get_view(view_type='form')['arch']
        buttons = [part for part in arch.split('<button') if 'action_cargo_shipment_open' in part.split('>')[0]]
        self.assertEqual(len(buttons), 2)
        confirmed = [part for part in buttons if 'confirm=' in part.split('>')[0]]
        self.assertEqual(len(confirmed), 1)
        self.assertIn('not cargo_marketplace_name', confirmed[0].split('>')[0])
