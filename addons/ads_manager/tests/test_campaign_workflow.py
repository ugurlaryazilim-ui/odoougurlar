# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError

@tagged('post_install', '-at_install', 'ads_manager')
class TestCampaignWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.account = cls.env['ads.account'].create({
            'name': 'Test Google Account',
            'platform': 'google',
            'platform_account_id': '123-456-7890',
            'state': 'connected',
            'google_client_id': 'fake_client_id',
            'google_client_secret': 'fake_secret',
            'google_developer_token': 'fake_dev_token',
        })

    def test_01_campaign_approval_lifecycle(self):
        """Test full campaign approval lifecycle: draft -> pending -> approved -> published."""
        campaign = self.env['ads.campaign'].create({
            'name': 'Black Friday Campaign',
            'account_id': self.account.id,
            'objective': 'sales',
            'daily_budget': 250.0,
            'is_local': True,
        })

        self.assertEqual(campaign.approval_status, 'draft')

        # 1. Submit for approval
        campaign.action_submit_for_approval()
        self.assertEqual(campaign.approval_status, 'pending')

        # 2. Cannot submit again when pending
        with self.assertRaises(UserError):
            campaign.action_submit_for_approval()

        # 3. Manager approves
        campaign.action_approve()
        self.assertEqual(campaign.approval_status, 'approved')
        self.assertEqual(campaign.approved_by, self.env.user)
        self.assertTrue(campaign.approved_date)

        # 4. Reset to draft test
        campaign.action_reset_to_draft()
        self.assertEqual(campaign.approval_status, 'draft')
        self.assertFalse(campaign.approved_by)

    def test_02_campaign_rejection(self):
        """Test campaign rejection with wizard."""
        campaign = self.env['ads.campaign'].create({
            'name': 'Invalid Budget Campaign',
            'account_id': self.account.id,
            'objective': 'traffic',
            'daily_budget': 50.0,
            'is_local': True,
        })
        campaign.action_submit_for_approval()

        # Rejection wizard action
        wiz = self.env['ads.campaign.reject.wizard'].create({
            'campaign_id': campaign.id,
            'rejection_reason': 'Bütçe stratejisi yetersiz, hedef kitle revize edilmeli.',
        })
        wiz.action_reject()

        self.assertEqual(campaign.approval_status, 'rejected')
        self.assertIn('Bütçe stratejisi', campaign.rejection_reason)

    def test_03_budget_wizard_validation(self):
        """Test budget adjustment wizard validations."""
        campaign = self.env['ads.campaign'].create({
            'name': 'Budget Adjustment Target',
            'account_id': self.account.id,
            'objective': 'leads',
            'daily_budget': 100.0,
        })

        # Negative budget must raise UserError
        wiz = self.env['ads.budget.wizard'].create({
            'campaign_id': campaign.id,
            'new_budget': -20.0,
            'apply_to_platform': False,
        })
        with self.assertRaises(UserError):
            wiz.action_apply()

        # Valid adjustment without platform call
        wiz.write({'new_budget': 150.0})
        wiz.action_apply()
        self.assertEqual(campaign.daily_budget, 150.0)
