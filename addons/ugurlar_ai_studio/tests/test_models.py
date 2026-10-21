"""Model / veritabanı testleri: kira, yetki, renk kapsamlı kaydetme, cron."""
import base64
from contextlib import contextmanager
import io
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from unittest.mock import patch

from ..services.garment_analyzer import clear_usage_recorder
from ..models.ai_studio_session import (
    AI_QUEUE_CRONS, _get_extra_prompt_en, _make_usage_recorder, _needs_bare_legs, _try_acquire_lease,
)

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


def _image_b64(color=(200, 30, 40)):
    buf = io.BytesIO()
    Image.new('RGB', (64, 96), color).save(buf, 'JPEG')
    return base64.b64encode(buf.getvalue())


@tagged('post_install', '-at_install', 'ugurlar_ai_studio')
class TestAiStudioModels(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Kuyruk işleri tr_TR ortamında çalışır; test veritabanında dil kapalı olabilir
        cls.env['res.lang']._activate_lang('tr_TR')
        color = cls.env['product.attribute'].create({
            'name': 'Renk',
            'value_ids': [(0, 0, {'name': 'Kırmızı'}), (0, 0, {'name': 'Mavi'})],
        })
        cls.template = cls.env['product.template'].create({
            'name': 'Test Elbise',
            'attribute_line_ids': [(0, 0, {
                'attribute_id': color.id,
                'value_ids': [(6, 0, color.value_ids.ids)],
            })],
        })
        cls.red, cls.blue = cls.template.product_variant_ids[:2]
        cls.Session = cls.env['ai.studio.session']
        cls.Gen = cls.env['ai.studio.generation']
        cls.operator = new_test_user(cls.env, login='ais_operator',
                                     groups='ugurlar_ai_studio.group_ai_studio_operator')

    def setUp(self):
        super().setUp()
        # İş gövdeleri thread-local kullanım kaydedicisi kurar (üretimde _queue_run_job temizler);
        # geri alınan oturuma yazan kaydedici sonraki testlere sızmasın
        self.addCleanup(clear_usage_recorder)

    def _session(self, product, **vals):
        return self.Session.create(dict({'product_id': product.id}, **vals))

    # ── Kira ─────────────────────────────────────────────────────────
    def test_lease_is_exclusive_until_expired(self):
        session = self._session(self.red)
        cr = self.env.cr
        self.assertTrue(_try_acquire_lease(cr, session.id, 'worker-a'))
        self.assertFalse(_try_acquire_lease(cr, session.id, 'worker-b'), 'canlı kira başkasına verilmemeli')
        self.assertTrue(_try_acquire_lease(cr, session.id, 'worker-a'), 'sahibi yenileyebilmeli')
        cr.execute("UPDATE ai_studio_session SET ai_lease_until = %s WHERE id = %s",
                   (fields.Datetime.now() - timedelta(minutes=1), session.id))
        self.assertTrue(_try_acquire_lease(cr, session.id, 'worker-b'), 'süresi dolan kira devralınabilmeli')

    # ── Yetki ────────────────────────────────────────────────────────
    def test_operator_cannot_approve_via_rpc(self):
        session = self._session(self.red)
        gen = self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'done'})
        with self.assertRaises(UserError):
            gen.with_user(self.operator).action_approve()

    def test_review_session_cannot_be_restarted(self):
        session = self._session(self.red, state='review')
        with self.assertRaises(UserError):
            session.action_start_processing()

    # ── İlave talimat çevirisi (oturum başına bir kez) ───────────────
    def test_extra_prompt_translated_once_and_refreshed_on_change(self):
        session = self._session(self.red, extra_prompt='Kollar kıvrık olsun')
        Gen = type(self.env['ai.studio.generation'])
        with patch.object(Gen, '_translate_prompt', return_value='Sleeves rolled up') as tr:
            self.assertEqual(_get_extra_prompt_en(session), 'Sleeves rolled up')
            self.assertEqual(_get_extra_prompt_en(session), 'Sleeves rolled up')
            self.assertEqual(tr.call_count, 1, 'aynı metin tekrar çevrilmemeli')
            session.extra_prompt = 'Yaka açık olsun'
            _get_extra_prompt_en(session)
            self.assertEqual(tr.call_count, 2, 'metin değişince yeniden çevrilmeli')

    # ── Elbise: pantolonlu manken gönderilmez ────────────────────────
    def test_dress_needs_bare_legs_even_with_uppercase_name(self):
        self.template.name = 'ELBİSE NOCTURNE'
        session = self._session(self.red)
        self.assertTrue(_needs_bare_legs(session, {'clothingCategory': 'dress', 'garmentType': 'Elbise'}))
        self.template.name = 'Tulum'
        self.assertFalse(_needs_bare_legs(session, {'clothingCategory': 'dress', 'garmentType': 'Tulum'}))
        self.template.name = 'Bluz'
        self.assertFalse(_needs_bare_legs(session, {'clothingCategory': 'tops', 'garmentType': 'Bluz'}))

    def test_bare_leg_mannequin_cached_and_reset(self):
        preset = self.env['ai.studio.model.preset'].create({
            'name': 'Test Manken', 'garment_type': 'tops', 'model_image_front': _image_b64(),
        })
        # Bacaklar zaten açıksa orijinal görsel önbelleğe alınır, düzenleme yapılmaz
        with patch('odoo.addons.ugurlar_ai_studio.services.garment_analyzer.mannequin_legs_covered',
                   return_value=False):
            img, cost = preset._get_bare_leg_mannequin('front', 'gemini-key', 'fal-key')
        self.assertEqual(img, preset.model_image_front)
        self.assertEqual(cost, 0.0)
        # Arka mankeni olmayan preset ön sürümü paylaşır (ikinci kez ücret yok)
        back_img, back_cost = preset._get_bare_leg_mannequin('back', 'gemini-key', 'fal-key')
        self.assertEqual(back_img, preset.model_image_front_legs)
        self.assertEqual(back_cost, 0.0)
        self.assertTrue(preset.model_image_front_legs)
        # Manken görseli değişince türetilmiş sürüm sıfırlanır
        preset.model_image_front = _image_b64((10, 10, 10))
        self.assertFalse(preset.model_image_front_legs)

    # ── Ayarlar: varsayılanı açık kutular kapatılabilmeli ────────────
    def test_default_on_toggles_can_be_turned_off(self):
        settings = self.env['res.config.settings'].create({
            'ai_studio_visual_qc': False, 'ai_studio_auto_tag_fix': False, 'ai_studio_auto_bg_remove': False,
        })
        settings.execute()
        icp = self.env['ir.config_parameter'].sudo()
        self.assertEqual(icp.get_param('ugurlar_ai_studio.visual_qc'), 'False')
        self.assertEqual(icp.get_param('ugurlar_ai_studio.auto_bg_remove'), 'False')
        fresh = self.env['res.config.settings'].create({})
        self.assertFalse(fresh.ai_studio_auto_tag_fix, 'kapatılan kutu formda yeniden açık görünmemeli')

    # ── Taslak oturum ürünü kilitlemez; bütçe revizyonlarda da geçerli ─
    def test_draft_session_does_not_block_product(self):
        session = self._session(self.red)  # "Geri" ile bırakılmış taslak
        self.assertEqual(session.state, 'draft')
        active = self.Session.search([
            ('product_id', '=', self.red.id),
            ('state', 'in', ['photos_ready', 'preprocessing', 'processing', 'review', 'failed', 'saving']),
        ])
        self.assertFalse(active)

    def test_budget_blocks_revisions_too(self):
        session = self._session(self.red, state='review')
        gen = self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'pending', 'cost': 5.0})
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_ai_studio.monthly_budget', '1.0')
        with self.assertRaises(UserError):
            session._process_single_generation(gen)

    # ── Aylık bütçe ──────────────────────────────────────────────────
    def test_monthly_budget_blocks_new_processing(self):
        session = self._session(self.red)
        self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'done', 'cost': 5.0})
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('ugurlar_ai_studio.monthly_budget', '0')
        session._check_monthly_budget()  # limitsiz
        icp.set_param('ugurlar_ai_studio.monthly_budget', '1.0')
        with self.assertRaises(UserError):
            session._check_monthly_budget()

    # ── Alternatif aday seçimi ───────────────────────────────────────
    def test_select_candidate_swaps_images(self):
        session = self._session(self.red, state='review')
        first, second = _image_b64((200, 30, 40)), _image_b64((20, 40, 200))
        gen = self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'done',
                               'generated_image': first})
        cand = self.env['ai.studio.generation.candidate'].create({'generation_id': gen.id, 'image': second})
        cand.action_select()
        self.assertEqual(gen.generated_image, second)
        self.assertEqual(cand.image, first, 'önceki ana görsel aday olarak kalmalı (geri alınabilir)')
        with self.assertRaises(UserError):
            cand.with_user(self.operator).action_select()

    # ── Ürüne kaydetme: diğer rengin AI galerisi korunmalı ───────────
    def test_save_to_product_keeps_other_color_images(self):
        Image_ = self.env['product.image']
        blue_ai = Image_.create({
            'name': 'Arka Yüz - AI (1)',
            'product_tmpl_id': self.template.id,
            'product_variant_id': self.blue.id,
            'image_1920': _image_b64((20, 40, 200)),
        })
        session = self._session(self.red, state='review')
        front = self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'done',
                                 'is_approved': True, 'is_primary': True,
                                 'generated_image': _image_b64()})
        back = self.Gen.create({'session_id': session.id, 'photo_type': 'back', 'state': 'done',
                                'is_approved': True, 'generated_image': _image_b64()})
        session._save_to_product(front | back)
        self.assertTrue(blue_ai.exists(), 'mavi varyantın AI görseli silinmemeli')
        red_images = Image_.search([('product_variant_id', '=', self.red.id), ('name', 'like', '% - AI (%')])
        self.assertEqual(len(red_images), 1)

    # ── Sınıflandırma ────────────────────────────────────────────────
    def test_detect_garment_type_uses_name(self):
        session = self._session(self.red)
        self.template.name = 'Kemerli Elbise'
        self.assertEqual(session._detect_garment_type(), 'one_piece')

    # ── Cron: alan adları / domain'ler geçerli, boş veride hata yok ──
    # (cron girişi her kayıttan sonra commit eder; testler commit'siz çekirdeği çağırır)
    def test_cron_runs(self):
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_ai_studio.fal_api_key', '')
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_ai_studio.fashn_api_key', '')
        self.Session._check_stuck_generations()
        self.assertIsNone(self.Session._queue_claim_job(1, 'w1'), 'API anahtarı yokken kuyruk iş almamalı')

    def test_orphan_generation_is_requeued(self):
        session = self._session(self.red, state='processing')
        gen = self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'processing'})
        self.env.flush_all()  # bekleyen ORM yazımı write_date'i SQL'den sonra ezmesin
        self.env.cr.execute("UPDATE ai_studio_generation SET write_date = %s WHERE id = %s",
                            (fields.Datetime.now() - timedelta(minutes=5), gen.id))
        gen.invalidate_recordset()
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_ai_studio.fashn_api_key', '')
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_ai_studio.fal_api_key', '')
        self.Session._check_stuck_generations()
        self.assertEqual(gen.state, 'pending', 'gönderilmeden ölen iş tekrar kuyruğa alınmalı')
        self.assertEqual(gen.retry_count, 1)

    # ── Sırada bekleyen thread bitmiş işi yeniden çalıştırmaz (mükerrer ücret) ──
    def test_thread_skips_work_finished_while_waiting(self):
        session = self._session(self.red, state='review')
        gen = self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'done'})
        Session = type(self.Session)
        # İş kendi cursor'ını açar; test verisini görsün diye registry test modunda
        with self.enter_registry_test_mode(), patch.object(Session, '_create_provider') as create_provider:
            self.Session._retry_generation_thread_body(session.id, gen.id, 'key', self.env.uid)
            self.Session._process_ai_thread_body(session.id, 'key', self.env.uid)
        create_provider.assert_not_called()
        self.assertEqual(gen.state, 'done')
        self.assertEqual(session.state, 'review')

    def test_cron_waits_for_front_in_fal_queue(self):
        session = self._session(self.red, state='processing')
        self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'processing',
                         'fal_request_id': 'req-1', 'submitted_at': fields.Datetime.now()})
        self.Gen.create({'session_id': session.id, 'photo_type': 'back', 'state': 'pending'})
        found = self.Session.search([('id', '=', session.id)] + self.Session._queue_session_domain())
        self.assertFalse(found, 'ön yüz fal kuyruğundayken oturum yeniden başlatılmamalı')

    # ── Arka ofis iptal / tamamlama korumaları ──────────────────────
    def test_processing_revision_cannot_be_cancelled(self):
        session = self._session(self.red, state='review')
        parent = self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'done'})
        rev = self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'processing',
                               'parent_generation_id': parent.id})
        with self.assertRaises(UserError):
            rev.action_cancel_revision_record()
        with self.assertRaises(UserError):
            rev.action_batch_cancel()
        self.assertTrue(rev.exists())

    def test_mark_done_blocked_while_revision_pending(self):
        session = self._session(self.red, state='review')
        self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'done', 'is_approved': True})
        self.Gen.create({'session_id': session.id, 'photo_type': 'back', 'state': 'pending'})
        with self.assertRaises(UserError):
            session.action_mark_done()
        self.assertEqual(session.state, 'review')

    # ── Odoo 19: onaycı grubunu yönetici üzerinden devralanlar da bildirim alır ──
    def test_reviewer_users_include_implied_managers(self):
        manager = new_test_user(self.env, login='ais_manager',
                                groups='ugurlar_ai_studio.group_ai_studio_manager')
        self.assertIn(manager, self.Session._get_reviewer_users())
        self.assertNotIn(self.operator, self.Session._get_reviewer_users())

    # ── fal içerik denetimi: manken düzenleme promptu "kıyafet çıkarma" içermemeli ──
    def test_bare_leg_prompt_avoids_moderation_terms(self):
        prompt = type(self.env['ai.studio.model.preset']).BARE_LEGS_EDIT_PROMPT.lower()
        for word in ('remove', 'bare', 'trousers', 'naked', 'undress'):
            self.assertNotIn(word, prompt)

    # ── AI kullanım kaydı / net maliyet ──────────────────────────────
    def _usage_recorder(self):
        cr = self.env.cr

        class _Cursor:
            def execute(self, *args):
                return cr.execute(*args)

            def commit(self):
                pass

        class _Pool:
            @contextmanager
            def cursor(self):
                yield _Cursor()

        return _make_usage_recorder(_Pool(), self.env.uid, 0.30, 2.50)

    def test_usage_recorder_writes_row_with_token_cost(self):
        session = self._session(self.red)
        self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'done', 'cost': 0.03})
        self._usage_recorder()({
            'session_id': session.id, 'product_id': self.red.id, 'provider': 'gemini', 'step': 'quality_check',
            'model': 'gemini-2.5-flash', 'input_tokens': 5200, 'output_tokens': 500, 'image_count': 3,
            'duration': 4.2, 'status': 'ok', 'cost': None,
        })
        self.env.invalidate_all()
        usage = session.usage_ids
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage.product_id, self.red)
        self.assertAlmostEqual(usage.cost, 0.00281, places=6)
        self.assertEqual(session.gemini_call_count, 1)
        self.assertAlmostEqual(session.gemini_cost, 0.00281, places=6)
        self.assertAlmostEqual(session.net_cost, 0.03281, places=5)

    def test_deleted_generation_cost_stays_in_net_cost(self):
        session = self._session(self.red)
        gen = self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'done', 'cost': 5.0})
        gen.unlink()
        self.env.invalidate_all()
        kept = session.usage_ids
        self.assertEqual((kept.provider, kept.step), ('fal', 'deleted_generation'))
        self.assertAlmostEqual(kept.cost, 5.0)
        self.assertAlmostEqual(session.net_cost, 5.0)
        report = self.env['ai.studio.cost.report'].search([('session_id', '=', session.id)])
        self.assertAlmostEqual(sum(report.mapped('cost')), 5.0)

    def test_deleted_session_keeps_generation_cost(self):
        # Üretimler cascade ile silinir: oturum silinse de harcama raporda kalır
        session = self._session(self.red)
        self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'done', 'cost': 0.2})
        session.unlink()
        kept = self.env['ai.studio.usage'].search([('product_id', '=', self.red.id),
                                                   ('step', '=', 'deleted_generation')])
        self.assertAlmostEqual(sum(kept.mapped('cost')), 0.2)

    def test_month_cost_counts_usage_rows(self):
        before = self.Session._get_month_ai_cost()
        self.env['ai.studio.usage'].create({'provider': 'gemini', 'step': 'analysis', 'cost': 0.5})
        self.assertAlmostEqual(self.Session._get_month_ai_cost() - before, 0.5)

    # ── Doğruluk: yeniden deneme zinciri (aynı model → FASHN), işaretleme ──
    def _retry(self, scores, fallback=True):
        """scores: [ilk, 2. deneme, FASHN] kusur sayıları."""
        from ..models.ai_studio_session import _fidelity_retry
        calls = []

        def _attempt(label, cost):
            def fn(fix=''):
                calls.append((label, fix))
                return label.encode(), False, cost
            return fn

        def _check(b64, base_cost):
            return {'quality_details': 'qc', '_fidelity': scores[len(calls)], 'cost': base_cost}

        qc_vals = {'quality_details': 'qc', '_fidelity': scores[0], '_fix': 'The front is closed.', 'cost': 0.2}
        b64, vals = _fidelity_retry(self.env, None, b'FIRST', qc_vals, 0.2, _attempt('seedream', 0.135), _check,
                                    fallback=_attempt('fashn', 0.075) if fallback else None)
        return b64, vals, calls

    def test_fidelity_retry_falls_back_to_fashn(self):
        b64, vals, calls = self._retry([2, 2, 0])
        self.assertEqual([c[0] for c in calls], ['seedream', 'fashn'])
        self.assertEqual(calls[0][1], 'The front is closed.')
        self.assertEqual(b64, b'fashn')
        self.assertFalse(vals['fidelity_failed'])
        self.assertIn('FASHN seçildi', vals['quality_details'])
        self.assertAlmostEqual(vals['cost'], 0.2 + 0.135 + 0.075, places=4)

    def test_fidelity_retry_stops_when_second_attempt_is_clean(self):
        b64, vals, calls = self._retry([1, 0, 0])
        self.assertEqual([c[0] for c in calls], ['seedream'])
        self.assertEqual(b64, b'seedream')
        self.assertAlmostEqual(vals['cost'], 0.2 + 0.135, places=4)

    def test_fidelity_retry_flags_when_all_attempts_fail(self):
        b64, vals, calls = self._retry([1, 2, 3])
        self.assertEqual(b64, b'FIRST', 'en az kusurlu görsel tutulur')
        self.assertTrue(vals['fidelity_failed'])
        self.assertTrue(vals['quality_details'].startswith('⛔'))
        self.assertNotIn('generated_image', vals)

    def test_fidelity_retry_respects_fashn_setting(self):
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_ai_studio.fashn_fallback', 'False')
        _b64, vals, calls = self._retry([2, 2, 0])
        self.assertEqual([c[0] for c in calls], ['seedream'])
        self.assertTrue(vals['fidelity_failed'])

    def test_fashn_fallback_only_for_seedream_front_back(self):
        from ..models.ai_studio_session import _make_regenerators
        kw = {'model_name': 'seedream/v5/pro/edit', 'prompt': 'p'}
        noop = lambda *a: None  # noqa: E731
        self.assertIsNotNone(_make_regenerators(None, kw, noop, noop, 'fal', 'front')[1])
        self.assertIsNone(_make_regenerators(None, kw, noop, noop, 'fal', 'side')[1])
        self.assertIsNone(_make_regenerators(None, kw, noop, noop, 'fashn', 'front')[1])
        self.assertIsNone(_make_regenerators(None, dict(kw, model_name='fashn/tryon/v1.6'),
                                             noop, noop, 'fal', 'front')[1])

    def test_regenerate_cost_excludes_prep(self):
        # Hazırlık maliyeti ilk denemede bir kez sayılır; yeniden üretim yalnız kendi ücretini döndürür
        from ..models.ai_studio_session import _make_regenerators

        class _Provider:
            def __init__(self):
                self.kwargs = []

            def virtual_tryon(self, **kw):
                self.kwargs.append(kw)
                return {'cost': 0.135}

        provider = _Provider()
        regen, fallback = _make_regenerators(
            provider, {'model_name': 'seedream/v5/pro/edit', 'prompt': 'p'},
            lambda res: (b'IMG', None), lambda: None, 'fal', 'front')
        self.assertEqual(regen('Fix.')[2], 0.135)
        self.assertIn('Fix.', provider.kwargs[-1]['prompt'])
        fallback('Fix.')
        self.assertEqual(provider.kwargs[-1]['model_name'], 'fashn/tryon/v1.6')
        self.assertEqual(provider.kwargs[-1]['prompt'], '')

    # ── AI kuyruğu: iş HTTP worker'ında thread değil, cron slotlarında ──
    def _queue_env(self, limit='2'):
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('ugurlar_ai_studio.default_provider', 'fal')
        icp.set_param('ugurlar_ai_studio.fal_api_key', 'test-key')
        icp.set_param('ugurlar_ai_studio.monthly_budget', '0')
        icp.set_param('ugurlar_ai_studio.concurrent_limit', limit)

    def _queue_triggers(self):
        crons = self.env['ir.cron'].browse([self.env.ref(x).id for x in AI_QUEUE_CRONS])
        return self.env['ir.cron.trigger'].sudo().search_count([('cron_id', 'in', crons.ids)])

    def _preset(self, **vals):
        return self.env['ai.studio.model.preset'].create(dict({
            'name': 'Kuyruk Manken', 'garment_type': 'tops', 'model_image_front': _image_b64(),
        }, **vals))

    def test_queue_crons_exist(self):
        self.assertEqual(len(AI_QUEUE_CRONS), 2)
        for xmlid in AI_QUEUE_CRONS:
            cron = self.env.ref(xmlid)
            self.assertTrue(cron.active, xmlid)
            self.assertIn('_cron_process_queue', cron.code)

    def test_start_processing_enqueues_without_thread(self):
        self._queue_env()
        session = self._session(self.red, model_preset_id=self._preset().id)
        self.env['ai.studio.photo'].create({
            'session_id': session.id, 'photo_type': 'front', 'image_original': _image_b64()})
        before = self._queue_triggers()
        with patch('threading.Thread.start') as start:
            session.action_start_processing()
        start.assert_not_called()
        self.assertEqual(session.state, 'preprocessing')
        self.assertEqual(set(session.generation_ids.mapped('state')), {'pending'})
        self.assertGreater(self._queue_triggers(), before, 'kuyruk cron\'u tetiklenmeli')
        self.assertEqual(self.Session._queue_claim_job(1, 'w1'), ('session', session.id, False))
        session.invalidate_recordset(['ai_lease_until'])
        self.assertTrue(session.ai_lease_until, 'iş alınırken kira yazılmalı')

    def test_retry_paths_enqueue_without_thread(self):
        self._queue_env()
        preset = self._preset()
        with patch('threading.Thread.start') as start:
            # Kaldığı yerden devam
            failed = self._session(self.red, state='failed', model_preset_id=preset.id)
            gen = self.Gen.create({'session_id': failed.id, 'photo_type': 'front', 'state': 'failed'})
            before = self._queue_triggers()
            failed.action_retry_failed()
            self.assertEqual(gen.state, 'pending')
            self.assertGreater(self._queue_triggers(), before)
            # Toplu revizyon tekrar deneme
            review = self._session(self.blue, state='review')
            parent = self.Gen.create({'session_id': review.id, 'photo_type': 'front', 'state': 'done'})
            rev = self.Gen.create({'session_id': review.id, 'photo_type': 'front', 'state': 'failed',
                                   'parent_generation_id': parent.id})
            before = self._queue_triggers()
            rev.action_batch_retry()
            self.assertEqual(rev.state, 'pending')
            self.assertGreater(self._queue_triggers(), before)
            # Tek üretim (revizyon / Tekrar Dene)
            before = self._queue_triggers()
            review._process_single_generation(rev)
            self.assertGreater(self._queue_triggers(), before)
            # Takılmış revizyonları kurtar: senkron cron yerine kuyruk
            before = self._queue_triggers()
            rev.action_recover_stuck_revisions_server()
            self.assertGreater(self._queue_triggers(), before)
            # Toplu yeniden işleme
            self.env['ai.studio.photo'].create({
                'session_id': failed.id, 'photo_type': 'front', 'image_original': _image_b64()})
            failed.state = 'failed'
            before = self._queue_triggers()
            failed.action_batch_reprocess()
            self.assertEqual(failed.state, 'preprocessing')
            self.assertGreater(self._queue_triggers(), before)
        start.assert_not_called()
        with self.assertRaises(UserError):
            self._session(self.red, state='done')._process_single_generation(gen)

    def test_queue_slot_respects_concurrent_limit(self):
        self._queue_env(limit='1')
        session = self._session(self.red, state='processing')
        self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'pending'})
        self.assertIsNone(self.Session._queue_claim_job(2, 'w2'), 'limit 1 iken ikinci slot iş almamalı')
        self.assertEqual(self.Session._queue_claim_job(1, 'w1'), ('session', session.id, False))

    def test_queue_skips_leased_session(self):
        self._queue_env()
        session = self._session(self.red, state='processing')
        self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'pending'})
        self.assertTrue(_try_acquire_lease(self.env.cr, session.id, 'baska-worker'))
        self.assertIsNone(self.Session._queue_claim_job(1, 'w1'), 'canlı kiralı oturum ikinci kez alınmamalı')

    def test_queue_respects_budget(self):
        self._queue_env()
        session = self._session(self.red, state='processing')
        self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'pending', 'cost': 5.0})
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_ai_studio.monthly_budget', '1.0')
        self.assertIsNone(self.Session._queue_claim_job(1, 'w1'), 'bütçe doluyken ücretli iş başlamamalı')

    def test_queue_processes_review_revision(self):
        self._queue_env()
        session = self._session(self.red, state='review')
        gen = self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'pending'})
        self.assertEqual(self.Session._queue_claim_job(1, 'w1'), ('revision', session.id, gen.id))
        self.assertIsNone(self.Session._queue_claim_job(2, 'w2'), 'aynı oturum iki slotta işlenmemeli')

    def test_mannequin_generation_is_queued_not_threaded(self):
        self._queue_env()
        preset = self._preset(mannequin_prompt='Genç kadın manken')
        before = self._queue_triggers()
        with patch('threading.Thread.start') as start:
            preset.action_generate_mannequin()
        start.assert_not_called()
        self.assertEqual(preset.mannequin_generation_state, 'queued')
        self.assertGreater(self._queue_triggers(), before)
        with self.assertRaises(UserError):
            preset.action_generate_mannequin()
        self.assertEqual(self.Session._queue_claim_job(1, 'w1'), ('mannequin', preset.id, False))
        self.assertEqual(preset.mannequin_generation_state, 'generating')
        self.assertFalse(self.env['ai.studio.model.preset']._queue_claim_mannequin(),
                         'aynı preset iki slotta üretilmemeli')

    def test_stuck_mannequin_marked_failed(self):
        preset = self._preset(mannequin_generation_state='generating')
        self.env.cr.execute("UPDATE ai_studio_model_preset SET write_date = %s WHERE id = %s",
                            (fields.Datetime.now() - timedelta(hours=2), preset.id))
        preset.invalidate_recordset()
        self.Session._check_stuck_generations()
        self.assertEqual(preset.mannequin_generation_state, 'failed')

    def test_stuck_cron_isolates_broken_record(self):
        broken = self._session(self.red, state='processing')
        ok = self._session(self.blue, state='processing')
        self.Gen.create({'session_id': ok.id, 'photo_type': 'front', 'state': 'done'})
        Session = type(self.Session)
        original = Session._finalize_idle_session_state

        def _finalize(rec):
            if rec == broken:
                raise ValueError('bozuk kayıt')
            return original(rec)

        with patch.object(Session, '_finalize_idle_session_state', autospec=True, side_effect=_finalize), \
                self.assertLogs('odoo.addons.ugurlar_ai_studio.models.ai_studio_session', 'ERROR') as logs:
            self.Session._check_stuck_generations()
        self.assertEqual(ok.state, 'review', 'bozuk kayıt diğer oturumların ilerlemesini durdurmamalı')
        self.assertEqual(broken.state, 'processing')
        self.assertTrue(any('oturumu sonlandırma' in line for line in logs.output))

    def test_lease_renewed_during_prep(self):
        # Hazırlık (analiz, etiket silme, görünüm yapısı) kira süresini aşabilir: her adımda yenilenir
        self._queue_env()
        session = self._session(self.red, state='review', model_preset_id=self._preset().id)
        gen = self.Gen.create({'session_id': session.id, 'photo_type': 'back', 'state': 'pending',
                               'original_image': _image_b64()})
        Session = type(self.Session)
        mod = 'odoo.addons.ugurlar_ai_studio.models.ai_studio_session'
        with self.enter_registry_test_mode(), \
                patch.object(Session, '_create_provider'), \
                patch('odoo.addons.ugurlar_ai_studio.services.garment_analyzer.analyze_garment', return_value={}), \
                patch.object(Session, '_prepare_garment_for_tryon',
                             return_value=('url', _image_b64().decode(), 0.0)), \
                patch.object(Session, '_garment_view_info', side_effect=RuntimeError('dur')), \
                patch(mod + '._renew_session_lease') as renew, \
                self.assertLogs(mod, 'ERROR') as logs:
            self.Session._retry_generation_thread_body(session.id, gen.id, 'key', self.env.uid, lease_owner='w1')
        # işleme başında 1 + analiz sonrası + etiket silme sonrası
        self.assertGreaterEqual(renew.call_count, 3, logs.output)

    def test_qty_available_not_stored(self):
        # Stok her okumada değişir; stored kopya bayatlıyordu (kolon DB'de kalır, yazılmaz)
        self.assertFalse(self.Session._fields['qty_available'].store)
