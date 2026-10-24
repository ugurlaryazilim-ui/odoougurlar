# -*- coding: utf-8 -*-
"""K-29 / 05-inceleme Y3: iptal isteği belirsiz kalan ``created`` gönderinin çıkışı.

Kargo / Yönetici, gerekçe yazarak "kargo firmasında iptal edildi" işaretler (created -> cancelled). Eylem yalnız son
iptal isteği belirsiz kalmışsa (``cancel_uncertain_at``) ve o istekten en az 15 dk sonra çalışır; dış çağrı yapmaz,
transferdeki takip no normal iptaldeki gibi temizlenir.
"""
from datetime import timedelta

from freezegun import freeze_time

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .test_kabul_picking import PickingBase

_UNCERTAIN_CANCEL = {'status': 'uncertain', 'error_code': '', 'error_message': 'zaman asimi'}
_ALREADY_CANCELLED = {'status': 'error', 'error_code': '7', 'error_message': 'Gonderi zaten iptal'}


@tagged('post_install', '-at_install', 'cargo')
class TestMarkCancelled(PickingBase):

    def setUp(self):
        super().setUp()
        # NEDEN: canlı mod; test modunda takip no transfere hiç yazılmaz, temizlik yolu görünmez (K-26).
        self.carrier.prod_environment = True
        self.picking = self.make_picking()
        self.open_action(self.picking)
        self.shipment = self.shipment_of(self.picking)
        self.shipment.with_user(self.user).action_send()
        self.assertEqual(self.shipment.state, 'created', 'ön koşul')
        self.assertEqual(self.picking.carrier_tracking_ref, self.shipment.tracking_ref, 'ön koşul')

    def later(self, minutes):
        return freeze_time(fields.Datetime.now() + timedelta(minutes=minutes))

    def cancel_uncertain(self):
        self.provider.plan['cancel'] = _UNCERTAIN_CANCEL
        result = self.shipment.with_user(self.user).action_cancel()
        self.assertEqual(self.shipment.state, 'created', 'belirsiz iptal durumu değiştirmez')
        self.assertTrue(self.shipment.cancel_uncertain_at, 'belirsiz iptal işareti yazılır')
        return result

    def wizard(self, user, reason):
        action = self.shipment.with_user(user).action_mark_cancelled()
        return self.env['cargo.shipment.missing.wizard'].with_user(user).with_context(action['context']).create(
            {'reason': reason})

    def test_belirsiz_iptal_isaret_ve_uyari(self):
        result = self.cancel_uncertain()
        self.assertIn('Kargo firmasında iptal edildi', result['params']['message'])
        self.assertFalse(self.shipment.cancelled_at)
        # sonraki "zaten iptal" hatası işareti silmez (hata iptalin olmadığını kanıtlamaz)
        self.provider.plan['cancel'] = _ALREADY_CANCELLED
        self.shipment.with_user(self.user).action_cancel()
        self.assertEqual(self.shipment.state, 'created')
        self.assertTrue(self.shipment.cancel_uncertain_at)

    def test_iptal_edildi_yonetici_ve_transfer_temizlenir(self):
        self.cancel_uncertain()
        self.provider.plan['cancel'] = _ALREADY_CANCELLED
        self.shipment.with_user(self.user).action_cancel()
        calls = self.provider.count()
        with self.later(16):
            wizard = self.wizard(self.manager, 'Panelde gonderi iptal gorunuyor')
            self.assertEqual(wizard.mode, 'cancelled')
            wizard.action_confirm()
        self.assertEqual(self.shipment.state, 'cancelled')
        self.assertTrue(self.shipment.cancelled_at)
        self.assertFalse(self.picking.carrier_tracking_ref, 'normal iptaldeki gibi takip no silinir')
        chatter = self.chatter(self.shipment)
        self.assertIn('Panelde gonderi iptal gorunuyor', chatter)
        self.assertIn(self.manager.name, chatter)
        self.assertIn(self.shipment.tracking_ref, chatter)
        self.assertEqual(self.provider.count(), calls, 'dış çağrı yapılmaz')
        # transfer artık kilitli değil: yeni gönderi açılır
        self.open_action(self.picking)
        fresh = self.shipment_of(self.picking)
        self.assertNotEqual(fresh, self.shipment)
        self.assertEqual(fresh.state, 'draft')

    def test_iptal_edildi_baskasinin_takibi_silinmez(self):
        self.cancel_uncertain()
        self.picking.carrier_tracking_ref = 'BASKA-TAKIP-1'
        with self.later(16):
            self.shipment.with_user(self.manager)._cargo_mark_cancelled('panelde iptal')
        self.assertEqual(self.shipment.state, 'cancelled')
        self.assertEqual(self.picking.carrier_tracking_ref, 'BASKA-TAKIP-1')

    def test_iptal_edildi_genc_istek_reddedilir(self):
        """Yaş son BELİRSİZ iptal isteğinden ölçülür; gönderimin yaşı yetmez."""
        with self.later(60):
            self.cancel_uncertain()
        Manager = self.shipment.with_user(self.manager)
        with self.later(70):
            self.assert_user_error(lambda: Manager._cargo_mark_cancelled('erken'), r'en az 15 dk.*5 dk kaldı')
        self.assertEqual(self.shipment.state, 'created')
        with self.later(75):
            Manager._cargo_mark_cancelled('15 dk doldu')
        self.assertEqual(self.shipment.state, 'cancelled')

    def test_iptal_edildi_yalniz_yonetici(self):
        self.cancel_uncertain()
        with self.later(16):
            with self.assertRaises(AccessError):
                self.shipment.with_user(self.user)._cargo_mark_cancelled('yetkisiz')
            with self.assertRaises(AccessError):
                self.wizard(self.user, 'yetkisiz')
        self.assertEqual(self.shipment.state, 'created')

    def test_iptal_edildi_gerekce_zorunlu(self):
        self.cancel_uncertain()
        with self.later(16), self.assertRaises(UserError):
            self.shipment.with_user(self.manager)._cargo_mark_cancelled('  ')
        self.assertEqual(self.shipment.state, 'created')

    def test_iptal_edildi_yalniz_belirsiz_iptal(self):
        Manager = self.shipment.with_user(self.manager)
        with self.later(16):
            # iptal hiç denenmemiş ya da yalnız kesin hata almış created gönderi
            self.assert_user_error(lambda: Manager._cargo_mark_cancelled('gerekce'), 'iptal isteğinin sonucu belirsiz')
            self.provider.plan['cancel'] = _ALREADY_CANCELLED
            self.shipment.with_user(self.user).action_cancel()
            self.assert_user_error(lambda: Manager._cargo_mark_cancelled('gerekce'), 'iptal isteğinin sonucu belirsiz')
        self.assertEqual(self.shipment.state, 'created')
        # belirsiz GÖNDERİM (uncertain) bu eylemle kapanmaz (K-28'in işi)
        self.provider.plan['send'] = self.provider.uncertain_send()
        uncertain = self.mk()
        uncertain.action_send()
        with self.later(16):
            self.assert_user_error(lambda: uncertain.with_user(self.manager)._cargo_mark_cancelled('gerekce'))
        self.assertEqual(uncertain.state, 'uncertain')

    def test_form_dugmesi_yalniz_belirsiz_iptalde(self):
        arch = self.env['cargo.shipment'].with_user(self.manager).get_view(view_type='form')['arch']
        self.assertIn('name="action_mark_cancelled"', arch)
        self.assertIn("invisible=\"state != 'created' or not cancel_uncertain_at\"", arch)
