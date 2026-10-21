"""J6 / TODO-29: complete_session ağır kısmı kuyrukta; Görselsiz Ürünler önbellek süresi."""
import base64
import io
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError
from odoo.sql_db import db_connect
from odoo.tests import TransactionCase, new_test_user, tagged

from ..controllers.ai_studio_controller import AiStudioController
from ..models import ai_studio_imageless as imageless_module

CTRL = 'odoo.addons.ugurlar_ai_studio.controllers.ai_studio_controller'

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


def _image_b64():
    buf = io.BytesIO()
    Image.new('RGB', (64, 96), (200, 30, 40)).save(buf, 'JPEG')
    return base64.b64encode(buf.getvalue())


@tagged('post_install', '-at_install', 'ugurlar_ai_studio')
class TestCompleteSessionQueued(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.lang']._activate_lang('tr_TR')
        cls.product = cls.env['product.product'].create({'name': 'J6 Elbise'})
        cls.Session = cls.env['ai.studio.session']
        cls.Gen = cls.env['ai.studio.generation']
        cls.reviewer = new_test_user(cls.env, login='ais_reviewer_j6',
                                     groups='ugurlar_ai_studio.group_ai_studio_reviewer')

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_ai_studio.fal_api_key', '')
        self.env['ir.config_parameter'].sudo().set_param('ugurlar_ai_studio.fashn_api_key', '')
        # TransactionCase'te commit yapılamaz
        self.startPatcher(patch.object(type(self.env.cr), 'commit', lambda cr: None))

    def _review_session(self):
        # J10 D-J10-3: complete_session onaycının açık inceleme ekranının jetonunu ister
        session = self.Session.create({'product_id': self.product.id, 'state': 'review',
                                       'review_locked_by': self.reviewer.id, 'review_lock_token': 'j6',
                                       'review_lock_time': fields.Datetime.now()})
        self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'done',
                         'is_approved': True, 'is_primary': True, 'generated_image': _image_b64()})
        return session

    def test_complete_session_only_marks_saving_and_triggers_queue(self):
        session = self._review_session()
        cron = self.env.ref('ugurlar_ai_studio.cron_ai_queue_1')
        before = self.env['ir.cron.trigger'].search_count([('cron_id', '=', cron.id)])
        env = self.env(user=self.reviewer)
        with patch(CTRL + '.request', SimpleNamespace(env=env)), \
                patch.object(type(self.Session), '_save_to_product') as save:
            res = AiStudioController().complete_session(session.id, lock_token='j6')
        self.assertEqual(res, {'success': True, 'saving': True})
        save.assert_not_called()   # ağır iş istekte yapılmaz
        self.assertEqual(session.state, 'saving')
        self.assertEqual(session.reviewer_id, self.reviewer)
        self.assertEqual(self.env['ir.cron.trigger'].search_count([('cron_id', '=', cron.id)]), before + 1)

    def test_claim_prefers_saving_job_even_without_api_key(self):
        session = self._review_session()
        session.write({'state': 'saving', 'reviewer_id': self.reviewer.id})
        self.assertEqual(self.Session._queue_claim_job(1, 'w1'), ('save', session.id, False))
        self.assertIsNone(self.Session._queue_claim_job(2, 'w2'), 'kiralı oturum ikinci slota verilmemeli')

    def test_save_job_writes_product_and_finishes_session(self):
        session = self._review_session()
        session.write({'state': 'saving', 'reviewer_id': self.reviewer.id})
        self.Session._run_save_job(session.id)
        self.assertEqual(session.state, 'done')
        self.assertTrue(session.date_done)
        self.assertTrue(self.product.product_tmpl_id.image_1920)

    def test_save_job_failure_returns_session_to_review_with_message(self):
        session = self._review_session()
        session.write({'state': 'saving', 'reviewer_id': self.reviewer.id})
        with patch.object(type(self.Session), '_save_to_product', side_effect=ValueError('disk dolu')):
            self.Session._run_save_job(session.id)
        self.assertEqual(session.state, 'review', "başarısız kayıt 'saving'de takılı kalıp kuyruğu döndürmemeli")
        # A4 D1: beklenmeyen hatanın ham metni chatter'a girmez (ayrıntı log'da)
        self.assertNotIn('disk dolu', session.message_ids[0].body)
        self.assertIn('Tamamla', session.message_ids[0].body)
        self.assertFalse(self.Session.search_count(self.Session._queue_saving_domain()))

    # --- J9: 'saving' yalnız onay yolundan ---
    def test_operator_cannot_write_saving(self):
        operator = new_test_user(self.env, login='ais_operator_j9',
                                 groups='ugurlar_ai_studio.group_ai_studio_operator')
        session = self._review_session()
        session.user_id = operator
        op_session = session.with_user(operator)
        # NEDEN: operatör kaydı okuyup yazabiliyor olmalı; yoksa kayıt kuralının AccessError'ı denetimi maskeler
        self.assertEqual(op_session.read(['state'])[0]['state'], 'review')
        with self.assertRaises(AccessError):
            op_session.write({'state': 'saving'})
        with self.assertRaises(AccessError):
            self.Session.with_user(operator).create({'product_id': self.product.id, 'state': 'saving'})
        self.assertEqual(session.state, 'review')

    def test_reviewer_complete_session_then_queue_saves(self):
        session = self._review_session()
        env = self.env(user=self.reviewer)
        with patch(CTRL + '.request', SimpleNamespace(env=env)):
            self.assertTrue(AiStudioController().complete_session(session.id, lock_token='j6')['success'])
        self.assertEqual(session.state, 'saving')
        self.assertEqual(self.Session._queue_claim_job(1, 'w1'), ('save', session.id, False))
        self.Session._run_save_job(session.id)
        self.assertEqual(session.state, 'done')
        self.assertTrue(self.product.product_tmpl_id.image_1920)

    def test_save_job_rejects_unapproved_forced_saving(self):
        session = self._review_session()
        session.sudo().write({'state': 'saving'})   # onay yolundan geçmemiş (reviewer_id yok)
        with patch.object(type(self.Session), '_save_to_product') as save:
            self.Session._run_save_job(session.id)
        save.assert_not_called()
        self.assertEqual(session.state, 'review')
        self.assertFalse(self.product.product_tmpl_id.image_1920)

    def test_save_job_rejects_non_reviewer_reviewer_id(self):
        operator = new_test_user(self.env, login='ais_operator_j9b',
                                 groups='ugurlar_ai_studio.group_ai_studio_operator')
        session = self._review_session()
        session.sudo().write({'state': 'saving', 'reviewer_id': operator.id})
        with patch.object(type(self.Session), '_save_to_product') as save:
            self.Session._run_save_job(session.id)
        save.assert_not_called()
        self.assertEqual(session.state, 'review')


