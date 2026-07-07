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
            if not partner:
                partner = env['res.partner'].sudo().create({
                    'name': f"Meta User {sender_id}",
                    'ref': f'meta_{sender_id}',
                })

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
        # TODO: Implement comments syncing if needed

    def _trigger_ai_response(self, conversation, user_message, account):
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
            
            # Send message back via Meta API
            self._send_meta_message(conversation.social_user_id, reply_text, account)

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
