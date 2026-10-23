# -*- coding: utf-8 -*-
"""BIN ucu hız sınırı sıralaması (A2-G2, OTOMATIK_GUVENLIK bulgusu: sayaç kontrolü / log yazımı yarışı).

Gerçek eşzamanlılık (iki HTTP isteği aynı anda) test işleminde kurulamaz; bu yüzden SIRALAMANIN VARLIĞI
model düzeyinde doğrulanır: kullanıcıya özel ``pg_advisory_xact_lock`` sayaç kontrolünden önce alınır,
başka bir bağlantı aynı kilidi tutarken istek 429 alır (sağlayıcıya gitmez), kilit sonrası sayım Odoo
işleminin eski (REPEATABLE READ) anlık görüntüsüne takılmaz ve ``payment_id=False`` satırlar kayıt
sayacına girer. Tüm değerler sahte ya da herkese açık test değeridir.
"""
import json
import time
from datetime import timedelta
from unittest.mock import patch

from odoo import SUPERUSER_ID, api, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from ..tools import mark_payment
from .common import LEAK_BIN, querybin_body
from .test_mail_order_bin import BinCase

PAYMENT_MODULE = 'odoo.addons.sanal_pos.models.sanal_pos_payment'


class BinLockCase(BinCase):

    def setUp(self):
        super().setUp()
        self.mock.default('QUERYBIN', lambda p: querybin_body('DEBIT'))

    def lookup(self, payment, user=None):
        return payment.with_user(user or self.user_sp)._mail_order_bin_lookup(LEAK_BIN)

    def real_cursor(self):
        from odoo import sql_db
        return sql_db.db_connect(self.env.cr.dbname).cursor()

    def own_advisory_locks(self, uid):
        from odoo.addons.sanal_pos.models.sanal_pos_payment import BIN_LOCK_NAMESPACE
        self.env.cr.execute("""SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = %s
                                  AND objid = %s AND pid = pg_backend_pid()""", [BIN_LOCK_NAMESPACE, uid])
        return self.env.cr.fetchone()[0]


