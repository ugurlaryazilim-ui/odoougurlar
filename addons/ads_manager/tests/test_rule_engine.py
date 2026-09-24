# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError
from ..services.rule_engine import RuleEngine
from ..services.budget_pacer import BudgetPacer

@tagged('post_install', '-at_install', 'ads_manager')
class TestAdsRuleEngine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.account = cls.env['ads.account'].create({
            'name': 'Test Meta Account',
            'platform': 'meta',
            'platform_account_id': 'act_123456789',
            'state': 'connected',
            'access_token': 'fake_token',
        })

        cls.campaign = cls.env['ads.campaign'].create({
            'name': 'Summer Sale Promo',
            'account_id': cls.account.id,
            'platform_campaign_id': 'camp_101',
            'status': 'active',
            'daily_budget': 100.0,
        })

        # Create daily metrics for past 3 days
        today = date.today()
        cls.env['ads.metric.daily'].create([
            {
                'account_id': cls.account.id,
                'campaign_id': cls.campaign.id,
                'date': today - timedelta(days=2),
                'spend': 120.0,
                'impressions': 10000,
                'clicks': 200,
                'conversions': 2.0,
                'conversion_value': 80.0,
            },
            {
                'account_id': cls.account.id,
                'campaign_id': cls.campaign.id,
                'date': today - timedelta(days=1),
                'spend': 150.0,
                'impressions': 12000,
                'clicks': 180,
                'conversions': 1.0,
                'conversion_value': 40.0,
            },
            {
                'account_id': cls.account.id,
                'campaign_id': cls.campaign.id,
                'date': today,
                'spend': 180.0,
                'impressions': 15000,
                'clicks': 150,
                'conversions': 1.0,
                'conversion_value': 30.0,
            },
        ])

    def test_01_budget_pacer(self):
        """Test BudgetPacer calculation for active campaign."""
        pacer = BudgetPacer(self.env)
        pacing = pacer.calculate_pacing(self.campaign)
        self.assertIn('pacing_pct', pacing)
        self.assertIn('status', pacing)
        self.assertEqual(pacing['budget_type'], 'daily')
        self.assertGreater(pacing['spent_today'], 0)

    def test_02_rule_evaluation_condition_met(self):
        """Test rule triggered when ROAS drops below threshold."""
        rule = self.env['ads.rule'].create({
            'name': 'Low ROAS Alert',
            'severity': 'critical',
            'category': 'performance',
            'platform_filter': 'all',
            'condition_logic': 'all',
            'min_impressions': 500,
            'cooldown_hours': 24,
        })

        # Condition: ROAS < 1.0
        self.env['ads.rule.condition'].create({
            'rule_id': rule.id,
            'metric': 'roas',
            'operator': 'lt',
            'threshold': 1.0,
            'lookback_days': 7,
        })

        # Action: Create recommendation
        self.env['ads.rule.action'].create({
            'rule_id': rule.id,
            'action_type': 'create_recommendation',
            'require_approval': True,
        })

        engine = RuleEngine(self.env)
        met, metric_data = engine._evaluate_rule_conditions(rule, self.campaign)
        self.assertTrue(met, "Condition should be met because ROAS is below 1.0")

        # Execute actions
        engine._execute_rule_actions(rule, self.campaign, metric_data)

        # Verify recommendation created
        recs = self.env['ads.recommendation'].search([('rule_id', '=', rule.id)])
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs.severity, 'critical')
        self.assertEqual(recs.status, 'new')

    def test_03_rule_cooldown(self):
        """Test that cooldown prevents re-triggering within cooldown_hours."""
        rule = self.env['ads.rule'].create({
            'name': 'Frequent Trigger Test',
            'severity': 'warning',
            'cooldown_hours': 12,
        })

        self.env['ads.rule.condition'].create({
            'rule_id': rule.id,
            'metric': 'spend',
            'operator': 'gt',
            'threshold': 10.0,
            'lookback_days': 7,
        })

        self.env['ads.rule.action'].create({
            'rule_id': rule.id,
            'action_type': 'create_recommendation',
        })

        engine = RuleEngine(self.env)
        stats1 = engine.evaluate_all_rules()
        self.assertGreaterEqual(stats1['triggered'], 1)

        # Immediately run again - should be in cooldown
        stats2 = engine.evaluate_all_rules()
        self.assertGreaterEqual(stats2['skipped'], 1)
