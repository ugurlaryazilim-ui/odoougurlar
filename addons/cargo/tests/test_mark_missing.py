# -*- coding: utf-8 -*-
"""K-28 / 05-inceleme Ö1: belirsiz gönderinin çıkışı - Kargo / Yönetici "kargo firmasında yok" (uncertain -> failed).

05-inceleme Y1 / K-29: işaret son gönderimden (sent_at) en az RECONCILE_MIN_AGE sonra verilir; testler saati
``freeze_time`` ile ilerletir (sent_at'ı geriye yazmak yaş kuralını değil yalnız alanı sınardı).
"""
from datetime import timedelta

from freezegun import freeze_time

from odoo import fields
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

    def later(self, minutes):
        """Saati ``minutes`` dk ileri alır (yaş kuralı: son gönderimden 15 dk)."""
        return freeze_time(fields.Datetime.now() + timedelta(minutes=minutes))

    def wizard(self, user, reason):
        return self.env['cargo.shipment.missing.wizard'].with_user(user).create(
            {'shipment_id': self.shipment.id, 'reason': reason})

    def test_yok_isaretle_yonetici_ve_yeni_gonderi(self):
        action = self.shipment.with_user(self.manager).action_mark_missing()
        self.assertEqual(action['res_model'], 'cargo.shipment.missing.wizard')
        self.assertEqual(action['context'], {'default_shipment_id': self.shipment.id, 'default_mode': 'missing'})
        with self.later(16):
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
        with self.later(16), self.assertRaises(UserError):
            self.shipment.with_user(self.manager)._cargo_mark_missing('   ')
        self.assertEqual(self.shipment.state, 'uncertain')

    def test_yok_isaretle_yalniz_belirsiz(self):
        self.provider.plan['send'] = lambda shipment: self.provider.ok_send(shipment=shipment)
        sent = self.sent()
        with self.later(16), self.assertRaises(UserError):
            sent.with_user(self.manager)._cargo_mark_missing('gerekce')
        self.assertEqual(sent.state, 'created')

    def test_yok_isaretle_genc_kayit_reddedilir(self):
        """Y1: gönderimden 15 dk geçmeden "yok" işareti verilmez (panelde henüz görünmeyebilir)."""
        Manager = self.shipment.with_user(self.manager)
        for minutes in (0, 14):
            with self.subTest(minutes=minutes), self.later(minutes):
                self.assert_user_error(lambda: Manager._cargo_mark_missing('erken'), r'en az 15 dk.*Uzlaştır')
        self.assertEqual(self.shipment.state, 'uncertain')
        with self.later(15):
            Manager._cargo_mark_missing('15 dk doldu')
        self.assertEqual(self.shipment.state, 'failed')
        self.assertEqual(self.provider.count(), self.calls_before, 'dış çağrı yapılmaz')

    def test_yok_isaretle_yas_son_gonderimden_olculur(self):
        """DERSLER 22: kayıt eski (ilk gönderim reddedildi) ama son gönderim gençse işaret reddedilir."""
        self.provider.plan['send'] = self.provider.err_send()
        shipment = self.mk()
        shipment.action_send()
        self.assertEqual(shipment.state, 'failed', 'ön koşul')
        self.provider.plan['send'] = self.provider.uncertain_send()
        with self.later(30):
            shipment.action_send()
        self.assertEqual(shipment.state, 'uncertain', 'ön koşul')
        Manager = shipment.with_user(self.manager)
        with self.later(32):
            self.assert_user_error(lambda: Manager._cargo_mark_missing('erken'), r'13 dk kaldı')
        with self.later(46):
            Manager._cargo_mark_missing('son gönderimden 16 dk')
        self.assertEqual(shipment.state, 'failed')
