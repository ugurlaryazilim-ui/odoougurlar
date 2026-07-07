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
        token_url = f"https://graph.facebook.com/v19.0/oauth/access_token"
        params = {
            'client_id': app_id,
            'redirect_uri': redirect_uri,
            'client_secret': app_secret,
            'code': code
        }
        res = requests.get(token_url, params=params).json()
        user_token = res.get('access_token')

        if not user_token:
            _logger.error(f"Failed to get user token: {res}")
            return f"Failed to get user token. Check Odoo logs. Details: {res}"

        # 2. Get pages and tokens
        pages_url = f"https://graph.facebook.com/v19.0/me/accounts?access_token={user_token}"
        pages_res = requests.get(pages_url).json()

        for page in pages_res.get('data', []):
            page_id = page.get('id')
            page_name = page.get('name')
            page_token = page.get('access_token')

            # Create or update Facebook Page Account
            account = env['social.media.account'].sudo().search([('meta_page_id', '=', page_id), ('platform', '=', 'facebook')], limit=1)
            if not account:
                account = env['social.media.account'].sudo().create({
                    'name': f"{page_name} (Facebook Page)",
                    'platform': 'facebook',
                    'meta_page_id': page_id,
                })
            account.sudo().write({
                'api_token': page_token,
                'state': 'connected'
            })

            # Check for linked Instagram Account
            ig_url = f"https://graph.facebook.com/v19.0/{page_id}?fields=instagram_business_account&access_token={page_token}"
            ig_res = requests.get(ig_url).json()
            ig_business = ig_res.get('instagram_business_account')
            
            if ig_business:
                ig_id = ig_business.get('id')
                
                # Fetch IG Profile info
                ig_profile_url = f"https://graph.facebook.com/v19.0/{ig_id}?fields=username,name&access_token={page_token}"
                ig_prof_res = requests.get(ig_profile_url).json()
                ig_username = ig_prof_res.get('username') or ig_prof_res.get('name') or "IG Account"

                ig_account = env['social.media.account'].sudo().search([('meta_ig_id', '=', ig_id), ('platform', '=', 'instagram')], limit=1)
                if not ig_account:
                    ig_account = env['social.media.account'].sudo().create({
                        'name': f"{ig_username} (Instagram)",
                        'platform': 'instagram',
                        'meta_ig_id': ig_id,
                    })
                # Instagram uses the Page Token for API calls!
                ig_account.sudo().write({
                    'api_token': page_token,
                    'meta_page_id': page_id,
                    'state': 'connected'
                })

        # Redirect to social accounts view
        action = env.ref('social_media_ai_manager.action_social_media_accounts').id
        return werkzeug.utils.redirect(f'/web#action={action}&model=social.media.account&view_type=list')
