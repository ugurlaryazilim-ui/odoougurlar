# -*- coding: utf-8 -*-

import logging
import json
from datetime import date, timedelta
from odoo import fields

_logger = logging.getLogger(__name__)

class RuleEngine:
    """
    Service class that evaluates optimization rules against campaign metrics
    and creates recommendations.
    """

    def __init__(self, env):
        self.env = env

    def evaluate_all_rules(self):
        """Evaluate all active rules against all connected campaigns.
        Called by the cron job.
        Returns dict with counts: {evaluated, triggered, skipped, errors}"""
        stats = {'evaluated': 0, 'triggered': 0, 'skipped': 0, 'errors': 0}
        
        rules = self.env['ads.rule'].search([('active', '=', True)])
        if not rules:
            return stats

        campaigns = self.env['ads.campaign'].search([('account_id', '!=', False)])
        
        for rule in rules:
            for campaign in campaigns:
                try:
                    # a. Check platform_filter
                    if rule.platform_filter and rule.platform_filter != 'all' and rule.platform_filter != campaign.account_id.platform:
                        stats['skipped'] += 1
                        continue
                    
                    # b. Check campaign_ids filter
                    if rule.campaign_ids and campaign.id not in rule.campaign_ids.ids:
                        stats['skipped'] += 1
                        continue
                    
                    # c. Check cooldown
                    if rule.last_triggered and rule.cooldown_hours:
                        cooldown_end = rule.last_triggered + timedelta(hours=rule.cooldown_hours)
                        if fields.Datetime.now() < cooldown_end:
                            stats['skipped'] += 1
                            continue
                    
                    # d. Check min_impressions threshold
                    if hasattr(rule, 'min_impressions') and rule.min_impressions > 0:
                        # Find the max lookback among conditions, or default to 7
                        lookbacks = rule.condition_ids.mapped('lookback_days')
                        lb = max(lookbacks) if lookbacks else 7
                        impressions = self._get_metric_value(campaign, 'impressions', lb)
                        if (impressions or 0) < rule.min_impressions:
                            stats['skipped'] += 1
                            continue
                            
                    stats['evaluated'] += 1
                    
                    # e. Evaluate conditions
                    conditions_met, metric_data = self._evaluate_rule_conditions(rule, campaign)
                    
                    # f. Execute actions if triggered
                    if conditions_met:
                        self._execute_rule_actions(rule, campaign, metric_data)
                        stats['triggered'] += 1
                        
                except Exception as e:
                    _logger.error(f"Error evaluating rule {rule.id} for campaign {campaign.id}: {e}")
                    stats['errors'] += 1

        return stats

    def _evaluate_rule_conditions(self, rule, campaign):
        """Evaluate all conditions for a rule against a campaign.
        Returns (bool, dict) - (conditions_met, metric_data_snapshot)
        Uses short-circuit evaluation to avoid unnecessary DB queries."""
        if not rule.condition_ids:
            return False, {}

        metric_data = {}
        logic = rule.condition_logic if hasattr(rule, 'condition_logic') else 'all'
        
        for condition in rule.condition_ids:
            met, val = self._evaluate_single_condition(condition, campaign)
            metric_data[condition.metric] = val
            
            # Short-circuit: stop early when result is already determined
            if logic == 'all' and not met:
                return False, metric_data
            if logic == 'any' and met:
                return True, metric_data

        if logic == 'all':
            return True, metric_data
        elif logic == 'any':
            return False, metric_data
        else:
            return True, metric_data  # default to 'all' behavior

    def _evaluate_single_condition(self, condition, campaign):
        """Evaluate a single condition against campaign metrics.
        Returns (bool, float) - (condition_met, current_value)"""
        if getattr(condition, 'consecutive_days', 1) > 1:
            for i in range(condition.consecutive_days):
                target_date = date.today() - timedelta(days=i)
                val = self._get_metric_value_for_date(campaign, condition.metric, target_date)
                met = self._apply_operator(val, condition)
                if not met:
                    return False, val
            latest_val = self._get_metric_value_for_date(campaign, condition.metric, date.today())
            return True, latest_val
        else:
            if condition.operator in ['change_pct_up', 'change_pct_down']:
                current_val = self._get_metric_value(campaign, condition.metric, condition.lookback_days)
                prev_val = self._get_previous_period_value(campaign, condition.metric, condition.lookback_days)
                
                if current_val is None or prev_val is None or prev_val == 0:
                    return False, current_val
                
                if condition.operator == 'change_pct_up':
                    pct_up = ((current_val - prev_val) / prev_val) * 100
                    return pct_up > condition.threshold, pct_up
                else:
                    pct_down = ((prev_val - current_val) / prev_val) * 100
                    return pct_down > condition.threshold, pct_down
            else:
                val = self._get_metric_value(campaign, condition.metric, condition.lookback_days)
                return self._apply_operator(val, condition), val

    def _apply_operator(self, val, condition):
        if val is None:
            return False
        if condition.operator == 'gt':
            return val > condition.threshold
        elif condition.operator == 'lt':
            return val < condition.threshold
        elif condition.operator == 'gte':
            return val >= condition.threshold
        elif condition.operator == 'lte':
            return val <= condition.threshold
        return False

    def _get_metric_value(self, campaign, metric_name, lookback_days):
        """Get aggregated metric value for a campaign over lookback period.
        Returns float value or None if insufficient data."""
        if metric_name == 'budget_pace':
            try:
                from .budget_pacer import BudgetPacer
                pacing = BudgetPacer(self.env).calculate_pacing(campaign)
                return pacing.get('pacing_pct', 100.0)
            except Exception:
                return 100.0

        date_from = date.today() - timedelta(days=lookback_days)
        domain = [
            ('campaign_id', '=', campaign.id),
            ('date', '>=', date_from),
            ('date', '<=', date.today()),
        ]
        aggregates = self.env['ads.metric.daily']._read_group(
            domain, [],
            ['spend:sum', 'impressions:sum', 'clicks:sum', 'conversions:sum', 'conversion_value:sum', 'frequency:avg']
        )
        return self._calculate_metric(aggregates, metric_name)

    def _get_metric_value_for_date(self, campaign, metric_name, target_date):
        """Get metric value for a specific date (for consecutive_days check)."""
        if metric_name == 'budget_pace':
            return 0.0
            
        domain = [
            ('campaign_id', '=', campaign.id),
            ('date', '=', target_date),
        ]
        aggregates = self.env['ads.metric.daily']._read_group(
            domain, [],
            ['spend:sum', 'impressions:sum', 'clicks:sum', 'conversions:sum', 'conversion_value:sum', 'frequency:avg']
        )
        return self._calculate_metric(aggregates, metric_name)

    def _get_previous_period_value(self, campaign, metric_name, lookback_days):
        """Get metric value for the previous period (for change_pct operators).
        Previous period = [today - 2*lookback, today - lookback]"""
        date_from = date.today() - timedelta(days=2 * lookback_days)
        date_to = date.today() - timedelta(days=lookback_days + 1)
        domain = [
            ('campaign_id', '=', campaign.id),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ]
        aggregates = self.env['ads.metric.daily']._read_group(
            domain, [],
            ['spend:sum', 'impressions:sum', 'clicks:sum', 'conversions:sum', 'conversion_value:sum', 'frequency:avg']
        )
        return self._calculate_metric(aggregates, metric_name)

    def _calculate_metric(self, aggregates, metric_name):
        if not aggregates:
            return 0.0
            
        sum_spend, sum_impressions, sum_clicks, sum_conversions, sum_conversion_value, avg_frequency = aggregates[0]
        
        sum_spend = sum_spend or 0.0
        sum_impressions = sum_impressions or 0.0
        sum_clicks = sum_clicks or 0.0
        sum_conversions = sum_conversions or 0.0
        sum_conversion_value = sum_conversion_value or 0.0
        avg_frequency = avg_frequency or 0.0
        
        if metric_name == 'ctr':
            return (sum_clicks / sum_impressions * 100) if sum_impressions else 0.0
        elif metric_name == 'cpc':
            return (sum_spend / sum_clicks) if sum_clicks else 0.0
        elif metric_name == 'cpa':
            return (sum_spend / sum_conversions) if sum_conversions else 0.0
        elif metric_name == 'roas':
            return (sum_conversion_value / sum_spend) if sum_spend else 0.0
        elif metric_name == 'spend':
            return sum_spend
        elif metric_name == 'impressions':
            return sum_impressions
        elif metric_name == 'clicks':
            return sum_clicks
        elif metric_name == 'conversions':
            return sum_conversions
        elif metric_name == 'conversion_rate':
            return (sum_conversions / sum_clicks * 100) if sum_clicks else 0.0
        elif metric_name == 'frequency':
            return avg_frequency
            
        return 0.0

    def _execute_rule_actions(self, rule, campaign, metric_data):
        """Execute all actions defined for a triggered rule."""
        rule.write({
            'last_triggered': fields.Datetime.now(),
            'trigger_count': (rule.trigger_count or 0) + 1
        })
        
        for action in rule.action_ids:
            if action.action_type == 'create_recommendation':
                self._create_recommendation(rule, campaign, metric_data)
            elif action.action_type == 'notify_chatter':
                self._notify_via_chatter(campaign, rule, metric_data)
            elif action.action_type == 'notify_activity':
                self._notify_via_activity(campaign, rule)
            elif action.action_type == 'notify_email':
                self._notify_via_email(campaign, rule)
            elif action.action_type == 'pause_entity':
                self._create_recommendation(rule, campaign, metric_data, proposed_action="Kampanyayı duraklat (Pause)")
            elif action.action_type == 'adjust_budget_pct':
                proposal = self._build_budget_adjustment_proposal(rule, campaign, action, metric_data)
                self._create_recommendation(rule, campaign, metric_data, proposed_action=proposal)

    def _create_recommendation(self, rule, campaign, metric_data, proposed_action=None):
        """Create an ads.recommendation record."""
        vals = {
            'name': f"{rule.name}: {campaign.name}",
            'campaign_id': campaign.id,
            'rule_id': rule.id,
            'severity': getattr(rule, 'severity', 'info'),
            'category': getattr(rule, 'category', 'performance'),
            'status': 'new',
            'description': rule.description or f'Kural "{rule.name}" tetiklendi.',
            'proposed_action': proposed_action or '',
            'metric_data': metric_data,  # Assuming metric_data is a Json field
        }
        rec = self.env['ads.recommendation'].create(vals)
        
        if hasattr(rec, '_notify_critical') and vals['severity'] == 'critical':
            rec._notify_critical()
            
        return rec

    def _notify_via_chatter(self, campaign, rule, metric_data):
        """Post a formatted message to campaign chatter."""
        severity = getattr(rule, 'severity', 'info')
        category = getattr(rule, 'category', 'performance')
        
        body = f"""
        <p><strong>⚠️ Kural Tetiklendi: {rule.name}</strong></p>
        <ul>
            <li>Önem: {severity}</li>
            <li>Kategori: {category}</li>
            <li>Metrik Verileri: {json.dumps(metric_data)}</li>
        </ul>
        """
        campaign.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_note')

    def _notify_via_activity(self, campaign, rule):
        """Schedule an activity on the campaign."""
        user_id = campaign.user_id.id if campaign.user_id else self.env.user.id
        campaign.activity_schedule(
            'mail.mail_activity_data_todo',
            user_id=user_id,
            note=f'Kural "{rule.name}" tetiklendi. Lütfen inceleyin.',
            summary=f'Kural Uyarısı: {rule.name}',
        )

    def _notify_via_email(self, campaign, rule):
        """Send email notification via mail template."""
        template = self.env.ref('ads_manager.email_template_ads_critical_alert', raise_if_not_found=False)
        if template:
            template.send_mail(campaign.id, force_send=True)

    def _build_budget_adjustment_proposal(self, rule, campaign, action, metric_data):
        """Build a proposed budget adjustment text."""
        pct = action.adjustment_value or 0.0
        current_budget = campaign.daily_budget or 0.0
        proposed = current_budget * (1 + pct / 100)
        
        if hasattr(action, 'max_single_adjustment') and action.max_single_adjustment:
            if abs(proposed - current_budget) > action.max_single_adjustment:
                diff = action.max_single_adjustment if pct > 0 else -action.max_single_adjustment
                proposed = current_budget + diff
                
        return f"Günlük bütçeyi {current_budget:.2f} → {proposed:.2f} olarak değiştirmeyi öneriyoruz ({pct:+.1f}%)"
