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

_logger = logging.getLogger(__name__)

class AdsGoogleOAuthController(http.Controller):

    @http.route('/ads_manager/google/login', type='http', auth='user')
    def google_login(self, account_id, **kw):
        """Initiates the Google OAuth 2.0 flow for Google Ads."""
        try:
            account_id = int(account_id)
            account = request.env['ads.account'].browse(account_id)
            
            if not account.exists() or account.platform != 'google':
                raise UserError("Invalid account or account is not a Google Ads account.")
                
            if not account.google_client_id or not account.google_developer_token:
                raise UserError("Google Client ID and Developer Token must be set before connecting.")
                
            base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
            redirect_uri = f"{base_url}/ads_manager/google/callback"
            
            # Generate CSRF state token
            state_token = secrets.token_hex(20)
            request.session['google_oauth_state'] = state_token
            request.session['google_oauth_account_id'] = account_id
            
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

    @http.route('/ads_manager/google/callback', type='http', auth='user')
    def google_callback(self, **kw):
        """Handles the Google OAuth 2.0 callback."""
        account = request.env['ads.account']
        try:
            # 1. Verify CSRF state token
            state = kw.get('state')
            session_state = request.session.pop('google_oauth_state', None)
            account_id = request.session.pop('google_oauth_account_id', None)
            
            if not state or not session_state or state != session_state:
                raise UserError("Invalid or missing CSRF token.")
                
            if not account_id:
                raise UserError("Missing account ID in session.")
                
            account = request.env['ads.account'].browse(int(account_id))
            if not account.exists():
                raise UserError("Account not found.")
                
            # Check for error parameter
            error = kw.get('error')
            if error:
                raise UserError(f"Google OAuth Error: {error}")
                
            code = kw.get('code')
            if not code:
                raise UserError("Missing authorization code.")
                
            base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
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
            
            token_res = requests.post(token_url, data=token_data)
            if not token_res.ok:
                raise UserError(f"Failed to exchange token: {token_res.text}")
                
            token_json = token_res.json()
            access_token = token_json.get('access_token')
            refresh_token = token_json.get('refresh_token')
            expires_in = token_json.get('expires_in', 3599)
            
            if not access_token:
                raise UserError("No access token returned from Google.")
                
            # Step 2: Validate by fetching accessible customer IDs
            api_version = account.google_api_version or 'v25'
            customers_url = f"https://googleads.googleapis.com/{api_version}/customers:listAccessibleCustomers"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'developer-token': account.google_developer_token
            }
            
            customers_res = requests.get(customers_url, headers=headers)
            if not customers_res.ok:
                raise UserError(f"Failed to fetch accessible customers: {customers_res.text}")
                
            customers_json = customers_res.json()
            resource_names = customers_json.get('resourceNames', [])
            
            if not resource_names:
                raise UserError("No accessible Google Ads customers found for this account.")
                
            # Step 3: Match customer ID or use first accessible one
            customer_id = None
            if account.platform_account_id:
                formatted_search = f"customers/{account.platform_account_id.replace('-', '')}"
                if formatted_search in resource_names:
                    customer_id = account.platform_account_id
            
            if not customer_id:
                # Use the first one
                first_resource = resource_names[0]
                customer_id = first_resource.split('/')[1]
                
            # Write to account
            update_vals = {
                'access_token': access_token,
                'token_expiry': fields.Datetime.now() + timedelta(seconds=expires_in),
                'state': 'connected',
                'platform_account_id': customer_id,
            }
            
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
