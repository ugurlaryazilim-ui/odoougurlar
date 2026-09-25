# -*- coding: utf-8 -*-
import json
import logging
import time
import requests

_logger = logging.getLogger(__name__)

class GoogleAdsError(Exception):
    def __init__(self, message, errors=None, request_id=None):
        super().__init__(message)
        self.errors = errors or []
        self.request_id = request_id


class GoogleAdsClient:
    BASE_URL = 'https://googleads.googleapis.com'
    API_VERSION = 'v25'
    MICROS = 1_000_000

    def __init__(self, access_token, developer_token, customer_id, manager_id=None, refresh_token=None, client_id=None, client_secret=None, api_version=None, on_token_refreshed=None):
        self.access_token = access_token
        self.developer_token = developer_token
        self.customer_id = str(customer_id).replace('-', '').strip() if customer_id else None
        self.manager_id = str(manager_id).replace('-', '').strip() if manager_id else None
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_version = api_version or self.API_VERSION
        self.on_token_refreshed = on_token_refreshed

    def _get_headers(self):
        """Build headers with optional developer-token and optional login-customer-id for MCC"""
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }
        if self.developer_token:
            headers['developer-token'] = str(self.developer_token)
        if self.manager_id:
            headers['login-customer-id'] = str(self.manager_id)
        return headers

    def _make_request(self, method, endpoint, data=None, retries=3):
        """Make HTTP request with retry + exponential backoff + 401 auto token refresh"""
        url = f"{self.BASE_URL}/{self.api_version}/{endpoint}"
        headers = self._get_headers()
        
        for attempt in range(retries):
            try:
                response = requests.request(method, url, headers=headers, json=data)
                
                # Check for token expiration (401) and auto refresh
                if response.status_code == 401 and self.refresh_token and attempt == 0:
                    try:
                        _logger.info("Google access token expired (HTTP 401). Refreshing token...")
                        self.refresh_access_token()
                        headers = self._get_headers()
                        continue
                    except Exception as ref_err:
                        _logger.warning("Auto refresh Google token failed: %s", str(ref_err))

                if response.status_code in (429, 500, 503) and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                    
                if not response.ok:
                    error_data = {}
                    try:
                        error_data = response.json() if response.content else {}
                    except Exception:
                        pass
                    
                    error_msg = response.text
                    error_details = []
                    
                    if isinstance(error_data, list) and error_data:
                        first = error_data[0]
                        if isinstance(first, dict):
                            err_obj = first.get('error', first)
                            if isinstance(err_obj, dict):
                                error_msg = err_obj.get('message', response.text)
                                error_details = err_obj.get('details', [])
                            else:
                                error_msg = str(err_obj)
                        else:
                            error_msg = str(first)
                    elif isinstance(error_data, dict):
                        err_obj = error_data.get('error', error_data)
                        if isinstance(err_obj, dict):
                            error_msg = err_obj.get('message', response.text)
                            error_details = err_obj.get('details', [])
                        else:
                            error_msg = str(err_obj)

                    # Extract more descriptive Google error message if present in details
                    for detail in error_details:
                        if isinstance(detail, dict) and 'errors' in detail:
                            sub_msgs = [e.get('message') for e in detail['errors'] if isinstance(e, dict) and e.get('message')]
                            if sub_msgs:
                                error_msg += " (" + ", ".join(sub_msgs) + ")"
                                
                    raise GoogleAdsError(f"HTTP {response.status_code}: {error_msg}", errors=error_details)
                    
                return response.json() if response.content else {}
            except requests.RequestException as e:
                if attempt == retries - 1:
                    raise GoogleAdsError(f"Request failed: {str(e)}")
                time.sleep(2 ** attempt)
                
    def search_stream(self, query):
        """Execute GAQL query using SearchStream (efficient for large datasets)"""
        if not self.customer_id:
            raise ValueError("customer_id is required for search")
            
        endpoint = f"customers/{self.customer_id}/googleAds:searchStream"
        data = {"query": query}
        
        results = []
        try:
            # Search stream returns a list of JSON objects (batches)
            batches = self._make_request('POST', endpoint, data=data)
            if isinstance(batches, list):
                for batch in batches:
                    if isinstance(batch, dict) and 'results' in batch:
                        results.extend(batch['results'])
            elif isinstance(batches, dict) and 'results' in batches:
                results.extend(batches['results'])
        except Exception as e:
            _logger.error(f"SearchStream Error: {str(e)}")
            raise
            
        return results
        
    def search(self, query, page_size=10000, page_token=None):
        """Execute GAQL query using Search (paginated)"""
        if not self.customer_id:
            raise ValueError("customer_id is required for search")
            
        endpoint = f"customers/{self.customer_id}/googleAds:search"
        data = {
            "query": query,
            "pageSize": page_size
        }
        if page_token:
            data["pageToken"] = page_token
            
        return self._make_request('POST', endpoint, data=data)

    def list_accessible_customers(self):
        """List all customer IDs accessible by the authenticated user."""
        endpoint = f"customers:listAccessibleCustomers"
        data = self._make_request('GET', endpoint)
        resource_names = data.get('resourceNames', [])
        return [self._extract_id_from_resource_name(r) for r in resource_names]

    def get_campaigns(self, status_filter=None):
        """Fetch all campaigns using GAQL"""
        query = """
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                campaign.advertising_channel_type,
                campaign_budget.amount_micros,
                campaign_budget.period,
                campaign_budget.total_amount_micros
            FROM campaign
            WHERE campaign.status != 'REMOVED'
        """
        if status_filter:
            if isinstance(status_filter, str):
                status_filter = [status_filter]
            status_list = ", ".join([f"'{s}'" for s in status_filter])
            query += f" AND campaign.status IN ({status_list})"
            
        results = self.search_stream(query)
        return [self.normalize_campaign(r) for r in results]

    def get_ad_groups(self, campaign_id=None):
        """Fetch ad groups (equivalent to Meta ad sets)"""
        query = """
            SELECT
                ad_group.id,
                ad_group.name,
                ad_group.status,
                ad_group.campaign,
                ad_group.type
            FROM ad_group
            WHERE ad_group.status != 'REMOVED'
        """
        if campaign_id:
            query += f" AND campaign.id = {campaign_id}"
            
        results = self.search_stream(query)
        return [self.normalize_ad_group(r) for r in results]

    def get_ads(self, ad_group_id=None):
        """Fetch ads with headlines and landing page URLs"""
        query = """
            SELECT
                ad_group_ad.ad.id,
                ad_group_ad.ad.name,
                ad_group_ad.status,
                ad_group_ad.ad.type,
                ad_group_ad.ad.final_urls,
                ad_group_ad.ad.responsive_search_ad.headlines,
                ad_group_ad.ad_group
            FROM ad_group_ad
            WHERE ad_group_ad.status != 'REMOVED'
        """
        if ad_group_id:
            query += f" AND ad_group.id = {ad_group_id}"
            
        results = self.search_stream(query)
        return [self.normalize_ad(r) for r in results]
        
    def get_campaign_metrics(self, date_from, date_to, campaign_id=None):
        """Fetch daily campaign-level metrics using GAQL"""
        query = f"""
            SELECT
                campaign.id,
                segments.date,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value,
                metrics.ctr,
                metrics.average_cpc,
                metrics.average_cpm,
                metrics.cost_per_conversion,
                metrics.all_conversions,
                metrics.interactions
            FROM campaign
            WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
        """
        if campaign_id:
            query += f" AND campaign.id = {campaign_id}"
            
        results = self.search_stream(query)
        return [self.normalize_metrics(r) for r in results]
        
    def refresh_access_token(self):
        """Refresh OAuth2 access token using refresh_token"""
        if not all([self.client_id, self.client_secret, self.refresh_token]):
            raise ValueError("Missing credentials for token refresh (client_id, client_secret, refresh_token required)")
            
        url = "https://oauth2.googleapis.com/token"
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token'
        }
        
        response = requests.post(url, data=data)
        if not response.ok:
            raise GoogleAdsError(f"Failed to refresh token: {response.text}")
            
        token_data = response.json()
        self.access_token = token_data.get('access_token')
        expires_in = token_data.get('expires_in', 3599)
        if self.on_token_refreshed and callable(self.on_token_refreshed):
            try:
                self.on_token_refreshed(self.access_token, expires_in)
            except Exception as e:
                _logger.warning("on_token_refreshed callback failed: %s", str(e))
        return self.access_token, expires_in
        
    @staticmethod
    def _extract_id_from_resource_name(resource_name):
        """Extract numeric ID from Google Ads resource name like 'customers/123/campaigns/456'"""
        return str(resource_name.split('/')[-1]) if resource_name else None
        
    def normalize_campaign(self, raw_result):
        """Normalize Google Ads campaign to standard format"""
        campaign = raw_result.get('campaign', {})
        budget = raw_result.get('campaignBudget', {})
        
        status_map = {
            'ENABLED': 'active',
            'PAUSED': 'paused',
            'REMOVED': 'removed'
        }
        
        objective_map = {
            'SEARCH': 'traffic',
            'DISPLAY': 'awareness',
            'SHOPPING': 'sales',
            'PERFORMANCE_MAX': 'sales',
            'VIDEO': 'awareness',
            'DISCOVERY': 'engagement',
            'LOCAL': 'traffic'
        }
        
        status = status_map.get(campaign.get('status'), 'unknown')
        objective = objective_map.get(campaign.get('advertisingChannelType'), 'awareness')
        
        amount_micros = budget.get('amountMicros', '0')
        daily_budget = float(amount_micros) / self.MICROS if amount_micros else 0.0
        
        total_amount_micros = budget.get('totalAmountMicros', '0')
        lifetime_budget = float(total_amount_micros) / self.MICROS if total_amount_micros else 0.0
        
        return {
            'platform_campaign_id': str(campaign.get('id', '')),
            'name': campaign.get('name', ''),
            'status': status,
            'objective': objective,
            'daily_budget': daily_budget,
            'lifetime_budget': lifetime_budget
        }
        
    def normalize_ad_group(self, raw_result):
        """Normalize Google ad group (maps to ads.adset)"""
        ad_group = raw_result.get('adGroup', {})
        
        status_map = {
            'ENABLED': 'active',
            'PAUSED': 'paused',
            'REMOVED': 'removed'
        }
        status = status_map.get(ad_group.get('status'), 'unknown')
        
        campaign_resource = ad_group.get('campaign')
        platform_campaign_id = self._extract_id_from_resource_name(campaign_resource)
        
        return {
            'platform_adset_id': str(ad_group.get('id', '')),
            'platform_campaign_id': platform_campaign_id,
            'name': ad_group.get('name', ''),
            'status': status
        }
        
    def normalize_ad(self, raw_result):
        """Normalize Google ad with rich title and preview URL"""
        ad_group_ad = raw_result.get('adGroupAd', {})
        ad = ad_group_ad.get('ad', {})
        
        status_map = {
            'ENABLED': 'active',
            'PAUSED': 'paused',
            'REMOVED': 'removed'
        }
        status = status_map.get(ad_group_ad.get('status'), 'unknown')
        
        ad_group_resource = ad_group_ad.get('adGroup')
        platform_adset_id = self._extract_id_from_resource_name(ad_group_resource)
        
        # Determine rich name from headlines
        ad_name = ad.get('name')
        if not ad_name:
            rsa = ad.get('responsiveSearchAd', {})
            headlines = rsa.get('headlines', [])
            headline_texts = [h.get('text', '').strip() for h in headlines if h.get('text')]
            if headline_texts:
                ad_name = " | ".join(headline_texts[:2])
            else:
                ad_name = f"Ad {ad.get('id', '')}"

        # Determine ad type
        raw_type = ad.get('type', '')
        type_map = {
            'RESPONSIVE_SEARCH_AD': 'text',
            'EXPANDED_TEXT_AD': 'text',
            'RESPONSIVE_DISPLAY_AD': 'dynamic',
            'IMAGE_AD': 'image',
            'VIDEO_AD': 'video',
            'SHOPPING_PRODUCT_AD': 'dynamic',
        }
        ad_type = type_map.get(raw_type, 'text')
        
        final_urls = ad.get('finalUrls', [])
        preview_url = final_urls[0] if final_urls else False
        
        return {
            'platform_ad_id': str(ad.get('id', '')),
            'platform_adset_id': platform_adset_id,
            'name': ad_name,
            'status': status,
            'ad_type': ad_type,
            'preview_url': preview_url,
        }
        
    def normalize_metrics(self, raw_result):
        """Normalize Google metrics"""
        campaign = raw_result.get('campaign', {})
        segments = raw_result.get('segments', {})
        metrics = raw_result.get('metrics', {})
        
        cost_micros = float(metrics.get('costMicros', '0'))
        spend = cost_micros / self.MICROS
        
        return {
            'platform_campaign_id': str(campaign.get('id', '')),
            'date': segments.get('date', ''),
            'impressions': int(metrics.get('impressions', '0')),
            'clicks': int(metrics.get('clicks', '0')),
            'spend': spend,
            'conversions': float(metrics.get('conversions', '0')),
            'conversion_value': float(metrics.get('conversionsValue', '0')),
            'ctr': float(metrics.get('ctr', '0')),
            'cpc': float(metrics.get('averageCpc', '0')) / self.MICROS if metrics.get('averageCpc') else 0.0,
            'cpm': float(metrics.get('averageCpm', '0')) / self.MICROS if metrics.get('averageCpm') else 0.0,
            
            # Funnel metrics not provided directly by Google GAQL typically mapped to 0
            'reach': 0,
            'link_clicks': 0,
            'landing_page_views': 0,
            'add_to_cart': 0,
            'initiate_checkout': 0,
            'purchases': 0,
        }
