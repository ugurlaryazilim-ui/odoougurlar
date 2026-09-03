# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

class WebhookWhatsApp(http.Controller):

    @http.route('/social_media_ai/webhook/whatsapp', type='jsonrpc', auth='public', methods=['POST'], csrf=False)
    def whatsapp_webhook(self, **post):
        """ Webhook endpoint for WAHA or Evolution API """
        data = request.jsonrequest
        _logger.info(f"Incoming WhatsApp Webhook: {data}")

        # Basic parsing logic for typical WAHA/Evolution payload
        # Ensure it's an incoming message
        event_type = data.get('event')
        
        # Evolution API typically sends 'messages.upsert'
        if event_type == 'messages.upsert' or 'message' in data:
            self._process_message(data)

        return {'status': 'success'}

    def _process_message(self, data):
        # Extract sender phone and message text
        # Example for WAHA structure:
        # data = {'payload': {'from': '905551234567@c.us', 'body': 'Hello Odoo!'}}
        
        payload = data.get('payload', data.get('data', {}))
        
        sender_id = payload.get('from', payload.get('key', {}).get('remoteJid', ''))
        message_text = payload.get('body', payload.get('message', {}).get('conversation', ''))
        
        if not sender_id or not message_text:
            return

        phone_number = sender_id.split('@')[0] if '@' in sender_id else sender_id

        # Ignore group messages for now
        if '@g.us' in sender_id:
            return

        env = request.env
        
        instance_name = data.get('instance')
        
        # Find WhatsApp Account
        domain = [('platform', '=', 'whatsapp')]
        if instance_name:
            domain.append(('whatsapp_instance_name', '=', instance_name))
            
        account = env['social.media.account'].sudo().search(domain, limit=1)
        if not account:
            _logger.error(f"No active WhatsApp account found in Odoo for instance {instance_name}.")
            return

        # Find or create Partner based on phone number
        partner = env['res.partner'].sudo().search([('mobile', 'like', phone_number)], limit=1)
        if not partner:
            partner = env['res.partner'].sudo().search([('phone', 'like', phone_number)], limit=1)
            
        if not partner:
            # Create a new partner
            partner = env['res.partner'].sudo().create({
                'name': f"WA Contact {phone_number}",
                'mobile': phone_number,
            })

        # Find or create Conversation
        conversation = env['social.media.conversation'].sudo().search([
            ('social_user_id', '=', phone_number),
            ('account_id', '=', account.id)
        ], limit=1)
        
        if not conversation:
            conversation = env['social.media.conversation'].sudo().create({
                'account_id': account.id,
                'social_user_id': phone_number,
                'partner_id': partner.id,
                'state': 'bot' # Assume AI handles first
            })

        # Create Message
        msg = env['social.media.message'].sudo().create({
            'conversation_id': conversation.id,
            'message_type': 'incoming',
            'content': message_text,
            'is_read': False
        })
        
        conversation.sudo().write({'unread_count': conversation.unread_count + 1})

        # Call AI Provider if state is 'bot'
        if conversation.state == 'bot':
            # Artık anında cevap üretmiyoruz, Cron (Zamanlanmış Görev) sırayla işleyecek.
            pass
        else:
            msg.is_read = True
