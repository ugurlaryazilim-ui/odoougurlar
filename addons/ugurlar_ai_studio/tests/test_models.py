"""Model / veritabanı testleri: kira, yetki, renk kapsamlı kaydetme, cron."""
import base64
import io
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from unittest.mock import patch

from ..models.ai_studio_session import _get_extra_prompt_en, _needs_bare_legs, _try_acquire_lease

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
    def test_cron_runs(self):
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_ai_studio.fal_api_key', '')
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_ai_studio.fashn_api_key', '')
        self.Session._cron_check_stuck_generations()

    def test_orphan_generation_is_requeued(self):
        session = self._session(self.red, state='processing')
        gen = self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'processing'})
        self.env.cr.execute("UPDATE ai_studio_generation SET write_date = %s WHERE id = %s",
                            (fields.Datetime.now() - timedelta(minutes=5), gen.id))
        gen.invalidate_recordset()
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_ai_studio.fashn_api_key', '')
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_ai_studio.fal_api_key', '')
        self.Session._cron_check_stuck_generations()
        self.assertEqual(gen.state, 'pending', 'gönderilmeden ölen iş tekrar kuyruğa alınmalı')
        self.assertEqual(gen.retry_count, 1)

    # ── Sırada bekleyen thread bitmiş işi yeniden çalıştırmaz (mükerrer ücret) ──
    def test_thread_skips_work_finished_while_waiting(self):
        session = self._session(self.red, state='review')
        gen = self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'done'})
        Session = type(self.Session)
        with patch.object(Session, '_create_provider') as create_provider:
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
        found = self.Session.search([
            ('id', '=', session.id),
            ('generation_ids', 'not any', [
                ('photo_type', '=', 'front'), ('state', '=', 'processing'), ('fal_request_id', '!=', False),
            ]),
        ])
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
