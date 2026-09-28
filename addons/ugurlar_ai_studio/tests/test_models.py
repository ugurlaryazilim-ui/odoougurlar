"""Model / veritabanı testleri: kira, yetki, renk kapsamlı kaydetme, cron."""
import base64
import io
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..models.ai_studio_session import _try_acquire_lease

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