@tagged('post_install', '-at_install', 'ugurlar_ai_studio')
class TestImagelessCache(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Line = self.env['ai.studio.imageless.line']
        self.icp = self.env['ir.config_parameter'].sudo()

    def test_fresh_list_is_not_recomputed_on_menu_open(self):
        self.icp.set_param(imageless_module.IMAGELESS_REFRESHED_PARAM, fields.Datetime.to_string(fields.Datetime.now()))
        with patch.object(type(self.Line), '_refresh_lines') as calc:
            res = self.Line.action_refresh_cached()
        calc.assert_not_called()
        self.assertEqual(res['tag'], 'reload')

    def test_stale_list_is_recomputed_and_stamped(self):
        old = fields.Datetime.now() - timedelta(minutes=imageless_module.IMAGELESS_CACHE_MINUTES + 1)
        self.icp.set_param(imageless_module.IMAGELESS_REFRESHED_PARAM, fields.Datetime.to_string(old))
        with patch.object(type(self.Line), '_refresh_lines', return_value={'tag': 'reload'}) as calc:
            self.Line.action_refresh_cached()
        calc.assert_called_once()
        stamp = fields.Datetime.to_datetime(self.icp.get_param(imageless_module.IMAGELESS_REFRESHED_PARAM))
        self.assertGreater(stamp, old)

    def test_refresh_button_forces_even_when_fresh(self):
        self.icp.set_param(imageless_module.IMAGELESS_REFRESHED_PARAM, fields.Datetime.to_string(fields.Datetime.now()))
        with patch.object(type(self.Line), '_refresh_lines', return_value={'tag': 'reload'}) as calc:
            self.Line.action_refresh()
        calc.assert_called_once()

    def test_concurrent_refresh_is_skipped(self):
        # başka bağlantı kilidi tutarken ikinci yenileme beklemez, hesaplamaz
        with db_connect(self.env.cr.dbname).cursor() as other:
            other.execute("SELECT pg_advisory_lock(%s)", (imageless_module.IMAGELESS_LOCK_KEY,))
            try:
                with patch.object(type(self.Line), '_refresh_lines') as calc:
                    res = self.Line.action_refresh()
                calc.assert_not_called()
                self.assertEqual(res['tag'], 'reload')
            finally:
                other.execute("SELECT pg_advisory_unlock(%s)", (imageless_module.IMAGELESS_LOCK_KEY,))
