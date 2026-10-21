# -*- coding: utf-8 -*-
"""AI içerik kuyruğu: "Şimdi İşle" senkron sınırı, cron süre bütçesi, kayıt yalıtımı.

Dış AI çağrıları mock'lanır; cr.commit testte işlem sınırını bozmasın diye susturulur.
"""
import base64
import io
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

QUEUE_MOD = 'odoo.addons.ai_title_description.models.ai_content_queue'
PROVIDER_FACTORY = 'odoo.addons.ai_title_description.services.get_ai_provider'

RESULT = {
    'trendyol_title': 'Test Başlık', 'ecommerce_title': 'Test Ürün', 'meta_title': 'm',
    'seo_keywords': [], 'html_description': '<p>x</p>', 'short_summary': 's',
    'meta_description': 'd', '_prompt_tokens': 10, '_completion_tokens': 5,
}


def _png_b64():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (8, 8), (200, 30, 40)).save(buf, 'PNG')
    return base64.b64encode(buf.getvalue())


@tagged('post_install', '-at_install', 'ai_title_description')
class TestAiContentQueue(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('ai_title_description.provider', 'gemini')
        icp.set_param('ai_title_description.gemini_api_key', 'test-key')
        # Ağ çağrısı yok: anahtar kelime keşfi ve görsel analiz kapalı
        icp.set_param('ai_title_description.use_vision', 'False')
        icp.set_param('ai_title_description.use_google_suggest', 'False')
        icp.set_param('ai_title_description.use_trendyol_suggest', 'False')
        cls.Queue = cls.env['ai.content.queue']
        cls.cron = cls.env.ref('ai_title_description.ir_cron_ai_content_queue')

    def setUp(self):
        super().setUp()
        # Testte cr.commit yasaklı (örnek öznitelik); kuyruk kodu her kayıtta commit eder
        patcher = patch.object(self.env.cr, 'commit', lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Önceki/başka kayıtlar sayımı bozmasın
        self.Queue.search([]).unlink()

    def _records(self, n, **vals):
        recs = self.Queue
        for i in range(n):
            # Ürünler tek tek oluşturulur (toplu create'te image_1920 yalnız ilkine yazılır)
            product = self.env['product.template'].create({'name': 'Kuyruk Ürün %d' % i, 'image_1920': _png_b64()})
            # create_date aynı işlemde eşit olur; sıra için öncelik farkı ver
            recs |= self.Queue.create(dict({'product_tmpl_id': product.id, 'priority': 10 + i}, **vals))
        return recs

    def _triggers(self):
        return self.env['ir.cron.trigger'].sudo().search_count([('cron_id', '=', self.cron.id)])

    def _provider(self, side_effect=None):
        provider = MagicMock()
        provider.failed_calls = []
        provider.generate.side_effect = side_effect or (lambda **kw: dict(RESULT))
        return provider

    # ── KK1: Şimdi İşle senkron sınırı ───────────────────────────────
    def test_process_now_limits_sync_and_queues_rest(self):
        recs = self._records(5)
        provider = self._provider()
        before = self._triggers()
        with patch(PROVIDER_FACTORY, return_value=provider):
            action = recs.action_process_now()
        self.assertEqual(provider.generate.call_count, 3, 'en fazla 3 kayıt senkron işlenmeli')
        self.assertEqual(len(recs.filtered(lambda r: r.state == 'done')), 3)
        self.assertEqual(len(recs.filtered(lambda r: r.state == 'pending')), 2, 'fazlası kuyrukta kalmalı')
        self.assertEqual(self._triggers(), before + 1, 'kuyruk cron\'u tetiklenmeli')
        message = action['params']['message']
        self.assertIn('2 kayıt kuyruğa alındı', message, 'kullanıcıya kuyruğa alınan sayı bildirilmeli')

    def test_process_now_within_limit_does_not_trigger(self):
        recs = self._records(2)
        before = self._triggers()
        with patch(PROVIDER_FACTORY, return_value=self._provider()):
            action = recs.action_process_now()
        self.assertEqual(set(recs.mapped('state')), {'done'})
        self.assertEqual(self._triggers(), before, 'kuyruğa alınan yoksa tetik gerekmez')
        self.assertNotIn('kuyruğa alındı', action['params']['message'])

    # ── KK2: cron süre bütçesi ───────────────────────────────────────
    def test_cron_stops_at_time_budget_and_retriggers(self):
        recs = self._records(4)
        clock = [0.0]

        def generate(**kw):
            clock[0] += 60.0  # her çağrı 60 sn sürmüş gibi
            return dict(RESULT)

        fake_time = MagicMock()
        fake_time.monotonic.side_effect = lambda: clock[0]
        before = self._triggers()
        with patch(PROVIDER_FACTORY, return_value=self._provider(generate)), \
                patch(QUEUE_MOD + '.time', fake_time):
            self.Queue._cron_process_queue(batch_size=10)  # bütçe varsayılan: ~100 sn
        states = recs.mapped('state')
        self.assertEqual(states.count('done'), 2, 'bütçe (100 sn) 2 kayıttan sonra dolmalı')
        self.assertEqual(states.count('pending'), 2, 'kalanlar işlenmeden bekletilmeli')
        self.assertNotIn('processing', states)
        self.assertEqual(self._triggers(), before + 1, 'iş kaldıysa cron kendini tetiklemeli')

    def test_cron_does_not_retrigger_when_everything_fits(self):
        self._records(2)
        before = self._triggers()
        with patch(PROVIDER_FACTORY, return_value=self._provider()):
            self.Queue._cron_process_queue(batch_size=10)
        self.assertEqual(self._triggers(), before)

    def test_cron_budget_does_not_retrigger_for_failed_records(self):
        # Hata ile pending'e dönen kayıt aynı turda yeniden denenmiş sayılır: sonsuz tetik döngüsü olmaz
        recs = self._records(1)
        clock = [0.0]

        def boom(**kw):
            clock[0] += 200.0
            raise ValueError('api kapalı')

        fake_time = MagicMock()
        fake_time.monotonic.side_effect = lambda: clock[0]
        before = self._triggers()
        with patch(PROVIDER_FACTORY, return_value=self._provider(boom)), \
                patch(QUEUE_MOD + '.time', fake_time):
            self.Queue._cron_process_queue(batch_size=10)
        self.assertEqual(recs.state, 'pending')
        self.assertEqual(self._triggers(), before)

    # ── KK2: kayıt yalıtımı ──────────────────────────────────────────
    def test_cron_isolates_broken_record(self):
        recs = self._records(3)
        calls = []

        def generate(**kw):
            calls.append(1)
            if len(calls) == 1:
                raise ValueError('bozuk kayıt')
            return dict(RESULT)

        with patch(PROVIDER_FACTORY, return_value=self._provider(generate)):
            self.Queue._cron_process_queue(batch_size=10)
        broken = recs[0]
        self.assertEqual(broken.state, 'pending', 'hata sonrası deneme hakkı varsa yeniden beklemeli')
        self.assertEqual(broken.attempts, 1)
        self.assertIn('bozuk kayıt', broken.error_message)
        self.assertEqual(recs[1:].mapped('state'), ['done', 'done'], 'bozuk kayıt cron\'u durdurmamalı')

    def test_cron_isolates_failure_in_post_processing(self):
        # AI yanıtı geldi ama ürüne yazım patladı: savepoint geri alınır, sıradaki kayıt işlenir
        recs = self._records(2)
        Product = type(self.env['product.template'])
        original = Product.write
        state = {'failed': False}

        def flaky_write(self_, vals):
            if not state['failed'] and 'ai_content_generated' in vals:
                state['failed'] = True
                raise ValueError('yazım hatası')
            return original(self_, vals)

        with patch(PROVIDER_FACTORY, return_value=self._provider()), \
                patch.object(Product, 'write', flaky_write):
            self.Queue._cron_process_queue(batch_size=10)
        self.assertEqual(recs[0].state, 'pending')
        self.assertEqual(recs[1].state, 'done')
