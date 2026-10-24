# -*- coding: utf-8 -*-
"""Satır kilidi (FOR UPDATE NOWAIT) birim testi: ayrı bağlantılar, commit'li veri (G4, KK-12).

NEDEN ayrı bağlantı: test kipinde registry.cursor() ana işlemi paylaşır; kilit yarışması ancak
sql_db.db_connect ile açılan yeni bağlantılarla gözlenir. Veri commit'lidir ve test sonunda SQL ile silinir.
DIKKAT: sınıf işleminde paylaşılan satırlara (res.company vb.) YAZILMAZ: ayrı bağlantının FK denetimi o
satırın kilidini bekler ve test takılır (bkz. test_kabul_akis TestKabulEszamanlilik kök nedeni).
"""
import time
from unittest.mock import patch

from odoo import SUPERUSER_ID, api, sql_db
from odoo.exceptions import UserError
from odoo.tests import tagged

from .kabul_taban import CargoKabulCase

_CARRIER_NAME = 'KK Kilit Kargo'
_AREA_CODE = 999901      # kabul eşzamanlılık sınıfının aralığı (990000-999000) dışında


@tagged('post_install', '-at_install', 'cargo')
class TestShipmentConcurrency(CargoKabulCase):
    FAKE_COMMIT = False

    @classmethod
    def _kur(cls):
        # NEDEN: taban _kur şirket satırına yazar; ayrı bağlantının INSERT'i o kilidi bekler (bkz. modül notu).
        pass

    def setUp(self):
        super().setUp()
        self.admin_id = self.env.ref('base.user_admin').id
        self.group_id = self.env.ref('cargo.group_cargo_user').id
        self.purge()          # önceki yarıda kalmış koşunun artıkları
        self.addCleanup(self.purge)
        cr = self.cursor()
        try:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env['res.users'].browse(self.admin_id).write({'group_ids': [(4, self.group_id)]})
            state = env.ref('base.state_tr_06')
            area = env['cargo.area'].create({'provider': 'fixed', 'state_id': state.id, 'name': 'CANKAYA',
                                             'city_code': 6, 'area_code': _AREA_CODE})
            product = env['product.product'].create({'name': 'Kargo (kilit testi)', 'type': 'service'})
            carrier = env['delivery.carrier'].create({
                'name': _CARRIER_NAME, 'delivery_type': 'fixed', 'product_id': product.id,
                'integration_level': 'rate'})
            shipment = env['cargo.shipment'].with_user(self.admin_id).create({
                'carrier_id': carrier.id, 'recipient_name': 'Kilit Test', 'recipient_phone': '05321234567',
                'recipient_street': 'Ataturk Mah. Test Sk. 1', 'recipient_state_id': state.id,
                'recipient_district': 'Cankaya', 'package_count': 1, 'package_weight': 1.0})
            self.area_id, self.shipment_id, self.product_id = area.id, shipment.id, product.id
            cr.commit()
        finally:
            cr.close()
        # NEDEN: ayrı bağlantı commit'li şirketi görür (adresi boş olabilir); gönderici ilçesi commit'li alana bağlanır.
        Shipment = type(self.env['cargo.shipment'])
        patcher = patch.object(Shipment, '_cargo_sender_area', lambda s: s.env['cargo.area'].browse(self.area_id))
        patcher.start()
        self.addCleanup(patcher.stop)

    def cursor(self):
        cr = sql_db.db_connect(self.env.cr.dbname).cursor()
        # NEDEN: kilit sorunu sonsuz bekleme yerine hata versin; temizlik (purge) yine çalışır.
        cr.execute("SET lock_timeout = '10s'")
        return cr

    def purge(self):
        cr = self.cursor()
        try:
            cr.execute("SELECT id FROM delivery_carrier WHERE name->>'en_US' = %s", [_CARRIER_NAME])
            carriers = tuple(r[0] for r in cr.fetchall()) or (0,)
            cr.execute('SELECT id FROM cargo_shipment WHERE carrier_id IN %s', [carriers])
            shipments = tuple(r[0] for r in cr.fetchall()) or (0,)
            for table, column in (('ir_attachment', 'res_id'), ('mail_message', 'res_id'),
                                  ('mail_followers', 'res_id')):
                model_col = 'res_model' if table != 'mail_message' else 'model'
                cr.execute('DELETE FROM %s WHERE %s = %%s AND %s IN %%s' % (table, model_col, column),
                           ['cargo.shipment', shipments])
            cr.execute('DELETE FROM cargo_shipment WHERE id IN %s', [shipments])
            cr.execute('SELECT product_id FROM delivery_carrier WHERE id IN %s', [carriers])
            products = tuple(r[0] for r in cr.fetchall()) or (0,)
            cr.execute('DELETE FROM delivery_carrier WHERE id IN %s', [carriers])
            cr.execute("DELETE FROM product_product WHERE id IN %s AND id NOT IN (SELECT res_id FROM ir_model_data"
                       " WHERE model = 'product.product') RETURNING product_tmpl_id", [products])
            templates = tuple(r[0] for r in cr.fetchall()) or (0,)
            cr.execute('DELETE FROM product_template WHERE id IN %s', [templates])
            cr.execute('DELETE FROM cargo_area WHERE area_code = %s', [_AREA_CODE])
            env = api.Environment(cr, SUPERUSER_ID, {})
            env['res.users'].browse(self.admin_id).write({'group_ids': [(3, self.group_id)]})
            cr.commit()
        finally:
            cr.close()

    def run_as_admin(self, method):
        """Ayrı bağlantıda admin olarak ``method`` çağırır -> ('ok', sonuç) | ('error', istisna)."""
        cr = self.cursor()
        try:
            env = api.Environment(cr, self.admin_id, {})
            try:
                result = getattr(env['cargo.shipment'].browse(self.shipment_id), method)()
                cr.commit()
                return 'ok', result
            except Exception as error:      # noqa: BLE001 - sonuç raporu
                cr.rollback()
                return 'error', error
        finally:
            cr.close()

    def db_state(self):
        cr = self.cursor()
        try:
            cr.execute('SELECT state FROM cargo_shipment WHERE id = %s', [self.shipment_id])
            return cr.fetchone()[0]
        finally:
            cr.close()

    def test_nowait_ikinci_oturum(self):
        """Satır başka oturumda kilitliyken gönder/uzlaştır/iptal BEKLEMEZ, 'zaten işleniyor' verir, dışarı çıkmaz."""
        holder = self.cursor()
        try:
            holder.execute('SELECT id FROM cargo_shipment WHERE id = %s FOR UPDATE', [self.shipment_id])
            for method in ('action_send', 'action_reconcile', 'action_cancel'):
                with self.subTest(method=method):
                    started = time.monotonic()
                    kind, error = self.run_as_admin(method)
                    # NEDEN: NOWAIT yoksa oturum lock_timeout (10 sn) kadar bekler ve yine "zaten" alır.
                    self.assertLess(time.monotonic() - started, 5, 'kilit beklenmemeli (NOWAIT)')
                    self.assertEqual(kind, 'error')
                    self.assertIsInstance(error, UserError, 'ham veritabanı hatası sızmamalı: %r' % (error,))
                    self.assertRegex(str(error), r'zaten işleniyor')
        finally:
            holder.rollback()
            holder.close()
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.db_state(), 'draft')

        kind, result = self.run_as_admin('action_send')
        self.assertEqual(kind, 'ok', 'kilit bırakılınca gönderim yapılmalı: %r' % (result,))
        self.assertEqual(self.provider.count('send'), 1)
        self.assertEqual(self.provider.of('send')[0]['state'], 'sending', 'sağlayıcı çağrısı anında commit\'li sending')
        self.assertEqual(self.db_state(), 'created')
