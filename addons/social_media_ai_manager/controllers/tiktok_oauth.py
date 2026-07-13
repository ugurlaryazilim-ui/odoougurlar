# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import urllib.parse
import requests
import logging

_logger = logging.getLogger(__name__)

class TikTokOAuth(http.Controller):

    @http.route('/social_media_ai/tiktok/login', type='http', auth='user')
    def tiktok_login(self, account_id, **kwargs):
        """ Start the TikTok OAuth flow """
        env = request.env
        client_key = env['ir.config_parameter'].sudo().get_param('social_media_ai.tiktok_client_key')

        if not client_key:
            return "TikTok Client Key is not configured in settings."

        base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
        if base_url and base_url.startswith('http://'):
            base_url = base_url.replace('http://', 'https://')
        redirect_uri = base_url + '/social_media_ai/tiktok/callback'

        # Scopes for TikTok API (comma-separated)
        scopes = "user.info.basic,video.publish,video.upload,video.list"

        auth_url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
            'client_key': client_key,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': scopes,
            'state': str(account_id)
        })

        return request.redirect(auth_url, local=False)

    @http.route('/social_media_ai/tiktok/callback', type='http', auth='user')
    def tiktok_callback(self, **kwargs):
        """ Handle the callback from TikTok OAuth """
        env = request.env
        code = kwargs.get('code')
        state = kwargs.get('state')  # account_id
        error = kwargs.get('error')

        if error:
            return f"Error from TikTok: {error}"

        if not code or not state:
            return "Invalid request (missing code or state)."

        try:
            account_id = int(state)
        except ValueError:
            return "Invalid state parameter."

        client_key = env['ir.config_parameter'].sudo().get_param('social_media_ai.tiktok_client_key')
        client_secret = env['ir.config_parameter'].sudo().get_param('social_media_ai.tiktok_client_secret')
        base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
        if base_url and base_url.startswith('http://'):
            base_url = base_url.replace('http://', 'https://')
        redirect_uri = base_url + '/social_media_ai/tiktok/callback'

        token_url = "https://open.tiktokapis.com/v2/oauth/token/"
        data = {
            'client_key': client_key,
            'client_secret': client_secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_uri,
        }

        try:
            resp = requests.post(
                token_url,
                data=urllib.parse.urlencode(data),
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            ).json()

            if 'error' in resp:
                return f"Token Error: {resp.get('error_description', resp['error'])}"

            access_token = resp.get('access_token')
            refresh_token = resp.get('refresh_token')
            open_id = resp.get('open_id')

            if not access_token:
                return "No access token received."

            account = env['social.media.account'].browse(account_id)
            if not account.exists():
                return "Account not found."

            update_vals = {
                'api_token': access_token,
                'state': 'connected',
            }
            if refresh_token:
                update_vals['tiktok_refresh_token'] = refresh_token
            if open_id:
                update_vals['tiktok_open_id'] = open_id

            # Fetch user info
            headers = {'Authorization': f'Bearer {access_token}'}
            user_resp = requests.get(
                'https://open.tiktokapis.com/v2/user/info/',
                params={'fields': 'open_id,display_name,avatar_url'},
                headers=headers
            ).json()

            user_data = user_resp.get('data', {}).get('user', {})
            if user_data:
                if not open_id and user_data.get('open_id'):
                    update_vals['tiktok_open_id'] = user_data['open_id']
                if not account.name or account.name.startswith("New"):
                    display_name = user_data.get('display_name')
                    if display_name:
                        update_vals['name'] = display_name

            account.sudo().write(update_vals)

            # Redirect back to the account form (local URL)
            return request.redirect(f'/web#id={account.id}&model=social.media.account&view_type=form', local=False)

        except Exception as e:
            _logger.error(f"TikTok OAuth Exception: {e}")
            return f"An exception occurred: {e}"
