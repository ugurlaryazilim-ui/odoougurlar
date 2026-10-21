"""A4 güvenlik: onay kapısı create sonrası denetlenir (Y1); onaylanan oturum içeriği kilitli (O1);
kaydetme sorunlarında onaycıya bildirim (Ö-2) ve ham hata metni yok (D1)."""
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'ugurlar_ai_studio')
class TestApprovalGate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.lang']._activate_lang('tr_TR')
        cls.product = cls.env['product.product'].create({'name': 'A4 Elbise'})
        cls.other_product = cls.env['product.product'].create({'name': 'A4 Pantolon'})
        cls.Session = cls.env['ai.studio.session']
        cls.Gen = cls.env['ai.studio.generation']
        cls.reviewer = new_test_user(cls.env, login='ais_rev_a4',
                                     groups='ugurlar_ai_studio.group_ai_studio_reviewer')
        cls.operator = new_test_user(cls.env, login='ais_op_a4',
                                     groups='ugurlar_ai_studio.group_ai_studio_operator')

    def setUp(self):
        super().setUp()
        self.startPatcher(patch.object(type(self.env.cr), 'commit', lambda cr: None))

    def _session(self, state='review', **extra):
        # NEDEN: operatör kaydı okuyup yazabilmeli (user_id = operatör); yoksa kayıt kuralı AccessError'ı
        # denetimi maskeler ve test mutasyonda yeşil kalır.
        session = self.Session.create(dict({'product_id': self.product.id, 'state': state,
                                            'user_id': self.operator.id}, **extra))
        self.Gen.create({'session_id': session.id, 'photo_type': 'front', 'state': 'done',
                         'is_approved': True, 'is_primary': True})
        return session

    # --- Y1 ---
    def test_default_state_context_cannot_bypass(self):
        op = self.Session.with_user(self.operator).with_context(default_state='saving')
        with self.assertRaises(AccessError):
            op.create({'product_id': self.product.id})

    def test_default_reviewer_context_cannot_bypass(self):
        op = self.Session.with_user(self.operator).with_context(default_reviewer_id=self.reviewer.id)
        with self.assertRaises(AccessError):
            op.create({'product_id': self.product.id})

    def test_operator_cannot_write_or_create_with_reviewer_id(self):
        session = self._session()
        self.assertTrue(session.with_user(self.operator).read(['state']))
        with self.assertRaises(AccessError):
            session.with_user(self.operator).write({'reviewer_id': self.reviewer.id})
        with self.assertRaises(AccessError):
            self.Session.with_user(self.operator).create(
                {'product_id': self.product.id, 'reviewer_id': self.reviewer.id})

    def test_operator_plain_create_and_write_still_work(self):
        op = self.Session.with_user(self.operator)
        session = op.create({'product_id': self.product.id})
        self.assertEqual(session.state, 'draft')
        session.write({'product_id': self.other_product.id})
        self.assertEqual(session.product_id, self.other_product)

    def test_reviewer_can_set_reviewer_and_saving(self):
        session = self._session()
        session.with_user(self.reviewer).write({'reviewer_id': self.reviewer.id, 'state': 'saving'})
        self.assertEqual(session.state, 'saving')
        rec = self.Session.with_user(self.reviewer).with_context(default_state='saving').create(
            {'product_id': self.product.id})
        self.assertEqual(rec.state, 'saving')

    # --- O1 ---
    def test_operator_cannot_change_content_when_saving_or_done(self):
        for state in ('saving', 'done'):
            session = self._session(state=state, reviewer_id=self.reviewer.id)
            gen = session.generation_ids[0]
            line = self.env['ai.studio.set.line'].create(
                {'session_id': session.id, 'product_id': self.product.id})
            op_session, op_gen, op_line = (session.with_user(self.operator), gen.with_user(self.operator),
                                           line.with_user(self.operator))
            self.assertTrue(op_gen.read(['state']))
            with self.assertRaises(AccessError):
                op_session.write({'product_id': self.other_product.id})
            with self.assertRaises(AccessError):
                op_session.write({'apply_to_siblings': True})
            with self.assertRaises(AccessError):
                op_gen.write({'generated_image': False})
            with self.assertRaises(AccessError):
                op_gen.write({'is_approved': False})
            with self.assertRaises(AccessError):
                self.Gen.with_user(self.operator).create({'session_id': session.id, 'photo_type': 'back'})
            with self.assertRaises(AccessError):
                op_line.write({'product_id': self.other_product.id})
            with self.assertRaises(AccessError):
                self.env['ai.studio.set.line'].with_user(self.operator).create(
                    {'session_id': session.id, 'product_id': self.other_product.id})
            self.assertEqual(session.product_id, self.product)

    def test_operator_cannot_write_any_other_field_when_saving(self):
        # izin listesi dışındaki HER alan kilitli (kara liste değil): kısmen sayılmayan alanlar da
        session = self._session(state='saving', reviewer_id=self.reviewer.id)
        gen = session.generation_ids[0]
        for rec, vals in ((session, {'category': 'tops'}), (session, {'extra_prompt': 'x'}),
                          (session, {'session_type': 'set'}),
                          (gen, {'state': 'pending'}), (gen, {'revision_number': 9}),
                          (gen, {'generation_mode': 'set_combo'}), (gen, {'error_message': 'x'})):
            with self.assertRaises(AccessError, msg=str(vals)):
                rec.with_user(self.operator).write(vals)
        # kısa izin listesi açık
        gen.with_user(self.operator).write({'is_exported_to_local': True})
        session.with_user(self.operator).write({'state': 'review'})

    def test_operator_cannot_move_rows_into_or_out_of_locked_session(self):
        locked = self._session(state='saving', reviewer_id=self.reviewer.id)
        open_session = self._session()
        open_gen = open_session.generation_ids[0]
        open_line = self.env['ai.studio.set.line'].create(
            {'session_id': open_session.id, 'product_id': self.product.id})
        # açık oturumdan kilitli oturuma taşıma (hedef kilit)
        with self.assertRaises(AccessError):
            open_gen.with_user(self.operator).write({'session_id': locked.id})
        with self.assertRaises(AccessError):
            open_line.with_user(self.operator).write({'session_id': locked.id})
        # kilitli oturumdan dışarı taşıma (mevcut kilit)
        locked_gen = locked.generation_ids[0]
        with self.assertRaises(AccessError):
            locked_gen.with_user(self.operator).write({'session_id': open_session.id})
        # o2m komutuyla ekleme/bağlama
        with self.assertRaises(AccessError):
            locked.with_user(self.operator).write({'generation_ids': [(4, open_gen.id)]})
        self.assertEqual(open_gen.session_id, open_session)
        self.assertEqual(open_line.session_id, open_session)
        # onaycı taşıyabilir
        open_line.with_user(self.reviewer).write({'session_id': locked.id})
        self.assertEqual(open_line.session_id, locked)

    def test_operator_can_still_edit_in_review(self):
        session = self._session()
        session.with_user(self.operator).write({'product_id': self.other_product.id})
        session.generation_ids.with_user(self.operator).write({'is_excluded': True})
        self.assertEqual(session.product_id, self.other_product)

    def test_reviewer_flow_complete_to_done_green(self):
        session = self._session(state='saving', reviewer_id=self.reviewer.id)
        session.with_user(self.reviewer).write({'apply_to_siblings': True})   # onaycı kilide takılmaz
        with patch.object(type(self.Session), '_save_to_product') as save:
            self.Session._run_save_job(session.id)
        save.assert_called_once()
        self.assertEqual(session.state, 'done')

    # --- Ö-2 / D1 ---
    def test_pending_generation_rejection_names_right_reason_and_notifies_reviewer(self):
        session = self._session(state='saving', reviewer_id=self.reviewer.id)
        self.Gen.create({'session_id': session.id, 'photo_type': 'back', 'state': 'pending'})
        self.Session._run_save_job(session.id)
        self.assertEqual(session.state, 'review')
        msg = session.message_ids[0]
        self.assertIn('işlenen üretim', msg.body)
        self.assertNotIn('onaycı tarafından tamamlanmamış', msg.body)
        self.assertIn(self.reviewer.partner_id, msg.partner_ids)

    def test_unapproved_rejection_keeps_old_reason(self):
        session = self._session()
        session.sudo().write({'state': 'saving'})
        self.Session._run_save_job(session.id)
        self.assertIn('onaycı tarafından tamamlanmamış', session.message_ids[0].body)

    def test_save_failure_notifies_reviewer_and_hides_raw_error(self):
        session = self._session(state='saving', reviewer_id=self.reviewer.id)
        with patch.object(type(self.Session), '_save_to_product', side_effect=RuntimeError('psycopg2 /var/lib/x')):
            self.Session._run_save_job(session.id)
        msg = session.message_ids[0]
        self.assertNotIn('psycopg2', msg.body)
        self.assertIn(self.reviewer.partner_id, msg.partner_ids)

    def test_save_failure_user_error_text_is_shown(self):
        session = self._session(state='saving', reviewer_id=self.reviewer.id)
        with patch.object(type(self.Session), '_save_to_product', side_effect=UserError('Ürün arşivli')):
            self.Session._run_save_job(session.id)
        self.assertIn('Ürün arşivli', session.message_ids[0].body)
