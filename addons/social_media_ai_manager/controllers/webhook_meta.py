# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import json
import logging
import requests

_logger = logging.getLogger(__name__)

class WebhookMeta(http.Controller):

    @http.route('/social_media_ai/webhook/meta', type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def meta_webhook(self, **kwargs):
        """ Webhook endpoint for Meta (Facebook & Instagram) """
        
        # 1. Webhook Verification (GET)
        if request.httprequest.method == 'GET':
            mode = request.params.get('hub.mode')
            token = request.params.get('hub.verify_token')
            challenge = request.params.get('hub.challenge')

            if mode and token:
                # Find an account with this verify_token
                env = request.env
                account = env['social.media.account'].sudo().search([
                    ('platform', 'in', ['facebook', 'instagram']),
                    ('webhook_secret', '=', token)
                ], limit=1)

                if account and mode == 'subscribe':
                    _logger.info("Meta Webhook Verified!")
                    return http.Response(challenge, status=200)
                else:
                    return http.Response("Verification failed", status=403)
            return http.Response("Invalid request", status=400)

        # 2. Event Payload (POST)
        if request.httprequest.method == 'POST':
            try:
                data = json.loads(request.httprequest.data.decode('utf-8'))
                _logger.info(f"Incoming Meta Webhook: {json.dumps(data, indent=2)}")
                
                # Check if it's an Instagram or Facebook page event
                if data.get('object') in ['instagram', 'page']:
                    for entry in data.get('entry', []):
                        # Both messaging (DMs) and changes (Comments) can arrive
                        if 'messaging' in entry:
                            for event in entry['messaging']:
                                self._process_messaging_event(event)
                        elif 'changes' in entry:
                            for change in entry['changes']:
                                self._process_changes_event(change)
                
                return http.Response('EVENT_RECEIVED', status=200)
            except Exception as e:
                _logger.error(f"Meta Webhook Error: {e}")
                return http.Response("Internal Server Error", status=500)

    def _process_messaging_event(self, event):
        """ Process incoming DMs """
        sender_id = event.get('sender', {}).get('id')
        recipient_id = event.get('recipient', {}).get('id')
        
        if 'message' in event:
            message_text = event['message'].get('text')
            
            # Ignore echo messages (messages sent by the page itself)
            if event['message'].get('is_echo'):
                return
                
            if not sender_id or not message_text:
                return

            env = request.env
            
            # Find the account that received this message
            # The recipient_id is our Page ID or IG Account ID
            account = env['social.media.account'].sudo().search([
                ('platform', 'in', ['facebook', 'instagram'])
            ], limit=1) # TODO: Better matching by ID if multiple accounts exist
            
            if not account:
                _logger.error("No matching Meta account found in Odoo.")
                return

            # Find or create Partner
            partner = env['res.partner'].sudo().search([('ref', '=', f'meta_{sender_id}')], limit=1)
            
            # Try to fetch real name
            meta_name = f"Meta User {sender_id}"
            if not partner or partner.name.startswith("Meta User"):
                profile = self._fetch_meta_user_profile(sender_id, account)
                if profile and ('name' in profile or 'first_name' in profile):
                    meta_name = profile.get('name') or f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()

            if not partner:
                partner = env['res.partner'].sudo().create({
                    'name': meta_name,
                    'ref': f'meta_{sender_id}',
                })
            elif partner.name.startswith("Meta User") and not meta_name.startswith("Meta User"):
                partner.sudo().write({'name': meta_name})

            # Find or create Conversation
            conversation = env['social.media.conversation'].sudo().search([
                ('social_user_id', '=', sender_id),
                ('account_id', '=', account.id)
            ], limit=1)
            
            if not conversation:
                conversation = env['social.media.conversation'].sudo().create({
                    'account_id': account.id,
                    'social_user_id': sender_id,
                    'partner_id': partner.id,
                    'state': 'bot'
                })

            # Create Incoming Message
            msg = env['social.media.message'].sudo().create({
                'conversation_id': conversation.id,
                'message_type': 'incoming',
                'content': message_text,
                'is_read': False,
                'platform_message_id': event['message'].get('mid')
            })
            
            conversation.sudo().write({'unread_count': conversation.unread_count + 1})

            # AI Routing
            if conversation.state == 'bot':
                self._trigger_ai_response(conversation, message_text, account)

    def _process_changes_event(self, change):
        """ Process feed changes (e.g. comments on a post) """
        _logger.info(f"Processing feed change: {change}")
        value = change.get('value', {})
        
        # Determine if it's a comment
        if change.get('field') == 'feed' and value.get('item') == 'comment' and value.get('verb') == 'add':
            # Facebook Comment
            comment_id = value.get('comment_id')
            sender_id = value.get('from', {}).get('id')
            message_text = value.get('message')
            post_id = value.get('post_id')
            platform = 'facebook'
        elif change.get('field') == 'comments':
            # Instagram Comment
            comment_id = value.get('id')
            sender_id = value.get('from', {}).get('id')
            message_text = value.get('text')
            post_id = value.get('media', {}).get('id')
            platform = 'instagram'
        else:
            return

        if not sender_id or not message_text:
            return

        env = request.env
        # Find the account that received this comment
        account = env['social.media.account'].sudo().search([
            ('platform', '=', platform)
        ], limit=1) # Note: For production, match by page/ig ID from webhook context

        if not account:
            return

        # Extract name directly from webhook payload if available
        sender_from = value.get('from', {})
        webhook_sender_name = sender_from.get('name') or sender_from.get('username')

        # Find or create Partner
        partner = env['res.partner'].sudo().search([('ref', '=', f'meta_{sender_id}')], limit=1)
        
        # Try to fetch real name
        meta_name = webhook_sender_name or f"Meta Commenter {sender_id}"
        if not partner or partner.name.startswith("Meta "):
            profile = self._fetch_meta_user_profile(sender_id, account)
            if profile and ('name' in profile or 'first_name' in profile):
                meta_name = profile.get('name') or f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()

        if not partner:
            partner = env['res.partner'].sudo().create({
                'name': meta_name,
                'ref': f'meta_{sender_id}',
            })
        elif partner.name.startswith("Meta ") and not meta_name.startswith("Meta "):
            partner.sudo().write({'name': meta_name})

        # Save Comment as a Message
        conversation = env['social.media.conversation'].sudo().search([
            ('social_user_id', '=', sender_id),
            ('account_id', '=', account.id)
        ], limit=1)
        
        if not conversation:
            conversation = env['social.media.conversation'].sudo().create({
                'account_id': account.id,
                'social_user_id': sender_id,
                'partner_id': partner.id,
                'state': 'bot'
            })

        msg = env['social.media.message'].sudo().create({
            'conversation_id': conversation.id,
            'message_type': 'incoming',
            'content': f"[COMMENT on {post_id}]: {message_text}",
            'is_read': False,
            'platform_message_id': comment_id
        })
        conversation.sudo().write({'unread_count': conversation.unread_count + 1})

        # AI Routing for Comment
        if conversation.state == 'bot':
            self._trigger_ai_response(conversation, message_text, account, comment_id=comment_id)

    def _trigger_ai_response(self, conversation, user_message, account, comment_id=False):
        env = request.env
        ai_provider = env['social.media.ai.provider'].sudo()
        
        reply_text = ai_provider.generate_response(user_message, f"User is asking on {account.platform}. Keep it friendly and concise.")
        
        if reply_text:
            # Save AI response in Odoo
            env['social.media.message'].sudo().create({
                'conversation_id': conversation.id,
                'message_type': 'outgoing',
                'content': reply_text,
                'is_read': True
            })
            
            if comment_id:
                # Reply to the comment directly
                self._send_meta_comment_reply(comment_id, reply_text, account)
                # Send private message to the commenter
                self._send_meta_private_reply(comment_id, reply_text, account)
            else:
                # Standard DM
                self._send_meta_message(conversation.social_user_id, reply_text, account)

    def _send_meta_comment_reply(self, comment_id, message_text, account):
        """ Send a public reply to a comment """
        if not account.api_token:
            return
            
        endpoint = "replies" if account.platform == 'instagram' else "comments"
        url = f"https://graph.facebook.com/v19.0/{comment_id}/{endpoint}"
        payload = {
            "message": message_text,
            "access_token": account.api_token
        }
        try:
            requests.post(url, data=payload, timeout=10)
        except Exception as e:
            _logger.error(f"Failed to reply to comment: {e}")

    def _send_meta_private_reply(self, comment_id, message_text, account):
        """ Send a private DM reply based on a comment """
        if not account.api_token:
            return
            
        url = f"https://graph.facebook.com/v19.0/me/messages"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {account.api_token}"
        }
        payload = {
            "recipient": {"comment_id": comment_id},
            "message": {"text": message_text}
        }
        try:
            requests.post(url, headers=headers, json=payload, timeout=10)
        except Exception as e:
            _logger.error(f"Failed to send private reply: {e}")

    def _send_meta_message(self, recipient_id, message_text, account):
        """ Send a message using Facebook Graph API """
        if not account.api_token:
            _logger.error("Meta API Token not configured for this account.")
            return

        url = "https://graph.facebook.com/v19.0/me/messages"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {account.api_token}"
        }
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": message_text}
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            _logger.info(f"Successfully sent Meta message to {recipient_id}")
        except Exception as e:
            _logger.error(f"Failed to send Meta message: {e}")
            if hasattr(e, 'response') and e.response is not None:
                _logger.error(f"Meta Error details: {e.response.text}")

    def _fetch_meta_user_profile(self, user_id, account):
        """ Fetch real name from Meta Graph API using PSID or ASID """
        if not account.api_token:
            return None
        url = f"https://graph.facebook.com/v19.0/{user_id}?fields=name,first_name,last_name,profile_pic&access_token={account.api_token}"
        try:
            res = requests.get(url, timeout=5).json()
            if 'error' not in res:
                return res
        except Exception as e:
            _logger.error(f"Failed to fetch user profile for {user_id}: {e}")
        return None
