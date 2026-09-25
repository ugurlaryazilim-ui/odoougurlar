# -*- coding: utf-8 -*-
import logging
import requests
import werkzeug
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v26.0"

class MetaAdsOAuthController(http.Controller):

    @http.route('/ads_manager/meta/login', type='http', auth='user')
    def meta_login(self, account_id, **kw):
        """Initiate the Meta Ads OAuth flow"""
        if not account_id:
            return request.redirect('/web')

        account = request.env['ads.account'].browse(int(account_id))
        if not account.exists() or account.platform != 'meta':
            return request.redirect('/web')

        app_id = account.meta_app_id
        if not app_id:
            account.message_post(body='Meta App ID is missing. Cannot initiate login.')
            return request.redirect(f'/web#id={account_id}&model=ads.account&view_type=form')

        # Get base URL, ensure HTTPS in production
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        if not base_url.startswith('https://') and 'localhost' not in base_url and '127.0.0.1' not in base_url:
            base_url = base_url.replace('http://', 'https://')

        redirect_uri = f"{base_url}/ads_manager/meta/callback"
        
        # Generate CSRF token
        state = secrets.token_hex(16)
        
        # Store in session
        request.session['ads_meta_account_id'] = account.id
        request.session['ads_meta_oauth_state'] = state
        request.session['ads_meta_redirect_uri'] = redirect_uri

        # Build OAuth URL
        params = {
            'client_id': app_id,
            'redirect_uri': redirect_uri,
            'scope': 'ads_management,ads_read,business_management',
            'response_type': 'code',
            'state': state
        }
        
        oauth_url = f"https://www.facebook.com/{GRAPH_API_VERSION}/dialog/oauth?{urlencode(params)}"
        
        return request.redirect(oauth_url)

    @http.route('/ads_manager/meta/callback', type='http', auth='user')
    def meta_callback(self, **kw):
        """Handle the Meta Ads OAuth callback"""
        state = kw.get('state')
        code = kw.get('code')
        error = kw.get('error')
        
        session_state = request.session.get('ads_meta_oauth_state')
        account_id = request.session.get('ads_meta_account_id')
        redirect_uri = request.session.get('ads_meta_redirect_uri')
        
        # Clean up session
        request.session.pop('ads_meta_oauth_state', None)
        request.session.pop('ads_meta_account_id', None)
        request.session.pop('ads_meta_redirect_uri', None)
        
        if not account_id:
            return request.redirect('/web')
            
        account = request.env['ads.account'].browse(account_id)
        if not account.exists():
            return request.redirect('/web')
            
        base_redirect_url = f'/web#id={account.id}&model=ads.account&view_type=form'

        try:
            if error:
                error_msg = kw.get('error_description', error)
                account.sudo().write({'state': 'error'})
                account.message_post(body=f'Meta Ads OAuth hatası (Kullanıcı reddetti veya hata oluştu): {error_msg}')
                return request.redirect(base_redirect_url)
                
            if not state or state != session_state:
                raise ValueError('Geçersiz state parametresi. Olası CSRF saldırısı.')
                
            if not code:
                raise ValueError('OAuth kodu alınamadı.')

            app_id = account.meta_app_id
            app_secret = account.meta_app_secret
            
            if not app_secret:
                raise ValueError('Meta App Secret bulunamadı.')

            # Step 1: Exchange code for short-lived token
            token_params = {
                'client_id': app_id,
                'redirect_uri': redirect_uri,
                'client_secret': app_secret,
                'code': code
            }
            token_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/oauth/access_token"
            token_res = requests.get(token_url, params=token_params)
            token_res.raise_for_status()
            token_data = token_res.json()
            short_token = token_data.get('access_token')
            
            if not short_token:
                raise ValueError('Kısa ömürlü token alınamadı.')

            # Step 2: Exchange short-lived for long-lived token
            exchange_params = {
                'grant_type': 'fb_exchange_token',
                'client_id': app_id,
                'client_secret': app_secret,
                'fb_exchange_token': short_token
            }
            exchange_res = requests.get(token_url, params=exchange_params)
            exchange_res.raise_for_status()
            exchange_data = exchange_res.json()
            long_token = exchange_data.get('access_token')
            
            if not long_token:
                raise ValueError('Uzun ömürlü token alınamadı.')

            # Step 3: Validate token and get ad account info
            adaccounts_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/me/adaccounts"
            ad_params = {
                'fields': 'account_id,name,currency,timezone_name,account_status',
                'access_token': long_token
            }
            ad_res = requests.get(adaccounts_url, params=ad_params)
            ad_res.raise_for_status()
            ad_data = ad_res.json()
            
            ad_accounts = ad_data.get('data', [])
            if not ad_accounts:
                raise ValueError('Bağlı hesaba ait Meta Reklam Hesabı (Ad Account) bulunamadı.')
                
            # Try to match the platform_account_id if provided, else use the first one
            target_ad_account = None
            if account.platform_account_id:
                for ad_acc in ad_accounts:
                    if ad_acc.get('account_id') == account.platform_account_id or f"act_{ad_acc.get('account_id')}" == account.platform_account_id:
                        target_ad_account = ad_acc
                        break
            
            if not target_ad_account:
                target_ad_account = ad_accounts[0]
                
            currency_code = target_ad_account.get('currency', 'USD')
            currency = request.env['res.currency'].search([('name', '=', currency_code)], limit=1)

            vals = {
                'access_token': long_token,
                'token_expiry': fields.Datetime.now() + timedelta(days=60),
                'state': 'connected',
                'timezone': target_ad_account.get('timezone_name'),
                'platform_account_id': target_ad_account.get('account_id'),
            }
            
            if currency:
                vals['currency_id'] = currency.id
                
            account.sudo().write(vals)
            account.message_post(body=f'Meta Ads hesabı başarıyla bağlandı. Bağlanan Hesap ID: {target_ad_account.get("account_id")}')

        except Exception as e:
            _logger.error('Meta Ads OAuth Error: %s', str(e), exc_info=True)
            account.sudo().write({'state': 'error'})
            account.message_post(body=f'Meta Ads bağlantı hatası: {str(e)}')
            
        return request.redirect(base_redirect_url)
