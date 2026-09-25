# -*- coding: utf-8 -*-
import logging
from datetime import date, timedelta, datetime

_logger = logging.getLogger(__name__)

class BudgetPacer:
    """Service to calculate budget pacing metrics for ad campaigns."""

    def __init__(self, env):
        self.env = env

    def get_pacing_status(self, pacing_pct):
        """Determine pacing status from percentage."""
        if pacing_pct >= 150:
            return 'critical_overspend'
        elif pacing_pct >= 110:
            return 'overspending'
        elif pacing_pct <= 70:
            return 'underspending'
        return 'on_track'

    def calculate_pacing(self, campaign, today_spend_override=None):
        """Calculate current budget pacing for a campaign.
        Returns dict with pacing details.
        Args:
            today_spend_override: If provided, skip DB query for today's spend (batch optimization).
        """
        today = date.today()
        daily_budget = float(campaign.daily_budget) if getattr(campaign, 'daily_budget', 0) else 0.0
        lifetime_budget = float(campaign.lifetime_budget) if getattr(campaign, 'lifetime_budget', 0) else 0.0

        if daily_budget <= 0 and lifetime_budget <= 0:
            return {
                'pacing_pct': 100.0,
                'budget_type': 'none',
                'budget_amount': 0.0,
                'spent_today': 0.0,
                'spent_total': 0.0,
                'expected_spend': 0.0,
                'remaining_budget': 0.0,
                'projected_spend': 0.0,
                'status': 'on_track',
                'days_remaining': 0,
            }

        MetricDaily = self.env['ads.metric.daily']

        if daily_budget > 0:
            budget_type = 'daily'
            budget_amount = daily_budget
            
            # Today's spend — use override if available (batch optimization)
            if today_spend_override is not None:
                spent_today = today_spend_override
            else:
                today_metrics = MetricDaily.search([
                    ('campaign_id', '=', campaign.id),
                    ('date', '=', today)
                ])
                spent_today = sum(today_metrics.mapped('spend'))
            
            # Spent total is same as today for daily pacing context
            spent_total = spent_today

            now = datetime.now()
            hours_elapsed = now.hour + (now.minute / 60.0)
            if hours_elapsed == 0:
                hours_elapsed = 0.1 # avoid div by zero if exactly midnight
                
            expected_spend = daily_budget * (hours_elapsed / 24.0)
            
            pacing_pct = (spent_today / expected_spend) * 100 if expected_spend > 0 else 0.0
            remaining_budget = max(0, daily_budget - spent_today)
            projected_spend = daily_budget # projection for the day
            days_remaining = 0
            
        else:
            budget_type = 'lifetime'
            budget_amount = lifetime_budget
            
            start_date = campaign.start_date if getattr(campaign, 'start_date', False) else today
            end_date = campaign.end_date if getattr(campaign, 'end_date', False) else today + timedelta(days=30)
            
            total_days = (end_date - start_date).days or 1
            days_elapsed = (today - start_date).days
            days_elapsed = max(0, min(days_elapsed, total_days))
            days_remaining = max(0, total_days - days_elapsed)
            
            expected_daily_spend = lifetime_budget / total_days
            expected_spend = expected_daily_spend * days_elapsed
            
            # Total spend
            all_metrics = MetricDaily.search([
                ('campaign_id', '=', campaign.id),
                ('date', '>=', start_date),
                ('date', '<=', today)
            ])
            spent_total = sum(all_metrics.mapped('spend'))
            
            # Today spend
            today_metrics = all_metrics.filtered(lambda m: m.date == today)
            spent_today = sum(today_metrics.mapped('spend'))
            
            pacing_pct = (spent_total / expected_spend) * 100 if expected_spend > 0 else 0.0
            remaining_budget = max(0, lifetime_budget - spent_total)
            projected_spend = (spent_total / days_elapsed) * total_days if days_elapsed > 0 else lifetime_budget

        status = self.get_pacing_status(pacing_pct)

        return {
            'pacing_pct': pacing_pct,
            'budget_type': budget_type,
            'budget_amount': budget_amount,
            'spent_today': spent_today,
            'spent_total': spent_total,
            'expected_spend': expected_spend,
            'remaining_budget': remaining_budget,
            'projected_spend': projected_spend,
            'status': status,
            'days_remaining': days_remaining,
        }

    def get_projected_spend(self, campaign, period_days=30):
        """Project total spend based on recent daily averages."""
        today = date.today()
        seven_days_ago = today - timedelta(days=7)
        
        metrics = self.env['ads.metric.daily'].search([
            ('campaign_id', '=', campaign.id),
            ('date', '>=', seven_days_ago),
            ('date', '<', today)
        ])
        
        total_recent_spend = sum(metrics.mapped('spend'))
        
        # If no metrics, return 0
        if not total_recent_spend:
            return 0.0
            
        avg_daily = total_recent_spend / 7.0
        return avg_daily * period_days

    def get_recommended_daily_budget(self, campaign, target_spend, remaining_days):
        """Calculate recommended daily budget to hit target spend over remaining days."""
        today = date.today()
        start_date = getattr(campaign, 'start_date', False)
        current_budget = float(campaign.daily_budget) if getattr(campaign, 'daily_budget', 0) else 0.0
        
        if not start_date or remaining_days <= 0:
            return {
                'recommended_budget': current_budget,
                'current_budget': current_budget,
                'change_pct': 0.0
            }
            
        metrics = self.env['ads.metric.daily'].search([
            ('campaign_id', '=', campaign.id),
            ('date', '>=', start_date),
            ('date', '<=', today)
        ])
        total_spent = sum(metrics.mapped('spend'))
        
        remaining_to_spend = max(0, target_spend - total_spent)
        recommended = remaining_to_spend / remaining_days
        
        # Safety margin
        max_recommended = current_budget * 2 if current_budget > 0 else recommended
        recommended = min(recommended, max_recommended)
        
        change_pct = ((recommended - current_budget) / current_budget * 100) if current_budget > 0 else 0.0
        
        return {
            'recommended_budget': recommended,
            'current_budget': current_budget,
            'change_pct': change_pct
        }

    def calculate_batch_pacing(self, campaigns):
        """Calculate pacing for multiple campaigns efficiently."""
        if not campaigns:
            return {}
            
        today = date.today()
        
        # Fetch today's spend using _read_group (Odoo 19+)
        daily_groups = self.env['ads.metric.daily']._read_group(
            [('campaign_id', 'in', campaigns.ids), ('date', '=', today)],
            ['campaign_id'],
            ['spend:sum']
        )
        
        today_spend_map = {cam.id: spend_sum or 0.0 for cam, spend_sum in daily_groups}
        
        results = {}
        for campaign in campaigns:
            # Use pre-aggregated today spend to avoid per-campaign DB queries
            pacing = self.calculate_pacing(campaign, today_spend_override=today_spend_map.get(campaign.id))
            results[campaign.id] = pacing
            
        return results

    def get_budget_alerts(self, campaign):
        """Generate budget-related alert messages."""
        pacing_data = self.calculate_pacing(campaign)
        alerts = []
        
        pacing_pct = pacing_data['pacing_pct']
        remaining = pacing_data['remaining_budget']
        
        if remaining <= 0 and pacing_data['budget_type'] != 'none':
            alerts.append(('critical', 'KRİTİK: Bütçe tükendi!'))
        elif pacing_pct >= 150:
            alerts.append(('critical', 'KRİTİK: Bütçe %50+ aşıldı!'))
        elif pacing_pct >= 120:
            alerts.append(('warning', 'UYARI: Bütçe aşımı yaklaşıyor.'))
        elif pacing_pct <= 50 and pacing_data['budget_type'] != 'none':
            alerts.append(('info', 'BİLGİ: Bütçe kullanımı çok düşük.'))
            
        return alerts
