# -*- coding: utf-8 -*-
"""Gönder / uzlaştır / iptal akışı birim testleri (G4; sahte sağlayıcı + sahte commit, kabul tabanı üzerinden).

Kabul testlerinin (test_kabul_akis) kapsamadığı kardeş yollar: durum matrisi, transfer takip yazımı/temizliği,
kısmi etiket, yan iş hatası, takılı sending (S1), test_mode anı, sır sızıntısı, şirket ayrımı.
"""
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .kabul_taban import CargoKabulCase, make_label_png

_LOGGER = 'odoo.addons.cargo.models.cargo_shipment'
_ALL_STATES = ('draft', 'sending', 'uncertain', 'created', 'in_transit', 'out_for_delivery', 'delivered',
               'returned', 'exception', 'cancelled', 'failed')


@tagged('post_install', '-at_install', 'cargo')
class TestShipmentFlow(CargoKabulCase):

    def picking(self):
        picking_type = self.env.ref('stock.picking_type_out')
        return self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
        })

    def with_state(self, state, **vals):
        shipment = self.mk()
        shipment.sudo().write(dict(vals, state=state))
        return shipment

    # -- arayüz
    def test_private_send_ayni_yol(self):
        """G7 create_and_send aynı _cargo_send yolunu kullanır: sonuç sözlüğü + created + tek çağrı."""
        shipment = self.mk()
        result = shipment._cargo_send()
        self.assertEqual(result['status'], 'ok')
        self.assertIn(shipment.tracking_ref, result['message'])
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(self.provider.count('send'), 1)

    def test_bildirim_bicimi(self):
        cases = ((None, 'success', False), (self.provider.err_send(), 'danger', True),
                 (self.provider.uncertain_send(), 'warning', True))
        for plan, kind, sticky in cases:
            with self.subTest(kind=kind):
                if plan:
                    self.provider.plan['send'] = plan
                action = self.mk().action_send()
                self.assertEqual((action['type'], action['tag']), ('ir.actions.client', 'display_notification'))
                self.assertEqual(action['params']['type'], kind)
                self.assertEqual(action['params']['sticky'], sticky)
                self.assertEqual(action['params']['next']['tag'], 'soft_reload')

    def test_sudo_cagrisi_da_yetki_ister(self):
        shipment = self.mk()
        with self.assertRaises(AccessError):
            shipment.with_user(self.plain).sudo().action_send()
        self.no_provider_calls()

    # -- durum matrisi
    def test_durum_matrisi_send(self):
        expected = {'sending': r'zaten işleniyor', 'uncertain': r'Uzlaştır', 'cancelled': r'iptal edilmiş'}
        for state in _ALL_STATES:
            if state in ('draft', 'failed'):
                continue
            with self.subTest(state=state):
                shipment = self.with_state(state)
                self.assert_user_error(shipment.action_send, expected.get(state, r'zaten oluşturuldu'))
                self.assertEqual(shipment.state, state)
        self.no_provider_calls()

    def test_durum_matrisi_cancel(self):
        for state in _ALL_STATES:
            if state == 'created':
                continue
            with self.subTest(state=state):
                shipment = self.with_state(state)
                self.assert_user_error(shipment.action_cancel)
                self.assertEqual(shipment.state, state)
        self.no_provider_calls()

    def test_durum_matrisi_reconcile(self):
        for state in _ALL_STATES:
            if state in ('uncertain', 'sending'):
                continue
            with self.subTest(state=state):
                shipment = self.with_state(state, sent_at=self.minutes_ago(30))
                self.assert_user_error(shipment.action_reconcile, r'belirsiz')
        young = self.with_state('sending', sent_at=self.minutes_ago(2))
        self.assert_user_error(young.action_reconcile, r'zaten işleniyor')
        self.assertEqual(young.state, 'sending')
        self.no_provider_calls()

    # -- S1: takılı sending
    def test_takili_sending_uzlastirilir(self):
        cases = ((self.provider.found('1ZTAKILI0001'), 'created'), (self.provider.not_found(), 'failed'),
                 (self.provider.find_error(), 'uncertain'))
        for plan, final in cases:
            with self.subTest(final=final):
                self.provider.plan['find'] = plan
                shipment = self.with_state('sending', sent_at=self.minutes_ago(20))
                self.try_call(shipment.action_reconcile)
                self.assertEqual(shipment.state, final)
        self.assertEqual(self.provider.count('send'), 0, 'uzlaştırma yeniden gönderim yapmaz')

    def test_bulunamadi_genc_dakika_bildirir(self):
        self.provider.plan['find'] = self.provider.not_found()
        shipment = self.with_state('uncertain', sent_at=self.minutes_ago(5))
        action = shipment.action_reconcile()
        self.assertEqual(shipment.state, 'uncertain')
        self.assertRegex(action['params']['message'], r'1[01] dk sonra')

    # -- sonuç sözlüğü savunması
    def test_ok_takipsiz_belirsiz(self):
        self.provider.plan['send'] = lambda s: dict(self.provider.ok_send(shipment=s), tracking_ref='  ')
        shipment = self.mk()
        shipment.action_send()
        self.assertEqual(shipment.state, 'uncertain')
        self.assertFalse(self.attachments(shipment, 'image/png'))

    def test_gecersiz_yanit_belirsiz(self):
        for plan in ({'status': 'tuhaf'}, lambda s: None):
            with self.subTest(plan=plan):
                self.provider.plan['send'] = plan
                shipment = self.mk()
                shipment.action_send()
                self.assertEqual(shipment.state, 'uncertain')

    def test_hata_mesaji_kesilir(self):
        self.provider.plan['send'] = self.provider.err_send('1', 'x' * 1200)
        shipment = self.mk()
        shipment.action_send()
        self.assertEqual(shipment.state, 'failed')
        self.assertEqual(len(shipment.error_message), 500)

    def test_failed_yeniden_gonderimde_hata_alanlari_temizlenir(self):
        self.provider.plan['send'] = [self.provider.err_send('9', 'ilk'), self.provider.uncertain_send('ikinci')]
        shipment = self.mk()
        shipment.action_send()
        shipment.action_send()
        self.assertEqual(shipment.state, 'uncertain')
        self.assertFalse(shipment.error_code)
        self.assertEqual(shipment.error_message, 'ikinci')

    # -- etiket / yan işler
    def test_bozuk_png_label_missing(self):
        self.provider.plan['send'] = lambda s: dict(self.provider.ok_send(shipment=s),
                                                    labels=[make_label_png(0), b'bozuk', 'metin'])
        shipment = self.mk(package_count=2)
        shipment.action_send()
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(self.attachments(shipment, 'image/png').mapped('name'), ['%s-1.png' % shipment.name])
        self.assertFalse(shipment.label_missing, 'en az bir etiket varsa label_missing yazılmaz')
        self.assertRegex(self.chatter(shipment), r'Etiket eksik: 1/2')

        self.provider.plan['send'] = lambda s: dict(self.provider.ok_send(shipment=s), labels=[b'bozuk'])
        other = self.mk()
        other.action_send()
        self.assertEqual(other.state, 'created')
        self.assertTrue(other.label_missing)

    def test_yan_is_hatasi_durumu_bozmaz(self):
        Shipment = type(self.env['cargo.shipment'])
        picking = self.picking()
        self.carrier.prod_environment = True
        shipment = self.mk()
        shipment.sudo().picking_id = picking
        boom = RuntimeError('yan is coktu')
        with patch.object(Shipment, '_cargo_store_labels', side_effect=boom), \
                patch.object(Shipment, '_cargo_write_picking_tracking', side_effect=boom), \
                self.assertLogs(_LOGGER, 'WARNING') as logs:
            shipment.action_send()
        self.assertEqual(shipment.state, 'created')
        self.assertTrue(shipment.tracking_ref)
        self.assertTrue(shipment.label_missing, 'etiket yan işi çökerse etiket yok sayılır')
        self.assertIn(shipment.tracking_ref, self.chatter(shipment), 'chatter yan işi bağımsız çalışır')
        self.assertTrue(any('RuntimeError' in line for line in logs.output))
        self.assertFalse(any('yan is coktu' in line for line in logs.output))

    # -- transfer takip alanları
    def test_created_picking_yazilir(self):
        picking = self.picking()
        self.carrier.prod_environment = True
        shipment = self.mk()
        shipment.sudo().picking_id = picking
        shipment.action_send()
        self.assertFalse(shipment.test_mode)
        self.assertEqual(picking.carrier_tracking_ref, shipment.tracking_ref)
        self.assertEqual(picking.carrier_id, self.carrier)

    def test_test_mode_picking_yazilmaz(self):
        picking = self.picking()
        shipment = self.mk()
        shipment.sudo().picking_id = picking
        shipment.action_send()
        self.assertTrue(shipment.test_mode)
        self.assertFalse(picking.carrier_tracking_ref, 'test ucu takip no transfere yazılmaz')

    def test_iptal_yalniz_bizim_takibi_temizler(self):
        self.carrier.prod_environment = True
        for other_ref in (None, '1ZBASKA0001'):
            with self.subTest(other_ref=other_ref):
                picking = self.picking()
                shipment = self.mk()
                shipment.sudo().picking_id = picking
                shipment.action_send()
                if other_ref:
                    picking.carrier_tracking_ref = other_ref
                shipment.action_cancel()
                self.assertEqual(shipment.state, 'cancelled')
                self.assertEqual(picking.carrier_tracking_ref or None, other_ref)
                self.assertEqual(picking.carrier_id, self.carrier, 'firma alanı kalır')

    def test_reconcile_found_picking_yazilir(self):
        picking = self.picking()
        self.carrier.prod_environment = True
        self.provider.plan['send'] = self.provider.uncertain_send()
        shipment = self.mk()
        shipment.sudo().picking_id = picking
        shipment.action_send()
        shipment.sudo().sent_at = self.minutes_ago(20)
        self.provider.plan['find'] = self.provider.found('1ZUZLAS0001')
        shipment.action_reconcile()
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(picking.carrier_tracking_ref, '1ZUZLAS0001')

    # -- K-26: test_mode gönderim anında
    def test_test_mode_sending_aninda_yazilir(self):
        shipment = self.mk()
        self.assertTrue(shipment.test_mode)
        self.carrier.prod_environment = True
        shipment.action_send()
        self.assertFalse(shipment.test_mode)
        self.assertFalse(self.provider.of('send')[0]['test_mode'], 'sağlayıcı çağrı anında canlı bayrağı görür')
        self.carrier.prod_environment = False
        shipment.action_cancel()
        self.assertFalse(shipment.test_mode, 'gönderilmiş kaydın bayrağı firma değişince oynamaz')
        self.assertFalse(self.provider.of('cancel')[0]['test_mode'])

    # -- KK-3: istisna metni sızmaz
    def test_istisna_metni_loga_ve_chattera_gitmez(self):
        secret = 'GIZLI-parola-4242'
        self.provider.plan['send'] = RuntimeError(secret)
        shipment = self.mk()
        with self.assertLogs(_LOGGER, 'WARNING') as logs:
            shipment.action_send()
        self.assertEqual(shipment.state, 'uncertain')
        shipment.sudo().sent_at = self.minutes_ago(20)
        self.provider.plan['find'] = ValueError(secret)
        with self.assertLogs(_LOGGER, 'WARNING') as more:
            shipment.action_reconcile()
        self.assertEqual(shipment.state, 'uncertain', 'find istisnası hata sayılır, durum belirsiz kalır')
        self.provider.plan['send'] = lambda s: self.provider.ok_send(shipment=s)
        created = self.sent()
        self.provider.plan['cancel'] = ConnectionError(secret)
        with self.assertLogs(_LOGGER, 'WARNING') as cancel_logs:
            created.action_cancel()
        self.assertEqual(created.state, 'created', 'iptal istisnası belirsiz: durum değişmez')
        for record in (shipment, created):
            self.assertNotIn(secret, self.chatter(record))
            self.assertNotIn(secret, record.error_message or '')
        output = '\n'.join(logs.output + more.output + cancel_logs.output)
        self.assertNotIn(secret, output)
        self.assertIn('RuntimeError', output)


