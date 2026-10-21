"""Nebim zincirinde toplam süre bütçesi (BORC B8): GERÇEK HTTP, yerel sahte IntegratorService.

Veri uçları asılı (hung) ya da yavaş; Connect hızlı. Süreler küçültülmüştür (üretimde çağrı 60 sn,
bütçe 75 sn). Asılı sunucuda zincir, ilk zaman aşımında kalan aşamaları atlayıp tek çağrı süresinde
bitmelidir; yavaş ama yanıtlayan sunucuda zincir bütçe + küçük pay içinde bitmelidir."""
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import requests

from odoo.tests import tagged
from odoo.tests.common import _super_send

from odoo.addons.odoougurlar.services import nebim_connector as nc
from odoo.addons.ugurlar_barcode.controllers import batch_api, packing_api
from odoo.addons.ugurlar_barcode.tests.common import PackingCase

_logger = logging.getLogger(__name__)

CALL_TIMEOUT = 1.0      # üretimde WRITE_CHAIN_TIMEOUT = 60
BUDGET = 3.0            # üretimde NEBIM_COMPLETE_BUDGET = 75
PAY = 1.5               # bütçe üstü kabul edilen pay (Odoo işi + son çağrının yuvarlanması)


class _FakeNebim:
    """Connect hızlı; diğer uçlar `mode`'a göre asılı / yavaş / hızlı. `calls` veri çağrıları."""

    def __init__(self):
        self.mode = 'hang'
        self.delay = 0.0
        self.calls = []
        self.post_models = []   # gelen Post'ların ModelType'ı (cari 2/3, sipariş 13/14, fatura ...)
        self.stop = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                if self.path.endswith('/Connect'):
                    return self._send({'SessionID': 'fake-session'})
                try:
                    data = json.loads(body or b'{}')
                except ValueError:
                    data = {}
                proc = data.get('ProcName') or self.path.rsplit('/', 1)[-1]
                owner.calls.append(proc)
                if self.path.endswith('/Post'):
                    owner.post_models.append(data.get('ModelType'))
                # 'hang_after_post': ilk Post'a kadar hızlı (sorgular boş), sonra yalnız Post dışı uçlar asılı
                if owner.mode == 'hang' or (owner.mode == 'hang_after_post' and owner.post_models
                                            and not self.path.endswith('/Post')):
                    owner.stop.wait(30)
                    return
                if owner.delay:
                    owner.stop.wait(owner.delay)
                self._send({'HeaderID': 'H-1', 'CurrAccCode': '1-4-1', 'DocumentNumber': 'D-1'}
                           if self.path.endswith('/Post') else [])

            def _send(self, data):
                raw = json.dumps(data).encode()
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.url = 'http://127.0.0.1:%s/IntegratorService' % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()