@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinUserLock(BinLockCase):

    def test_kilit_alinir_ve_islem_sonuna_kadar_tutulur(self):
        payment = self.make_mail_order()
        self.assertEqual(self.own_advisory_locks(self.user_sp.id), 0)
        self.assertEqual(self.lookup(payment)['status'], 200)
        self.assertEqual(self.own_advisory_locks(self.user_sp.id), 1,
                         'kilit QUERYBIN satırıyla birlikte düşmeli: işlem sonuna kadar tutulur')
        self.assertEqual(self.own_advisory_locks(self.user_sp.id + 100000), 0, 'kilit kullanıcıya özel')

    def test_kilit_sayac_kontrolunden_once_alinir(self):
        payment = self.make_mail_order()
        order = []
        model = type(payment)
        original_lock, original_check = model._bin_user_lock, model._bin_rate_limited

        def lock(this):
            order.append('lock')
            return original_lock(this)

        def check(this):
            order.append('check')
            return original_check(this)

        with patch.object(model, '_bin_user_lock', lock), patch.object(model, '_bin_rate_limited', check):
            self.assertEqual(self.lookup(payment)['status'], 200)
        self.assertEqual(order, ['lock', 'check'])

    def test_gecersiz_ve_kapali_istek_kilit_almaz(self):
        closed = self.make_mail_order(state='expired')
        with self.assertRaises(UserError):
            self.lookup(closed)
        self.assertEqual(self.own_advisory_locks(self.user_sp.id), 0, 'kapalı kayıt kilide hiç girmez')

    def test_baska_baglanti_ayni_kullanici_kilidini_tutarken_429_paratika_yok(self):
        from odoo.addons.sanal_pos.models.sanal_pos_payment import BIN_LOCK_NAMESPACE
        payment = self.make_mail_order()
        other = self.real_cursor()
        try:
            other.execute('SELECT pg_advisory_lock(%s, %s)', [BIN_LOCK_NAMESPACE, self.user_sp.id])
            started = time.monotonic()
            with patch(PAYMENT_MODULE + '.BIN_LOCK_TIMEOUT', '300ms'):
                result = self.lookup(payment)
            self.assertLess(time.monotonic() - started, 3, 'bekleme sınırlıdır')
            self.assertEqual(result, {'status': 429})
            self.assertNoParatikaCalls()
            self.assertFalse(self.logs('QUERYBIN'))
            self.env.cr.execute('SHOW lock_timeout')
            self.assertEqual(self.env.cr.fetchone()[0], '0', 'lock_timeout geri yüklendi')
            # başka kullanıcının kilidi etkilenmez
            self.assertEqual(self.lookup(payment, user=self.user_mgr)['status'], 200)
            other.execute('SELECT pg_advisory_unlock(%s, %s)', [BIN_LOCK_NAMESPACE, self.user_sp.id])
            self.assertEqual(self.lookup(payment)['status'], 200, 'kilit bırakılınca sorgu çalışır')
        finally:
            other.close()

    def test_baska_baglanti_kayit_kilidini_tutarken_baska_kullanici_429(self):
        """G2-1: farklı kullanıcılar aynı kayda sorarken 20/sa kayıt sayacı da sıralanır."""
        from odoo.addons.sanal_pos.models.sanal_pos_payment import BIN_RECORD_LOCK_NAMESPACE
        payment = self.make_mail_order()
        sibling = self.make_mail_order(invoice_no='BIN-SIB', merchant_payment_id='BIN-SIB-1')
        other = self.real_cursor()
        try:
            other.execute('SELECT pg_advisory_lock(%s, %s)', [BIN_RECORD_LOCK_NAMESPACE, payment.id])
            with patch(PAYMENT_MODULE + '.BIN_LOCK_TIMEOUT', '300ms'), self.capture_logs() as captured:
                result = self.lookup(payment, user=self.user_mgr)
            self.assertEqual(result, {'status': 429})
            self.assertNoParatikaCalls()
            self.assertFalse(self.logs('QUERYBIN'))
            self.assertTrue(any('sıralama kilidi alınamadı' in line for line in captured), captured)
            self.assertEqual(self.lookup(sibling, user=self.user_mgr)['status'], 200, 'kilit kayda özel')
            other.execute('SELECT pg_advisory_unlock(%s, %s)', [BIN_RECORD_LOCK_NAMESPACE, payment.id])
            self.assertEqual(self.lookup(payment, user=self.user_mgr)['status'], 200)
            self.env.cr.execute("""SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = %s
                                      AND objid = %s AND pid = pg_backend_pid()""",
                                [BIN_RECORD_LOCK_NAMESPACE, payment.id])
            self.assertEqual(self.env.cr.fetchone()[0], 1, 'kayıt kilidi işlem sonuna kadar tutulur')
        finally:
            other.close()

    def test_sure_butcesi_kilit_beklemesini_kapsar(self):
        """Ö-1: ikinci çağrı sınırı (1,0 sn) istek başından ölçülür; kilit beklemesi de içindedir."""
        payment = self.make_mail_order()
        model = type(payment)
        original_lock = model._bin_user_lock
        offset = [0.0]
        real = time.monotonic

        def slow_lock(this):
            offset[0] += 0.8                 # kilit beklemesi
            return original_lock(this)

        def quick_bin(params):
            offset[0] += 0.3                 # tek başına 1,0 sn altında
            return querybin_body('CREDIT')

        self.mock.queue('QUERYBIN', quick_bin)
        with patch.object(model, '_bin_user_lock', slow_lock), patch('time.monotonic', lambda: real() + offset[0]):
            self.assertEqual(self.lookup(payment), {'status': 502})
        self.assertEqual(self.mock.actions, ['QUERYBIN'], '0,8 + 0,3 > 1,0: ikinci çağrı yapılmaz')
        from odoo.addons.sanal_pos.models import sanal_pos_payment as module
        self.assertEqual(module.BIN_LOCK_TIMEOUT, '500ms', 'NFR-2.1: 2 x 0,5 + 3,5 = 4,5 sn')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinRecordCounter(BinLockCase):

    def fallback_rows(self, payment, count):
        """Kayıt kilitliyken yazılan satırları taklit eder: ilk create LockNotAvailable atar (yedek dal)."""
        from psycopg2 import errors
        Log = type(self.env['sanal.pos.log'])
        original = Log.create

        def create(this, vals_list):
            items = vals_list if isinstance(vals_list, list) else [vals_list]
            if any(v.get('action') == 'QUERYBIN' and v.get('payment_id') for v in items):
                raise errors.LockNotAvailable('canceling statement due to lock timeout')
            return original(this, vals_list)

        with patch.object(Log, 'create', create):
            return [self.lookup(payment)['status'] for _ in range(count)]

    def test_yedek_dalda_yazilan_satir_kayit_isareti_tasir(self):
        payment = self.make_mail_order()
        self.assertEqual(self.fallback_rows(payment, 1), [200])
        row = self.logs('QUERYBIN')
        self.assertFalse(row.payment_id)
        self.assertEqual(json.loads(row.request_body)['_payment_id'], payment.id)
        self.assertNotIn(LEAK_BIN, row.request_body)

    def test_payment_id_olmayan_satirlar_kayit_sayacina_girer(self):
        payment = self.make_mail_order()
        self.assertEqual(self.fallback_rows(payment, 20), [200] * 20)
        self.assertTrue(all(not r.payment_id for r in self.logs('QUERYBIN')))
        self.assertEqual(self.lookup(payment), {'status': 429},
                         'ödemeye bağlanamayan 20 satır da kayıt sayacına girer')

    def test_kayit_kimligi_onek_cakismasi_yok(self):
        payment = self.make_mail_order()
        other_id = payment.id * 10          # '"_payment_id": 123}' ile '"_payment_id": 12}' farklıdır
        Log = self.env['sanal.pos.log'].sudo()
        for _ in range(3):
            Log.create({'action': 'QUERYBIN', 'provider': 'paratika', 'environment': 'test',
                        'request_body': mark_payment('{"ACTION": "QUERYBIN"}', other_id)})
        since = fields.Datetime.now() - timedelta(hours=1)
        self.assertEqual(payment._bin_counts(Log, since)[0], 0, '12 işareti 120 satırlarını saymaz')
        self.assertEqual(payment.browse(other_id)._bin_counts(Log, since)[0], 3)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinFreshSnapshot(BinLockCase):
    """Kilit beklerken eskiyen REPEATABLE READ anlık görüntüsü, başka bağlantının commit'ini saymayı engellemez."""

    def setUp(self):
        super().setUp()
        self.committed = []
        self.addCleanup(self.purge)

    def purge(self):
        if not self.committed:
            return
        cr = self.real_cursor()
        try:
            cr.execute('DELETE FROM sanal_pos_log WHERE id IN %s', [tuple(self.committed)])
            cr.commit()
        finally:
            cr.close()

    def commit_marked_rows(self, payment, count, uid=SUPERUSER_ID, warning=False):
        cr = self.real_cursor()
        try:
            Log = api.Environment(cr, uid, {}, su=True)['sanal.pos.log']
            vals = [{'action': 'QUERYBIN', 'provider': 'paratika', 'environment': 'test',
                     'request_body': mark_payment('{"ACTION": "QUERYBIN"}', payment.id)}
                    for _ in range(count)]
            if warning:
                vals.append({'action': 'BIN_RATE_LIMIT', 'provider': 'paratika', 'environment': 'test',
                             'request_body': json.dumps({'user_id': uid, 'payment_id': payment.id})})
            rows = Log.create(vals)
            self.committed += rows.ids
            cr.commit()
        finally:
            cr.close()

    def test_baska_baglantinin_commitli_satirlari_sayilir(self):
        payment = self.make_mail_order()
        Log = self.env['sanal.pos.log'].sudo()
        self.assertEqual(self.lookup(payment)['status'], 200)       # işlemin anlık görüntüsü alındı
        self.commit_marked_rows(payment, 20)
        main_count = payment._bin_counts(Log, fields.Datetime.now() - timedelta(hours=1))[0]
        self.assertEqual(main_count, 1, 'önkoşul: ana işlem başka bağlantının commit\'ini görmez (eski anlık görüntü)')
        # NEDEN yama: test kipinde registry.cursor() ana işlemi paylaşır; üretimdeki gerçek yeni imleç taklit edilir
        with patch.object(self.registry, 'cursor', self.real_cursor):
            self.assertEqual(self.lookup(payment), {'status': 429})
        self.assertEqual(self.mock.count('QUERYBIN'), 1, 'reddedilen istek sağlayıcıya gitmez')

    def test_baska_baglantinin_commitli_uyari_satiri_varken_ikinci_uyari_yok(self):
        """G2-2: eşzamanlı istekten commit'lenmiş BIN_RATE_LIMIT satırı yeni imleçte görülür; çift satır/uyarı yok.

        Kullanıcı commit'li yönetici (id 2): diğer bağlantıda ``create_uid`` FK'si test işlemindeki kullanıcıyı görmez.
        """
        admin = self.env.ref('base.user_admin')
        admin.write({'group_ids': [(4, self.env.ref('sanal_pos.group_sanal_pos_user').id)]})
        payment = self.make_mail_order()
        Log = self.env['sanal.pos.log'].sudo()
        self.commit_marked_rows(payment, 20, uid=admin.id, warning=True)
        self.assertFalse(Log.search([('action', '=', 'BIN_RATE_LIMIT')]),
                         'önkoşul: ana işlem commit\'li uyarı satırını görmez (eski anlık görüntü)')
        with patch.object(self.registry, 'cursor', self.real_cursor), self.capture_logs() as captured:
            self.assertEqual(self.lookup(payment, user=admin), {'status': 429})
        self.assertFalse([line for line in captured if 'hız sınırı aşıldı' in line], 'ikinci uyarı yazılmaz')
        self.assertFalse(Log.search([('action', '=', 'BIN_RATE_LIMIT')]), 'ikinci BIN_RATE_LIMIT satırı yazılmaz')
        self.assertNoParatikaCalls()
