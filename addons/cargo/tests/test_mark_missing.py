# -*- coding: utf-8 -*-
"""K-28 / 05-inceleme Ö1: belirsiz gönderinin çıkışı - Kargo / Yönetici "kargo firmasında yok" (uncertain -> failed)."""
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .test_kabul_picking import PickingBase


@tagged('post_install', '-at_install', 'cargo')
class TestMarkMissing(PickingBase):

    def setUp(self):
        super().setUp()
        self.picking = self.make_picking()
        self.open_action(self.picking)
        self.shipment = self.shipment_of(self.picking)
        self.provider.plan['send'] = self.provider.uncertain_send()
        self.shipment.with_user(self.user).action_send()
        self.assertEqual(self.shipment.state, 'uncertain', 'ön koşul')
        self.calls_before = self.provider.count()

    def wizard(self, user, reason):
        return self.env['cargo.shipment.missing.wizard'].with_user(user).create(
            {'shipment_id': self.shipment.id, 'reason': reason})

    def test_yok_isaretle_yonetici_ve_yeni_gonderi(self):
        action = self.shipment.with_user(self.manager).action_mark_missing()
        self.assertEqual(action['res_model'], 'cargo.shipment.missing.wizard')
        self.assertEqual(action['context'], {'default_shipment_id': self.shipment.id})
        self.wizard(self.manager, 'Panelde referansla arandi, kayit yok').action_confirm()
        self.assertEqual(self.shipment.state, 'failed')
        self.assertIn('Panelde referansla arandi', self.shipment.error_message)
        chatter = self.chatter(self.shipment)
        self.assertIn('Panelde referansla arandi, kayit yok', chatter)
        self.assertIn(self.manager.name, chatter)
        self.assertIn(self.carrier.name, chatter)
        self.assertEqual(self.provider.count(), self.calls_before, 'dış çağrı yapılmaz')
        # transfer artık kilitli değil: yeni gönderi açılır
        self.open_action(self.picking)
        fresh = self.shipment_of(self.picking)
        self.assertNotEqual(fresh, self.shipment)
        self.assertEqual(fresh.state, 'draft')

    def test_yok_isaretle_yalniz_yonetici(self):
        with self.assertRaises(AccessError):
            self.shipment.with_user(self.user)._cargo_mark_missing('yetkisiz')
        with self.assertRaises(AccessError):
            self.wizard(self.user, 'yetkisiz')
        self.assertEqual(self.shipment.state, 'uncertain')

    def test_yok_isaretle_gerekce_zorunlu(self):
        with self.assertRaises(UserError):
            self.shipment.with_user(self.manager)._cargo_mark_missing('   ')
        self.assertEqual(self.shipment.state, 'uncertain')

    def test_yok_isaretle_yalniz_belirsiz(self):
        self.provider.plan['send'] = lambda shipment: self.provider.ok_send(shipment=shipment)
        sent = self.sent()
        with self.assertRaises(UserError):
            sent.with_user(self.manager)._cargo_mark_missing('gerekce')
        self.assertEqual(sent.state, 'created')
