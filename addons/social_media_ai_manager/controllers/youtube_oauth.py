# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import urllib.parse
import requests
import logging

_logger = logging.getLogger(__name__)

class YouTubeOAuth(http.Controller):

    @http.route('/social_media_ai/youtube/login', type='http', auth='user')
    def youtube_login(self, account_id, **kwargs):
        """ Start the Google OAuth flow for YouTube """
        env = request.env
        client_id = env['ir.config_parameter'].sudo().get_param('social_media_ai.youtube_client_id')
        
        if not client_id:
            return "YouTube (Google) Client ID is not configured in settings."

        base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
        if base_url and base_url.startswith('http://'):
            base_url = base_url.replace('http://', 'https://')
        redirect_uri = base_url + '/social_media_ai/youtube/callback'
        
        # Scopes for YouTube Data API (Upload videos and read/write comments)
        scopes = [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl",
            "https://www.googleapis.com/auth/userinfo.profile"
        ]

        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(scopes),
            'access_type': 'offline',
            'prompt': 'consent',
            'state': str(account_id)
        })
        
        return request.redirect(auth_url, local=False)

    @http.route('/social_media_ai/youtube/callback', type='http', auth='user')
    def youtube_callback(self, **kwargs):
        """ Handle the callback from Google OAuth """
        env = request.env
        code = kwargs.get('code')
        state = kwargs.get('state') # account_id
        error = kwargs.get('error')
        
        if error:
            return f"Error from Google: {error}"
            
        if not code or not state:
            return "Invalid request (missing code or state)."

        try:
            account_id = int(state)
        except ValueError:
            return "Invalid state parameter."

        client_id = env['ir.config_parameter'].sudo().get_param('social_media_ai.youtube_client_id')
        client_secret = env['ir.config_parameter'].sudo().get_param('social_media_ai.youtube_client_secret')
        base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
        if base_url and base_url.startswith('http://'):
            base_url = base_url.replace('http://', 'https://')
        redirect_uri = base_url + '/social_media_ai/youtube/callback'

        token_url = "https://oauth2.googleapis.com/token"
        data = {
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }

        try:
            resp = requests.post(token_url, data=data).json()
            
            if 'error' in resp:
                return f"Token Error: {resp.get('error_description', resp['error'])}"
                
            access_token = resp.get('access_token')
            refresh_token = resp.get('refresh_token')
            
            if not access_token:
                return "No access token received."

            account = env['social.media.account'].browse(account_id)
            if not account.exists():
                return "Account not found."

            update_vals = {
                'api_token': access_token,
                'state': 'connected'
            }
            if refresh_token:
                update_vals['youtube_refresh_token'] = refresh_token

            # Fetch Channel info
            headers = {'Authorization': f'Bearer {access_token}'}
            channel_resp = requests.get('https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true', headers=headers).json()
            
            if 'items' in channel_resp and channel_resp['items']:
                channel = channel_resp['items'][0]
                update_vals['youtube_channel_id'] = channel['id']
                if not account.name or account.name.startswith("New"):
                    update_vals['name'] = channel['snippet']['title']
            
            account.sudo().write(update_vals)
            
            # Redirect back to the account form (local URL)
            return request.redirect(f'/web#id={account.id}&model=social.media.account&view_type=form', local=False)
            
        except Exception as e:
            _logger.error(f"YouTube OAuth Exception: {e}")
            return f"An exception occurred: {e}"