@tagged('post_install', '-at_install')
class TestNebimChainBudget(PackingCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod = cls._new_product('Nebim Bütçe Ürünü', 'NCB-1')

    def setUp(self):
        super().setUp()
        self._patch_request(batch_api)
        self.fake = _FakeNebim()
        self.addCleanup(self.fake.close)
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('odoougurlar.nebim_url', self.fake.url)
        for key in ('customer', 'order', 'invoice'):
            icp.set_param('odoougurlar.nebim_sync_%s_enabled' % key, 'True')
        self.customer.write({'email': 'nebim.butce@example.com', 'phone': '05321234567',
                             'city': 'Kadıköy', 'street': 'Test Sokak 1'})
        # NEDEN: Odoo test koşucusu requests.Session.send'i yamar (tuple timeout'ta patlar, <10 sn
        # timeout'u 10'a çıkarır, localhost'a özgün send ile geçer). Süre ölçümü için özgün send.
        p = patch.object(requests.Session, 'send', _super_send)
        p.start()
        self.addCleanup(p.stop)
        saved = dict(nc._session_cache)
        nc._session_cache.update(token=None, expires=0)
        self.addCleanup(nc._session_cache.update, saved)
        for name, value in (('WRITE_CHAIN_TIMEOUT', CALL_TIMEOUT), ('NEBIM_COMPLETE_BUDGET', BUDGET)):
            p = patch.object(packing_api, name, value)
            p.start()
            self.addCleanup(p.stop)
        # TestCursor commit'i savepoint'e çevirir; fatura aşaması commit eder
        p = patch.object(self.env.cr, 'commit', self.env.flush_all)
        p.start()
        self.addCleanup(p.stop)

    def _complete(self):
        sale, picking = self._sale(self.prod, 1)
        batch = self._route(picking)
        picking.move_ids.write({'wave_collected_qty': 1, 'wave_skipped': False})
        res = batch_api.BatchApiController().batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        t0 = time.monotonic()
        res = self.pack_ctl.packing_complete(batch_id=batch.id)
        elapsed = time.monotonic() - t0
        _logger.info('B8 ÖLÇÜM: zincir %.2f sn, veri çağrısı %d: %s', elapsed,
                     len(self.fake.calls), self.fake.calls)
        return sale, picking, batch, res, elapsed

    def test_hung_data_endpoints_chain_stops_at_first_timeout(self):
        """Asılı uç: ilk zaman aşımında kalan aşamalar atlanır (önce: her aşama ayrı CALL_TIMEOUT)."""
        self.fake.mode = 'hang'
        sale, picking, batch, res, elapsed = self._complete()
        self.assertEqual(picking.state, 'done', 'doğrulama Nebim hatasından etkilenmez')
        self.assertEqual(len(self.fake.calls), 1, 'ilk zaman aşımından sonra ağ çağrısı yok: %s' % self.fake.calls)
        self.assertLess(elapsed, CALL_TIMEOUT + PAY)
        sale.invalidate_recordset()
        self.assertFalse(sale.nebim_customer_sent)
        self.assertFalse(sale.nebim_order_sent)
        self.assertIn('HATA', sale.nebim_order_response or '')
        # Tekrar denenebilir: sunucu düzelince aynı sipariş aktarılır
        self.fake.mode = 'ok'
        self.fake.calls.clear()
        self.pack_ctl._trigger_nebim_sync(picking)
        sale.invalidate_recordset()
        self.assertTrue(sale.nebim_customer_sent)
        self.assertTrue(sale.nebim_order_sent)

    def _spy_http(self):
        """Gerçek gönderimi bozmadan her HTTP çağrısının (uç, ProcName, timeout) kaydı."""
        sent = []
        orig = nc._http_session.post

        def spy(url, *args, **kwargs):
            sent.append((url.rsplit('/', 1)[-1], (kwargs.get('json') or {}).get('ProcName'),
                         kwargs.get('timeout')))
            return orig(url, *args, **kwargs)
        p = patch.object(nc._http_session, 'post', spy)
        p.start()
        self.addCleanup(p.stop)
        return sent

    def test_slow_data_endpoints_chain_bounded_by_deadline(self):
        """Yavaş ama yanıtlayan uç: zincir toplam bütçeyi aşmaz; YAZMA (Post) kısaltılmış timeout ile
        hiç başlamaz (K-1: kesilen Post Nebim'de belge açar, nebim_sent yazılmaz -> mükerrer belge)."""
        self.fake.mode = 'slow'
        self.fake.delay = 0.7       # her çağrı timeout altında; toplamı bütçeyi aşar
        sent = self._spy_http()
        sale, picking, batch, res, elapsed = self._complete()
        self.assertEqual(picking.state, 'done')
        self.assertLess(elapsed, BUDGET + PAY, 'zincir deadline + pay içinde bitmeli')
        self.assertLess(len(self.fake.calls), 6, self.fake.calls)
        posts = [t for ep, _proc, t in sent if ep == 'Post']
        self.assertTrue(all(t[1] == CALL_TIMEOUT for t in posts), 'Post yalnız tam timeout ile: %s' % sent)
        # Gönderilen her Post yanıtlandı (0,7 < 1 sn): cari gittiyse kodu kayıtlı, kesilen yazma yok
        sale.invalidate_recordset()
        self.assertEqual(sale.nebim_customer_sent, any(m in (2, 3) for m in self.fake.post_models),
                         self.fake.post_models)

    def test_write_without_full_budget_is_never_sent(self):
        """Kalan süre < yazma timeout'u: Post ve numara SP'si ağa HİÇ çıkmaz (Connect dahil);
        okuma ise kalan süreye kısaltılıp yapılır."""
        self.fake.mode = 'slow'
        sent = self._spy_http()
        conn = self.env['odoougurlar.nebim.connector'].with_context(
            nebim_timeout=CALL_TIMEOUT, nebim_retries=0, nebim_deadline=time.monotonic() + CALL_TIMEOUT / 2)
        with self.assertRaises(nc.NebimTimeoutError):
            conn.post_data('Post', {'ModelType': 13})
        with self.assertRaises(nc.NebimTimeoutError):
            conn.run_proc('sp_GetNextExportFileNumber_Hamurlabs')
        self.assertEqual(sent, [], 'yazma için hiçbir istek gitmemeli')
        self.assertEqual(self.fake.calls, [])
        conn.run_proc('sp_GetCustomer_Hamurlabs')
        self.assertEqual(self.fake.calls, ['sp_GetCustomer_Hamurlabs'])
        self.assertLessEqual(sent[-1][2][1], CALL_TIMEOUT / 2, 'okuma kalan süreye kısaltılır')

    def test_write_with_budget_uses_full_timeout(self):
        self.fake.mode = 'slow'
        sent = self._spy_http()
        conn = self.env['odoougurlar.nebim.connector'].with_context(
            nebim_timeout=CALL_TIMEOUT, nebim_retries=0, nebim_deadline=time.monotonic() + CALL_TIMEOUT + 2)
        conn.post_data('Post', {'ModelType': 13})
        conn.run_proc('sp_GetNextExportFileNumber_Hamurlabs')
        writes = [t for ep, proc, t in sent if ep == 'Post' or proc == 'sp_GetNextExportFileNumber_Hamurlabs']
        self.assertEqual(len(writes), 2, sent)
        self.assertTrue(all(t[1] == CALL_TIMEOUT for t in writes), sent)

    def test_customer_post_ok_address_lookup_hung_keeps_code(self):
        """Ö-1: cari Post başarılı, ardından adres sorgusu asılı -> cari kodu kayıtlı kalır (savepoint geri
        almaz); ikinci denemede yeni cari Post'u gitmez (önce: kod kaybolur, mükerrer cari açılırdı)."""
        self.fake.mode = 'hang_after_post'
        sale, picking, batch, res, elapsed = self._complete()
        self.assertEqual(self.fake.post_models[:1], [3], self.fake.post_models)
        sale.invalidate_recordset()
        self.customer.invalidate_recordset()
        self.assertTrue(sale.nebim_customer_sent)
        self.assertEqual(sale.nebim_customer_code, '1-4-1')
        self.assertEqual(self.customer.nebim_customer_code, '1-4-1')
        self.assertFalse(sale.nebim_order_sent, 'sipariş aşaması asılı uçta tekrar denenecek')
        self.fake.mode = 'ok'
        self.fake.post_models.clear()
        self.pack_ctl._trigger_nebim_sync(picking)
        self.assertFalse([m for m in self.fake.post_models if m in (2, 3)],
                         'ikinci denemede cari Post yok: %s' % self.fake.post_models)
        sale.invalidate_recordset()
        self.assertTrue(sale.nebim_order_sent)

    def test_chain_without_deadline_context_keeps_per_call_timeout(self):
        """Cron yolu: nebim_deadline context'i yok -> connector yalnız çağrı timeout'u uygular."""
        self.fake.mode = 'hang'
        conn = self.env['odoougurlar.nebim.connector'].with_context(
            nebim_timeout=CALL_TIMEOUT, nebim_retries=0)
        t0 = time.monotonic()
        with self.assertRaises(nc.NebimTimeoutError):
            conn.run_proc('sp_Any')
        self.assertGreaterEqual(time.monotonic() - t0, CALL_TIMEOUT - 0.1)

    def test_exhausted_deadline_fails_without_network_call(self):
        conn = self.env['odoougurlar.nebim.connector'].with_context(
            nebim_timeout=CALL_TIMEOUT, nebim_retries=0, nebim_deadline=time.monotonic() - 1)
        with self.assertRaises(nc.NebimTimeoutError):
            conn.run_proc('sp_Any')
        with self.assertRaises(nc.NebimTimeoutError):
            conn.post_data('Post', {})
        self.assertEqual(self.fake.calls, [])

    def test_deadline_shortens_call_timeout(self):
        self.fake.mode = 'hang'
        conn = self.env['odoougurlar.nebim.connector'].with_context(
            nebim_timeout=30, nebim_retries=0, nebim_deadline=time.monotonic() + 1.0)
        t0 = time.monotonic()
        with self.assertRaises(nc.NebimTimeoutError):
            conn.run_proc('sp_Any')
        self.assertLess(time.monotonic() - t0, 2.5, 'çağrı 30 sn değil, kalan ~1 sn ile sınırlı')
