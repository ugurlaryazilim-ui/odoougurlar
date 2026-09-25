# -*- coding: utf-8 -*-

import json
import logging
import urllib.parse
import requests
from datetime import timedelta
import secrets
import werkzeug

from odoo import http, fields
from odoo.http import request
from odoo.exceptions import UserError, AccessError

import hmac
import hashlib
import time

_logger = logging.getLogger(__name__)

def _get_oauth_secret(env):
    secret = env['ir.config_parameter'].sudo().get_param('database.secret') or 'ads_oauth_default_secret'
    return secret.encode('utf-8')

def _generate_signed_state(env, account_id):
    salt = secrets.token_hex(8)
    ts = str(int(time.time()))
    payload = f"{account_id}:{ts}:{salt}"
    sig = hmac.new(_get_oauth_secret(env), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"

def _verify_signed_state(env, state_str, max_age_seconds=900):
    """Verify HMAC signed state. Returns account_id if valid, None otherwise."""
    if not state_str or ':' not in state_str:
        return None
    parts = state_str.split(':')
    if len(parts) != 4:
        return None
    account_id_str, ts_str, salt, sig = parts
    payload = f"{account_id_str}:{ts_str}:{salt}"
    expected_sig = hmac.new(_get_oauth_secret(env), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        ts = int(ts_str)
        if time.time() - ts > max_age_seconds:
            _logger.warning("OAuth state expired (age: %s seconds)", time.time() - ts)
            return None
        return int(account_id_str)
    except (ValueError, TypeError):
        return None

def _get_clean_base_url():
    base_url = request.httprequest.url_root.rstrip('/')
    forwarded_proto = request.httprequest.headers.get('X-Forwarded-Proto')
    if forwarded_proto == 'https' and base_url.startswith('http://'):
        base_url = 'https://' + base_url[7:]
    elif not base_url.startswith('https://') and 'localhost' not in base_url and '127.0.0.1' not in base_url:
        param_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        if param_url.startswith('https://'):
            base_url = param_url.rstrip('/')
        else:
            base_url = base_url.replace('http://', 'https://')
    return base_url

class AdsGoogleOAuthController(http.Controller):

    @http.route('/ads_manager/google/login', type='http', auth='user')
    def google_login(self, account_id, **kw):
        """Initiates the Google OAuth 2.0 flow for Google Ads."""
        try:
            account_id = int(account_id)
            account = request.env['ads.account'].browse(account_id)
            
            if not account.exists() or account.platform != 'google':
                raise UserError("Invalid account or account is not a Google Ads account.")
                
            if not account.google_client_id or not account.google_client_secret:
                raise UserError("Google Client ID and Client Secret must be set before connecting.")
                
            base_url = _get_clean_base_url()
            redirect_uri = f"{base_url}/ads_manager/google/callback"
            
            state_token = _generate_signed_state(request.env, account_id)
            request.session['google_oauth_state'] = state_token
            request.session['google_oauth_account_id'] = account_id
            request.session['google_oauth_redirect_uri'] = redirect_uri
            
            params = {
                'client_id': account.google_client_id,
                'redirect_uri': redirect_uri,
                'scope': 'https://www.googleapis.com/auth/adwords',
                'response_type': 'code',
                'access_type': 'offline',
                'prompt': 'consent',
                'state': state_token,
            }
            
            auth_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode(params)
            return werkzeug.utils.redirect(auth_url)
            
        except Exception as e:
            _logger.exception("Error initiating Google OAuth flow")
            return request.redirect('/web#action=ads_manager.action_ads_account')

    @http.route('/ads_manager/google/callback', type='http', auth='public', csrf=False)
    def google_callback(self, **kw):
        """Handles the Google OAuth 2.0 callback."""
        account = request.env['ads.account'].sudo()
        try:
            # 1. Verify CSRF state token using HMAC and/or session
            state = kw.get('state')
            session_state = request.session.pop('google_oauth_state', None)
            session_account_id = request.session.pop('google_oauth_account_id', None)
            
            verified_account_id = _verify_signed_state(request.env, state)
            
            # STRICT: Only accept HMAC-verified account_id — no fallback to session
            if not verified_account_id:
                _logger.warning("OAuth CSRF check failed: HMAC state verification failed (state=%s)", state)
                return request.redirect('/web#action=ads_manager.action_ads_account')
            account_id = verified_account_id
                
            account = request.env['ads.account'].sudo().browse(int(account_id))
            if not account.exists():
                raise UserError("Account not found.")
                
            # Check for error parameter
            error = kw.get('error')
            if error:
                raise UserError(f"Google OAuth Error: {error}")
                
            code = kw.get('code')
            if not code:
                raise UserError("Missing authorization code.")
                
            redirect_uri = request.session.pop('google_oauth_redirect_uri', None)
            if not redirect_uri:
                base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
                if not base_url.startswith('https://') and 'localhost' not in base_url and '127.0.0.1' not in base_url:
                    base_url = base_url.replace('http://', 'https://')
                redirect_uri = f"{base_url}/ads_manager/google/callback"
            
            # Step 1: Exchange code for tokens
            token_url = "https://oauth2.googleapis.com/token"
            token_data = {
                'client_id': account.google_client_id,
                'client_secret': account.google_client_secret,
                'code': code,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code'
            }
            
            token_res = requests.post(token_url, data=token_data, timeout=(5, 15))
            if not token_res.ok:
                raise UserError(f"Failed to exchange token: {token_res.text}")
                
            token_json = token_res.json()
            access_token = token_json.get('access_token')
            refresh_token = token_json.get('refresh_token')
            expires_in = token_json.get('expires_in', 3599)
            
            if not access_token:
                raise UserError("No access token returned from Google.")
                
            # Step 2: Validate / discover customer IDs
            headers = {
                'Authorization': f'Bearer {access_token}',
            }
            if account.google_developer_token:
                headers['developer-token'] = str(account.google_developer_token)
                
            customer_id = account.platform_account_id
            api_version = account.google_api_version or 'v25'
            customers_url = f"https://googleads.googleapis.com/{api_version}/customers:listAccessibleCustomers"
            try:
                customers_res = requests.get(customers_url, headers=headers, timeout=10)
                if customers_res.ok:
                    customers_json = customers_res.json()
                    resource_names = customers_json.get('resourceNames', [])
                    if resource_names and not customer_id:
                        customer_id = resource_names[0].split('/')[-1]
                else:
                    _logger.warning("List accessible customers returned %s: %s", customers_res.status_code, customers_res.text)
            except Exception as ex:
                _logger.warning("Error calling listAccessibleCustomers: %s", str(ex))
                
            # Write to account
            update_vals = {
                'access_token': access_token,
                'token_expiry': fields.Datetime.now() + timedelta(seconds=expires_in),
                'state': 'connected',
            }
            if customer_id:
                update_vals['platform_account_id'] = customer_id
            
            if refresh_token:
                update_vals['refresh_token'] = refresh_token
                
            account.sudo().write(update_vals)
            
            # Post success message to chatter
            account.message_post(body="Successfully connected to Google Ads API.")
            
            # Redirect back to the account form view
            action = request.env.ref('ads_manager.action_ads_account', raise_if_not_found=False)
            if action:
                url = f"/web#id={account.id}&model=ads.account&view_type=form&action={action.id}"
            else:
                url = f"/web#id={account.id}&model=ads.account&view_type=form"
            return request.redirect(url)
            
        except Exception as e:
            _logger.exception("Error in Google OAuth callback")
            if account and account.exists():
                account.sudo().write({'state': 'error'})
                account.message_post(body=f"Failed to connect to Google Ads: {str(e)}")
            return request.redirect('/web#action=ads_manager.action_ads_account')
