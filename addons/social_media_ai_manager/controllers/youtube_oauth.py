# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.tools import html_escape
import urllib.parse
import requests
import logging

from ..tools import check_oauth_state, make_oauth_state, mask_secrets, require_system_user

_logger = logging.getLogger(__name__)

class YouTubeOAuth(http.Controller):

    @http.route('/social_media_ai/youtube/login', type='http', auth='user')
    def youtube_login(self, account_id, **kwargs):
        """ Start the Google OAuth flow for YouTube """
        env = request.env
        require_system_user(env)
        client_id = env['ir.config_parameter'].sudo().get_param('social_media_ai.youtube_client_id')

        if not client_id:
            return "YouTube (Google) Client ID is not configured in settings."

        try:
            account_id = int(account_id)
        except ValueError:
            return "Invalid account."

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
            'state': make_oauth_state(env, 'youtube', account_id),
        })

        return request.redirect(auth_url, local=False)

    @http.route('/social_media_ai/youtube/callback', type='http', auth='user')
    def youtube_callback(self, **kwargs):
        """ Handle the callback from Google OAuth """
        env = request.env
        require_system_user(env)
        code = kwargs.get('code')
        error = kwargs.get('error')

        if error:
            # NEDEN (A5 Y2): ?error= saldırgan kontrolünde; ham dönüş yansıyan XSS idi
            return "Error from Google: %s" % html_escape(error)

        # NEDEN (A5 O1): imzasız state ile başkasının Google kodu şirket hesabına yazdırılabiliyordu
        account_id = check_oauth_state(env, 'youtube', kwargs.get('state'))
        if not account_id:
            return "Invalid or expired state. Please start the login again."
        if not code:
            return "Invalid request (missing code)."

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

        access_token = refresh_token = None  # except bloğunda maskelemek için
        try:
            resp = requests.post(token_url, data=data, timeout=30).json()

            if 'error' in resp:
                return "Token Error: %s" % html_escape(resp.get('error_description', resp['error']))

            access_token = resp.get('access_token')
            refresh_token = resp.get('refresh_token')

            if not access_token:
                return "No access token received."

            account = env['social.media.account'].sudo().browse(account_id)
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
            channel_resp = requests.get('https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true', headers=headers, timeout=30).json()

            if 'items' in channel_resp and channel_resp['items']:
                channel = channel_resp['items'][0]
                update_vals['youtube_channel_id'] = channel['id']
                if not account.name or account.name.startswith("New"):
                    update_vals['name'] = channel['snippet']['title']

            account.write(update_vals)

            # Redirect back to the account form (local URL)
            return request.redirect(f'/web#id={account.id}&model=social.media.account&view_type=form', local=False)

        except Exception as e:
            # DIKKAT: istisna metni kullanıcıya dönmez (XSS + sır sızıntısı); logda maskelenir
            _logger.error("YouTube OAuth Exception: %s: %s", type(e).__name__,
                          mask_secrets(e, client_secret, code, access_token, refresh_token))
            return "YouTube bağlantısı sırasında bir hata oluştu (%s). Ayrıntı sunucu logundadır." % type(e).__name__
