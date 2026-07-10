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
        env = request.env
        enable_dms = env['ir.config_parameter'].sudo().get_param('social_media_ai.enable_dms')
        if enable_dms != 'True':
            return
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

            ignored_ids = [idx for idx in [account.meta_page_id, account.meta_ig_id] if idx]
            if sender_id in ignored_ids:
                _logger.info("Ignoring outgoing DM from the business account itself.")
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
        env = request.env
        enable_comments = env['ir.config_parameter'].sudo().get_param('social_media_ai.enable_comments')
        if enable_comments != 'True':
            return
            
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

        ignored_ids = [idx for idx in [account.meta_page_id, account.meta_ig_id] if idx]
        if sender_id in ignored_ids:
            _logger.info("Ignoring outgoing comment from the business account itself.")
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

        # Build post URL if possible
        post_link = False
        linked_post = False
        if platform == 'facebook' and post_id:
            # Facebook post_id is usually pageID_postID
            post_link = f"https://facebook.com/{post_id}"
        elif platform == 'instagram' and post_id:
            # Instagram media ID is hard to link without shortcode, but we can try generic
            pass # Instagram direct links usually require shortcode from Graph API, left empty for now
            
        if post_id:
            post_line = env['social.media.post.line'].sudo().search([('platform_post_id', '=', post_id)], limit=1)
            if post_line:
                linked_post = post_line.post_id

        msg = env['social.media.message'].sudo().create({
            'conversation_id': conversation.id,
            'message_type': 'incoming',
            'content': f"[YORUM]: {message_text}",
            'is_read': False,
            'platform_message_id': comment_id,
            'post_link': post_link
        })
        conversation.sudo().write({'unread_count': conversation.unread_count + 1})

        # AI Routing for Comment
        if conversation.state == 'bot':
            self._trigger_ai_response(conversation, message_text, account, comment_id=comment_id, linked_post=linked_post)

    def _trigger_ai_response(self, conversation, user_message, account, comment_id=False, linked_post=False):
        env = request.env
        ai_provider = env['social.media.ai.provider'].sudo()
        
        system_context = env['ir.config_parameter'].sudo().get_param('social_media_ai.system_prompt', 'Sen profesyonel bir müşteri temsilcisisin. Sorulara kısa ve nazik cevaplar ver.')
        system_context += f"\n\nKullanıcı {account.platform} üzerinden yazıyor."
        
        if linked_post and hasattr(linked_post, 'product_tmpl_ids') and linked_post.product_tmpl_ids:
            ecommerce_url = env['ir.config_parameter'].sudo().get_param('social_media_ai.ecommerce_url', 'https://www.ugurlar.com').strip('/')
            system_context += "\n\nKULLANICININ YORUM YAPTIĞI GÖNDERİDEKİ ÜRÜNLER (Bu bilgileri kullanarak soruları cevapla. Sipariş linkini direkt ver):"
            for p in linked_post.product_tmpl_ids:
                price = f"{p.list_price} TL" if hasattr(p, 'list_price') else "Bilinmiyor"
                stock = p.qty_available if hasattr(p, 'qty_available') else 10
                sku = p.default_code or ""
                
                stock_text = f"{stock} Adet (Tükenmek üzere, müşteriye aciliyet bildir!)" if 0 < stock < 5 else f"{stock} Adet" if stock > 0 else "Stokta Yok (Müşteriye stokta olmadığını nazikçe belirt)"
                
                # Variants
                variants_text = ""
                if hasattr(p, 'attribute_line_ids') and p.attribute_line_ids:
                    for attr in p.attribute_line_ids:
                        variants_text += f"{attr.attribute_id.name}: {', '.join(attr.value_ids.mapped('name'))}. "
                
                link = f"{ecommerce_url}/search?q={sku}" if sku else ecommerce_url
                
                system_context += f"\n- Ürün: {p.name}"
                if sku:
                    system_context += f" (Kodu: {sku})"
                system_context += f"\n  Fiyat: {price}"
                system_context += f"\n  Stok Durumu: {stock_text}"
                if variants_text:
                    system_context += f"\n  Seçenekler: {variants_text}"
                system_context += f"\n  Sipariş Linki: {link}\n"
        
        reply_text = ai_provider.generate_response(user_message, system_context)
        
        if reply_text:
            # Check for Handoff trigger
            if "[DEVRET]" in reply_text.upper():
                reply_text = reply_text.replace("[DEVRET]", "").replace("[devret]", "").strip()
                conversation.sudo().write({'state': 'open'})
                
                # If AI gave an empty string after removing the tag, send a generic message
                if not reply_text:
                    reply_text = "Sizi hemen bir müşteri temsilcimize aktarıyorum. Lütfen hattan ayrılmayın."
            
            # Save AI response in Odoo
            env['social.media.message'].sudo().create({
                'conversation_id': conversation.id,
                'message_type': 'outgoing',
                'content': reply_text,
                'is_read': True
            })
            
            if comment_id:
                # Get the auto-reply text for public comments from settings
                auto_reply = env['ir.config_parameter'].sudo().get_param(
                    'social_media_ai.comment_auto_reply', 
                    'Merhaba, detaylı bilgi DM üzerinden iletilmiştir.'
                )
                # Reply to the comment publicly with the generic text
                self._send_meta_comment_reply(comment_id, auto_reply, account)
                # Send the actual AI answer via private DM
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
            response = requests.post(url, data=payload, timeout=10)
            if not response.ok:
                _logger.error(f"Failed to reply to comment: {response.text}")
            else:
                _logger.info(f"Successfully replied to comment {comment_id}")
        except Exception as e:
            _logger.error(f"Exception when replying to comment: {e}")

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
