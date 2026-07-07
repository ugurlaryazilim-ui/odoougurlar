# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import requests
import werkzeug
import logging

_logger = logging.getLogger(__name__)

class MetaOAuthController(http.Controller):

    @http.route('/social_media_ai/facebook/login', type='http', auth='user')
    def facebook_login(self, **kw):
        env = request.env
        app_id = env['ir.config_parameter'].sudo().get_param('social_media_ai.meta_app_id')
        if not app_id:
            return "Meta App ID not configured in settings."

        base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
        if base_url.startswith('http://') and 'localhost' not in base_url:
            base_url = base_url.replace('http://', 'https://')
            
        redirect_uri = f"{base_url}/social_media_ai/facebook/callback"

        scope = "pages_show_list,pages_messaging,pages_manage_metadata,pages_read_engagement,pages_manage_posts,instagram_basic,instagram_manage_comments,instagram_manage_messages,instagram_content_publish"
        
        auth_url = f"https://www.facebook.com/v19.0/dialog/oauth?client_id={app_id}&redirect_uri={redirect_uri}&scope={scope}&response_type=code"
        return werkzeug.utils.redirect(auth_url)

    @http.route('/social_media_ai/facebook/callback', type='http', auth='user')
    def facebook_callback(self, **kw):
        try:
            code = kw.get('code')
            if not code:
                return "No code returned from Facebook."

            env = request.env
            app_id = env['ir.config_parameter'].sudo().get_param('social_media_ai.meta_app_id')
            app_secret = env['ir.config_parameter'].sudo().get_param('social_media_ai.meta_app_secret')
            base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
            if base_url.startswith('http://') and 'localhost' not in base_url:
                base_url = base_url.replace('http://', 'https://')
                
            redirect_uri = f"{base_url}/social_media_ai/facebook/callback"

            # 1. Exchange code for user access token
            token_url = f"https://graph.facebook.com/v19.0/oauth/access_token?client_id={app_id}&redirect_uri={redirect_uri}&client_secret={app_secret}&code={code}"
            token_resp = requests.get(token_url).json()
            
            user_access_token = token_resp.get('access_token')
            if not user_access_token:
                _logger.error("Meta OAuth Error: %s", token_resp)
                return f"Error getting access token: {token_resp}"

            # 2. Get Long-lived User Token
            long_token_url = f"https://graph.facebook.com/v19.0/oauth/access_token?grant_type=fb_exchange_token&client_id={app_id}&client_secret={app_secret}&fb_exchange_token={user_access_token}"
            long_token_resp = requests.get(long_token_url).json()
            long_user_token = long_token_resp.get('access_token')
            if not long_user_token:
                return f"Error getting long-lived token: {long_token_resp}"

            # 3. Get Pages and Page Tokens
            pages_url = f"https://graph.facebook.com/v19.0/me/accounts?access_token={long_user_token}"
            pages_resp = requests.get(pages_url).json()
            
            created_accounts = []

            for page in pages_resp.get('data', []):
                page_id = page.get('id')
                page_name = page.get('name')
                page_token = page.get('access_token')
                
                # 4. Check for linked Instagram Account
                ig_url = f"https://graph.facebook.com/v19.0/{page_id}?fields=instagram_business_account&access_token={page_token}"
                ig_resp = requests.get(ig_url).json()
                ig_account = ig_resp.get('instagram_business_account')
                
                # Create or Update Facebook Page Account
                account = env['social.media.account'].sudo().search([('meta_page_id', '=', page_id), ('platform', '=', 'facebook')], limit=1)
                if not account:
                    account = env['social.media.account'].sudo().create({
                        'name': f"{page_name} (Facebook Page)",
                        'platform': 'facebook',
                        'meta_page_id': page_id,
                    })
                
                # Update tokens
                account.sudo().write({
                    'api_token': page_token,
                    'active': True
                })
                created_accounts.append(account.name)
                
                if ig_account:
                    ig_id = ig_account.get('id')
                    ig_acc = env['social.media.account'].sudo().search([('meta_ig_id', '=', ig_id), ('platform', '=', 'instagram')], limit=1)
                    if not ig_acc:
                        ig_acc = env['social.media.account'].sudo().create({
                            'name': f"{page_name} (Instagram)",
                            'platform': 'instagram',
                            'meta_ig_id': ig_id,
                            'meta_page_id': page_id,
                        })
                    
                    ig_acc.sudo().write({
                        'api_token': page_token,
                        'active': True
                    })
                    created_accounts.append(ig_acc.name)

            return request.redirect('/web#action=social_media_ai_manager.action_social_media_account')
        except Exception as e:
            _logger.error("Facebook Callback Error: %s", str(e), exc_info=True)
            return f"An internal error occurred: {str(e)}"
