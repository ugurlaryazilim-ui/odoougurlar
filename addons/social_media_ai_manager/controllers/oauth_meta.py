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

            # 3. Bypass `me/accounts` (pages_show_list) by directly querying configured pages
            # Since Meta blocks pages_show_list for internal apps, we fetch the token directly for the pages configured in Odoo.
            accounts = env['social.media.account'].sudo().search([('platform', '=', 'facebook')])
            
            created_accounts = []
            responses_log = []

            for account in accounts:
                page_id = account.meta_page_id
                if not page_id:
                    continue
                    
                # Query the page directly using the user token
                page_url = f"https://graph.facebook.com/v19.0/{page_id}?fields=name,access_token,instagram_business_account&access_token={long_user_token}"
                page_resp = requests.get(page_url).json()
                responses_log.append(f"Page {page_id}: {page_resp}")
                
                page_token = page_resp.get('access_token')
                if not page_token:
                    continue
                    
                # Update Facebook tokens
                account.sudo().write({
                    'api_token': page_token,
                    'active': True,
                    'state': 'connected'
                })
                created_accounts.append(account.name)
                
                # Subscribe the Page to the App's Webhooks
                try:
                    subscribe_url = f"https://graph.facebook.com/v19.0/{page_id}/subscribed_apps"
                    sub_data = {
                        'subscribed_fields': 'messages,messaging_postbacks,comments',
                        'access_token': page_token
                    }
                    sub_resp = requests.post(subscribe_url, data=sub_data).json()
                    _logger.info("Webhook Subscribe Response for Page %s: %s", page_id, sub_resp)
                except Exception as e:
                    _logger.error("Error subscribing webhook: %s", e)
                
                # Check for linked Instagram Account
                ig_account = page_resp.get('instagram_business_account')
                if ig_account:
                    ig_id = ig_account.get('id')
                    ig_acc = env['social.media.account'].sudo().search([('meta_ig_id', '=', ig_id), ('platform', '=', 'instagram')], limit=1)
                    if not ig_acc:
                        ig_acc = env['social.media.account'].sudo().create({
                            'name': f"{page_resp.get('name', 'Instagram')} (Instagram)",
                            'platform': 'instagram',
                            'meta_ig_id': ig_id,
                            'meta_page_id': page_id,
                        })
                    
                    ig_acc.sudo().write({
                        'api_token': page_token,
                        'active': True,
                        'state': 'connected'
                    })
                    created_accounts.append(ig_acc.name)

            if not created_accounts:
                return f"Facebook bağlandı ancak Odoo'daki hesaplarda geçerli bir 'Meta Page ID' bulunamadı veya Facebook token vermedi! Facebook Yanıtları: {responses_log}"

            return request.redirect('/web#action=social_media_ai_manager.action_social_media_account')
        except Exception as e:
            _logger.error("Facebook Callback Error: %s", str(e), exc_info=True)
            return f"An internal error occurred: {str(e)}"
