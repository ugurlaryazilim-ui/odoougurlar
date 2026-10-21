# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ads_manager')
class TestAdsSyncWrites(TransactionCase):
    """TODO-22: platformdan gelen değer değişmediyse yerel kayda write yapılmaz."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.account = cls.env['ads.account'].create({
            'name': 'Sync Test', 'platform': 'google', 'platform_account_id': '999-000',
            'state': 'connected',
        })
        cls.raw = {'platform_campaign_id': 'C1', 'name': 'Kampanya', 'status': 'active',
                   'objective': 'sales', 'daily_budget': 100.0, 'lifetime_budget': 0}

    def _client(self, raw):
        client = MagicMock()
        client.get_campaigns.return_value = [dict(raw)]
        return client

    def test_unchanged_campaign_is_not_written(self):
        self.assertEqual(self.account._sync_google_campaigns(self._client(self.raw)), (1, 0))
        camp = self.env['ads.campaign'].search([('platform_campaign_id', '=', 'C1')])
        with patch.object(type(camp), 'write', autospec=True) as w:
            self.assertEqual(self.account._sync_google_campaigns(self._client(self.raw)), (0, 0))
        w.assert_not_called()

    def test_changed_campaign_writes_only_diff(self):
        self.account._sync_google_campaigns(self._client(self.raw))
        camp = self.env['ads.campaign'].search([('platform_campaign_id', '=', 'C1')])
        res = self.account._sync_google_campaigns(self._client(dict(self.raw, daily_budget=150.0)))
        self.assertEqual(res, (0, 1))
        self.assertEqual(camp.daily_budget, 150.0)
        self.assertEqual(camp.name, 'Kampanya')

    def test_crons_load_on_odoo19(self):
        # Taze kurulumda ir_cron_data.xml nextcall eval'i (DateTime/relativedelta) çözülebilmeli
        cron = self.env.ref('ads_manager.ir_cron_ads_sync_metrics')
        self.assertTrue(cron.nextcall)