@tagged('post_install', '-at_install', 'cargo')
class TestShipmentCompany(CargoKabulCase):
    """Çok şirket ayrımı (güvenlik taraması): check_company + global şirket kuralı."""

    @classmethod
    def _kur(cls):
        super()._kur()
        cls.company2 = cls.env['res.company'].create({'name': 'KK Kargo Sirket 2'})
        product = cls.env['product.product'].create(
            {'name': 'Kargo hizmeti (sirket 2)', 'type': 'service', 'company_id': cls.company2.id})
        cls.carrier2 = cls.make_carrier('KK Kargo Sirket 2', product_id=product.id)

    def test_baska_sirket_firmasi_reddedilir(self):
        self.assertEqual(self.carrier2.company_id, self.company2)
        with self.assertRaises(UserError):
            self.env['cargo.shipment'].create(self.vals(carrier_id=self.carrier2.id))
        shipment = self.mk()
        with self.assertRaises(UserError):
            shipment.write({'carrier_id': self.carrier2.id})

    def test_baska_sirket_gonderisi_gorunmez_ve_islenmez(self):
        foreign = self.env['cargo.shipment'].create(
            self.vals(carrier_id=self.carrier2.id, company_id=self.company2.id))
        Shipment = self.env['cargo.shipment'].with_user(self.user)
        self.assertNotIn(foreign, Shipment.search([]))
        own = self.mk()
        self.assertIn(own, Shipment.search([]))
        for action in ('action_send', 'action_reconcile', 'action_cancel'):
            with self.subTest(action=action), self.assertRaises(AccessError):
                getattr(foreign.with_user(self.user), action)()
        self.no_provider_calls()
