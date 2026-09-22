# -*- coding: utf-8 -*-

import json
import logging
import time
import requests
from typing import Dict, List, Optional, Any, Union

_logger = logging.getLogger(__name__)


class MetaApiError(Exception):
    """Custom exception for Meta API errors."""
    def __init__(self, message: str, error_code: Optional[int] = None, error_subcode: Optional[int] = None, fb_trace_id: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.error_subcode = error_subcode
        self.fb_trace_id = fb_trace_id

    def __str__(self) -> str:
        return f"MetaApiError: {self.message} (Code: {self.error_code}, Subcode: {self.error_subcode}, Trace ID: {self.fb_trace_id})"


class MetaAdsClient:
    """Client for Meta Marketing API v26.0."""

    BASE_URL = 'https://graph.facebook.com'

    INSIGHTS_FIELDS = [
        'campaign_id', 'adset_id', 'ad_id', 'date_start', 'date_stop',
        'impressions', 'clicks', 'spend', 'reach', 'frequency', 
        'ctr', 'cpc', 'cpm', 'actions', 'action_values', 'cost_per_action_type'
    ]

    CAMPAIGN_FIELDS = [
        'id', 'name', 'status', 'objective', 'daily_budget', 'lifetime_budget', 
        'configured_status', 'effective_status'
    ]

    ADSET_FIELDS = [
        'id', 'name', 'campaign_id', 'status', 'daily_budget', 'lifetime_budget', 
        'targeting', 'optimization_goal', 'effective_status'
    ]

    AD_FIELDS = [
        'id', 'name', 'adset_id', 'status', 'creative{id,name,thumbnail_url}', 
        'configured_status', 'effective_status'
    ]

    def __init__(self, access_token: str, api_version: str = 'v26.0', account_id: Optional[str] = None, business_id: Optional[str] = None):
        self.access_token = access_token
        self.api_version = api_version if api_version.startswith('v') else f"v{api_version}"
        self.account_id = account_id
        self.business_id = business_id
        self.session = requests.Session()

    def _check_rate_limit(self, response: requests.Response) -> None:
        """Parse x-business-use-case-usage header, throttle if > 80%"""
        header = response.headers.get('x-business-use-case-usage')
        if header:
            try:
                usage = json.loads(header)
                for biz_id, limits in usage.items():
                    for limit in limits:
                        call_count = limit.get('call_count', 0)
                        total_cputime = limit.get('total_cputime', 0)
                        if call_count > 80 or total_cputime > 80:
                            wait_time = max(limit.get('estimated_time_to_regain_access', 60), 60)
                            _logger.warning('Meta BUC rate limit near threshold (%s%%), waiting %ds', call_count, wait_time)
                            time.sleep(wait_time)
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                _logger.debug("Failed to parse Meta rate limit header: %s", e)

    def _make_request(self, method: str, endpoint: str, params: Optional[Dict] = None, data: Optional[Dict] = None, retries: int = 3) -> Dict:
        """Make HTTP request with retry + backoff + rate limit check"""
        url = f"{self.BASE_URL}/{self.api_version}/{endpoint.lstrip('/')}"
        
        req_params = params.copy() if params else {}
        req_params['access_token'] = self.access_token

        backoff = 1
        for attempt in range(retries):
            try:
                response = self.session.request(method, url, params=req_params, json=data)
                self._check_rate_limit(response)
                
                if response.status_code in [429, 500, 502, 503, 504]:
                    if attempt < retries - 1:
                        time.sleep(backoff)
                        backoff *= 2
                        continue

                response_data = response.json()
                if not response.ok:
                    error = response_data.get('error', {})
                    raise MetaApiError(
                        message=error.get('message', 'Unknown error'),
                        error_code=error.get('code'),
                        error_subcode=error.get('error_subcode'),
                        fb_trace_id=error.get('fbtrace_id')
                    )
                
                return response_data

            except requests.exceptions.RequestException as e:
                if attempt < retries - 1:
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    raise MetaApiError(f"Network error: {str(e)}") from e

        raise MetaApiError("Max retries exceeded")

    def _fetch_all_pages(self, endpoint: str, params: Dict) -> List[Dict]:
        """Helper to fetch all items across multiple cursor-paginated requests."""
        results = []
        next_url = None
        
        while True:
            if next_url:
                req_params = {'access_token': self.access_token}
                try:
                    response = self.session.get(next_url, params=req_params)
                    self._check_rate_limit(response)
                    response.raise_for_status()
                    data = response.json()
                except requests.exceptions.RequestException as e:
                    raise MetaApiError(f"Network error during pagination: {str(e)}") from e
            else:
                data = self._make_request('GET', endpoint, params=params)
            
            results.extend(data.get('data', []))
            
            paging = data.get('paging', {})
            next_url = paging.get('next')
            if not next_url:
                break
                
        return results

    def get_campaigns(self, fields: Optional[List[str]] = None, limit: int = 100, status_filter: Optional[List[str]] = None) -> List[Dict]:
        """Fetch all campaigns for the account with cursor pagination"""
        if not self.account_id:
            raise ValueError("account_id is required")

        endpoint = f"{self.account_id}/campaigns"
        params = {
            'fields': ','.join(fields or self.CAMPAIGN_FIELDS),
            'limit': limit
        }
        if status_filter:
            params['filtering'] = json.dumps([
                {'field': 'effective_status', 'operator': 'IN', 'value': status_filter}
            ])

        return self._fetch_all_pages(endpoint, params)

    def get_adsets(self, campaign_id: Optional[str] = None, fields: Optional[List[str]] = None, limit: int = 100) -> List[Dict]:
        """Fetch ad sets, optionally filtered by campaign"""
        endpoint = f"{campaign_id}/adsets" if campaign_id else f"{self.account_id}/adsets"
        if not campaign_id and not self.account_id:
            raise ValueError("campaign_id or account_id is required")

        params = {
            'fields': ','.join(fields or self.ADSET_FIELDS),
            'limit': limit
        }
        return self._fetch_all_pages(endpoint, params)

    def get_ads(self, adset_id: Optional[str] = None, fields: Optional[List[str]] = None, limit: int = 100) -> List[Dict]:
        """Fetch ads, optionally filtered by ad set"""
        endpoint = f"{adset_id}/ads" if adset_id else f"{self.account_id}/ads"
        if not adset_id and not self.account_id:
            raise ValueError("adset_id or account_id is required")

        params = {
            'fields': ','.join(fields or self.AD_FIELDS),
            'limit': limit
        }
        return self._fetch_all_pages(endpoint, params)

    def get_insights(self, object_id: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None, 
                     level: str = 'campaign', time_increment: int = 1, breakdowns: Optional[List[str]] = None,
                     fields: Optional[List[str]] = None, async_mode: bool = False) -> List[Dict]:
        """Fetch insights for account/campaign/adset/ad"""
        target_id = object_id or self.account_id
        if not target_id:
            raise ValueError("object_id or account_id is required")

        params = {
            'level': level,
            'time_increment': time_increment,
            'fields': ','.join(fields or self.INSIGHTS_FIELDS)
        }
        
        if date_from and date_to:
            params['time_range'] = json.dumps({'since': date_from, 'until': date_to})
            
        if breakdowns:
            params['breakdowns'] = ','.join(breakdowns)

        endpoint = f"{target_id}/insights"

        if async_mode:
            response = self._make_request('POST', endpoint, params=params)
            report_run_id = response.get('report_run_id')
            if not report_run_id:
                raise MetaApiError("Failed to start async report")
            return self._poll_async_report(report_run_id)
        else:
            return self._fetch_all_pages(endpoint, params)

    def _poll_async_report(self, report_run_id: str, max_wait: int = 600, poll_interval: int = 10) -> List[Dict]:
        """Poll async report until completion, then fetch results with cursor pagination"""
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            status_data = self._make_request('GET', report_run_id)
            status = status_data.get('async_status')
            
            if status == 'Job Completed':
                return self._fetch_all_pages(f"{report_run_id}/insights", {})
            elif status == 'Job Failed':
                raise MetaApiError(f"Async report {report_run_id} failed")
                
            time.sleep(poll_interval)
            
        raise MetaApiError(f"Async report {report_run_id} timed out after {max_wait}s")

    def normalize_campaign(self, raw_campaign: Dict) -> Dict:
        """Normalize Meta campaign data to standard format"""
        status_map = {
            'ACTIVE': 'active',
            'PAUSED': 'paused',
            'ARCHIVED': 'archived',
            'DELETED': 'removed'
        }
        
        objective_map = {
            'OUTCOME_AWARENESS': 'awareness',
            'OUTCOME_TRAFFIC': 'traffic',
            'OUTCOME_ENGAGEMENT': 'engagement',
            'OUTCOME_LEADS': 'leads',
            'OUTCOME_SALES': 'sales',
            'OUTCOME_APP_PROMOTION': 'app_installs'
        }
        
        eff_status = raw_campaign.get('effective_status', 'PAUSED')
        status = status_map.get(eff_status, 'paused')
        
        raw_obj = raw_campaign.get('objective', '')
        objective = objective_map.get(raw_obj, 'traffic')
        
        daily_budget = raw_campaign.get('daily_budget')
        daily_budget = float(daily_budget) / 100.0 if daily_budget else 0.0
        
        lifetime_budget = raw_campaign.get('lifetime_budget')
        lifetime_budget = float(lifetime_budget) / 100.0 if lifetime_budget else 0.0

        return {
            'platform_campaign_id': raw_campaign.get('id'),
            'name': raw_campaign.get('name'),
            'status': status,
            'objective': objective,
            'daily_budget': daily_budget,
            'lifetime_budget': lifetime_budget
        }

    def normalize_adset(self, raw_adset: Dict) -> Dict:
        """Normalize adset data"""
        status_map = {
            'ACTIVE': 'active',
            'PAUSED': 'paused',
            'ARCHIVED': 'archived',
            'DELETED': 'removed'
        }
        
        eff_status = raw_adset.get('effective_status', 'PAUSED')
        status = status_map.get(eff_status, 'paused')

        daily_budget = raw_adset.get('daily_budget')
        daily_budget = float(daily_budget) / 100.0 if daily_budget else 0.0
        
        lifetime_budget = raw_adset.get('lifetime_budget')
        lifetime_budget = float(lifetime_budget) / 100.0 if lifetime_budget else 0.0

        return {
            'platform_adset_id': raw_adset.get('id'),
            'platform_campaign_id': raw_adset.get('campaign_id'),
            'name': raw_adset.get('name'),
            'status': status,
            'daily_budget': daily_budget,
            'lifetime_budget': lifetime_budget
        }

    def normalize_ad(self, raw_ad: Dict) -> Dict:
        """Normalize ad data"""
        status_map = {
            'ACTIVE': 'active',
            'PAUSED': 'paused',
            'ARCHIVED': 'archived',
            'DELETED': 'removed'
        }
        
        eff_status = raw_ad.get('effective_status', 'PAUSED')
        status = status_map.get(eff_status, 'paused')

        return {
            'platform_ad_id': raw_ad.get('id'),
            'platform_adset_id': raw_ad.get('adset_id'),
            'name': raw_ad.get('name'),
            'status': status
        }

    def normalize_insights(self, raw_insights: Dict) -> Dict:
        """Normalize insights data - extract conversions from actions array"""
        actions = raw_insights.get('actions', [])
        action_values = raw_insights.get('action_values', [])
        
        def get_action_val(data_list: List[Dict], action_types: List[str]) -> float:
            total = 0.0
            for item in data_list:
                if item.get('action_type') in action_types:
                    try:
                        total += float(item.get('value', 0))
                    except (ValueError, TypeError):
                        pass
            return total

        conversion_types = ['offsite_conversion.fb_pixel_purchase', 'purchase']
        link_click_types = ['link_click']
        landing_page_types = ['landing_page_view']
        add_to_cart_types = ['add_to_cart']
        initiate_checkout_types = ['initiate_checkout']
        
        conversions = get_action_val(actions, conversion_types)
        conversion_value = get_action_val(action_values, conversion_types)
        link_clicks = get_action_val(actions, link_click_types)
        landing_page_views = get_action_val(actions, landing_page_types)
        add_to_cart = get_action_val(actions, add_to_cart_types)
        initiate_checkout = get_action_val(actions, initiate_checkout_types)
        purchases = get_action_val(actions, conversion_types)

        try:
            spend = float(raw_insights.get('spend', 0))
        except (ValueError, TypeError):
            spend = 0.0

        return {
            'date': raw_insights.get('date_start'),
            'impressions': int(raw_insights.get('impressions', 0)),
            'clicks': int(raw_insights.get('clicks', 0)),
            'spend': spend,
            'reach': int(raw_insights.get('reach', 0)),
            'frequency': float(raw_insights.get('frequency', 0)) if raw_insights.get('frequency') else 0.0,
            'ctr': float(raw_insights.get('ctr', 0)) if raw_insights.get('ctr') else 0.0,
            'cpc': float(raw_insights.get('cpc', 0)) if raw_insights.get('cpc') else 0.0,
            'cpm': float(raw_insights.get('cpm', 0)) if raw_insights.get('cpm') else 0.0,
            'conversions': int(conversions),
            'conversion_value': float(conversion_value),
            'link_clicks': int(link_clicks),
            'landing_page_views': int(landing_page_views),
            'add_to_cart': int(add_to_cart),
            'initiate_checkout': int(initiate_checkout),
            'purchases': int(purchases)
        }
