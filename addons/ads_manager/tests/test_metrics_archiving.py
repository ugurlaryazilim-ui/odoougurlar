# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo.tests import TransactionCase, tagged

@tagged('post_install', '-at_install', 'ads_manager')
class TestMetricsArchiving(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.account = cls.env['ads.account'].create({
            'name': 'Test Metric Account',
            'platform': 'meta',
            'platform_account_id': 'act_999888',
            'state': 'connected',
        })

        cls.campaign = cls.env['ads.campaign'].create({
            'name': 'Archiving Test Campaign',
            'account_id': cls.account.id,
            'status': 'active',
            'daily_budget': 80.0,
        })

    def test_01_kpi_computation(self):
        """Test computed KPIs on ads.metric.daily."""
        metric = self.env['ads.metric.daily'].create({
            'account_id': self.account.id,
            'campaign_id': self.campaign.id,
            'date': date.today(),
            'impressions': 10000,
            'clicks': 500,
            'spend': 250.0,
            'conversions': 25.0,
            'conversion_value': 1000.0,
        })

        # CTR: 500 / 10000 * 100 = 5.0%
        self.assertAlmostEqual(metric.ctr, 5.0, places=2)
        # CPC: 250 / 500 = 0.50
        self.assertAlmostEqual(metric.cpc, 0.50, places=2)
        # CPA: 250 / 25 = 10.0
        self.assertAlmostEqual(metric.cpa, 10.0, places=2)
        # ROAS: 1000 / 250 = 4.0
        self.assertAlmostEqual(metric.roas, 4.0, places=2)
        # CPM: 250 / 10000 * 1000 = 25.0
        self.assertAlmostEqual(metric.cpm, 25.0, places=2)
        # Conv Rate: 25 / 500 * 100 = 5.0%
        self.assertAlmostEqual(metric.conversion_rate, 5.0, places=2)

    def test_02_monthly_archiving_cron(self):
        """Test archiving of records older than retention period into ads.metric.monthly."""
        old_date_1 = date.today() - timedelta(days=120)
        old_date_2 = date.today() - timedelta(days=119)
        ym = old_date_1.strftime('%Y-%m')

        self.env['ads.metric.daily'].create([
            {
                'account_id': self.account.id,
                'campaign_id': self.campaign.id,
                'date': old_date_1,
                'impressions': 5000,
                'clicks': 100,
                'spend': 50.0,
                'conversions': 5.0,
                'conversion_value': 150.0,
            },
            {
                'account_id': self.account.id,
                'campaign_id': self.campaign.id,
                'date': old_date_2,
                'impressions': 7000,
                'clicks': 150,
                'spend': 70.0,
                'conversions': 7.0,
                'conversion_value': 210.0,
            },
        ])

        # Run archiving cron with 90 days retention
        self.env['ads.metric.daily']._cron_archive_old_metrics(days_retention=90)

        # 1. Daily records should now be marked is_archived = True
        archived_daily = self.env['ads.metric.daily'].search([
            ('campaign_id', '=', self.campaign.id),
            ('date', 'in', [old_date_1, old_date_2])
        ])
        self.assertTrue(all(archived_daily.mapped('is_archived')))

        # 2. Monthly aggregate record should exist
        monthly = self.env['ads.metric.monthly'].search([
            ('campaign_id', '=', self.campaign.id),
            ('year_month', '=', ym)
        ], limit=1)

        self.assertTrue(monthly.id)
        self.assertEqual(monthly.total_spend, 120.0)
        self.assertEqual(monthly.total_impressions, 12000)
        self.assertEqual(monthly.total_clicks, 250)
        self.assertEqual(monthly.total_conversions, 12.0)
        self.assertEqual(monthly.total_conversion_value, 360.0)
        self.assertAlmostEqual(monthly.avg_roas, 3.0, places=2)
