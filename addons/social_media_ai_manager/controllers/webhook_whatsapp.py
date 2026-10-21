# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import hmac
import logging
import re

_logger = logging.getLogger(__name__)

SECRET_PARAM = 'social_media_ai.whatsapp_webhook_secret'
SECRET_HEADER = 'X-Webhook-Secret'


class WebhookWhatsApp(http.Controller):

    # NEDEN: type='jsonrpc' JSON-RPC zarfı (params) bekler; WAHA/Evolution ham JSON gönderir.
    # Odoo 17+'da request.jsonrequest de yok; bu yüzden type='http' + get_json_data().
    @http.route('/social_media_ai/webhook/whatsapp', type='http', auth='public', methods=['POST'], csrf=False)
    def whatsapp_webhook(self, **post):
        """ Webhook endpoint for WAHA or Evolution API """
        # DIKKAT: Uç auth='public'; paylaşılan secret tanımsız veya eşleşmiyorsa hiçbir kayıt oluşmamalı.
        secret = request.env['ir.config_parameter'].sudo().get_param(SECRET_PARAM)
        given = request.httprequest.headers.get(SECRET_HEADER, '')
        if not secret or not hmac.compare_digest(given.encode('utf-8'), secret.encode('utf-8')):
            _logger.warning(
                "WhatsApp webhook rejected: secret not configured or header mismatch "
                "(Ayarlar > Teknik > Sistem Parametreleri'nde '%s' anahtarını tanımlayın; "
                "WAHA/Evolution aynı değeri '%s' başlığında göndermeli)", SECRET_PARAM, SECRET_HEADER)
            return request.make_json_response({'status': 'forbidden'}, status=403)

        try:
            data = request.get_json_data()
        except ValueError:
            return request.make_json_response({'status': 'invalid json'}, status=400)
        if not isinstance(data, dict):
            return request.make_json_response({'status': 'invalid payload'}, status=400)
        _logger.debug("Incoming WhatsApp Webhook: %s", data)

        # Basic parsing logic for typical WAHA/Evolution payload
        # Ensure it's an incoming message
        event_type = data.get('event')

        # Evolution API typically sends 'messages.upsert'
        if event_type == 'messages.upsert' or 'message' in data:
            self._process_message(data)

        return request.make_json_response({'status': 'success'})

    def _process_message(self, data):
        # Extract sender phone and message text
        # Example for WAHA structure:
        # data = {'payload': {'from': '905551234567@c.us', 'body': 'Hello Odoo!'}}

        payload = data.get('payload', data.get('data', {}))

        sender_id = payload.get('from', payload.get('key', {}).get('remoteJid', ''))
        message_text = payload.get('body', payload.get('message', {}).get('conversation', ''))

        if not sender_id or not message_text:
            return

        # Ignore group messages for now
        if '@g.us' in sender_id:
            return

        phone_number = re.sub(r'\D', '', sender_id.split('@')[0])
        if not phone_number:
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

        # NEDEN: res.partner.mobile Odoo 19'da yok; 'like %..%' indeksi kullanamaz. Rakamlara normalize
        # edilmiş numarayla '=' araması: ref (wa_<no>; Meta'daki meta_<id> kalıbı) veya phone.
        Partner = env['res.partner'].sudo()
        partner = Partner.search([
            '|', ('ref', '=', f'wa_{phone_number}'), ('phone', 'in', [phone_number, f'+{phone_number}']),
        ], limit=1)
        if not partner:
            partner = Partner.create({
                'name': f"WA Contact {phone_number}",
                'phone': phone_number,
                'ref': f'wa_{phone_number}',
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
