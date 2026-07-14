# -*- coding: utf-8 -*-
from odoo import models, fields, exceptions, api

class SocialMediaAccount(models.Model):
    _name = 'social.media.account'
    _description = 'Social Media Account'

    name = fields.Char(string="Account Name", required=True)
    platform = fields.Selection([
        ('whatsapp', 'WhatsApp (WAHA/Evolution)'),
        ('facebook', 'Facebook Page'),
        ('instagram', 'Instagram Account'),
        ('youtube', 'YouTube Channel'),
        ('tiktok', 'TikTok Account'),
    ], string="Platform", required=True)
    
    active = fields.Boolean(default=True)
    
    # API Credentials / Webhook tokens
    api_token = fields.Char(string="API Token / Access Token")
    webhook_secret = fields.Char(string="Webhook Secret (Verify Token)")
    phone_number = fields.Char(string="Phone Number (WhatsApp)")
    
    # Meta Specific IDs
    meta_page_id = fields.Char(string="Meta Page ID")
    meta_ig_id = fields.Char(string="Instagram Account ID")

    # YouTube Specific
    youtube_refresh_token = fields.Char(string="YouTube Refresh Token")
    youtube_channel_id = fields.Char(string="YouTube Channel ID")

    # TikTok Specific
    tiktok_refresh_token = fields.Char(string="TikTok Refresh Token")
    tiktok_open_id = fields.Char(string="TikTok Open ID")
    
    # WhatsApp Specific (Evolution API)
    whatsapp_api_url = fields.Char(string="WhatsApp API URL (Evolution)")
    whatsapp_instance_name = fields.Char(string="WhatsApp Instance Name")
    
    # Connection status
    state = fields.Selection([
        ('draft', 'Not Connected'),
        ('connected', 'Connected'),
        ('error', 'Error / Disconnected')
    ], string="Status", default='draft')
    
    def action_subscribe_webhooks(self):
        """ Manually subscribe the Page to the App's Webhooks and show result """
        self.ensure_one()
        if self.platform not in ['facebook', 'instagram'] or not self.api_token or not self.meta_page_id:
            raise exceptions.UserError("Bu işlem için Facebook/Instagram seçili olmalı, Meta Page ID ve API Token dolu olmalıdır.")
            
        import requests
        
        subscribe_url = f"https://graph.facebook.com/v19.0/{self.meta_page_id}/subscribed_apps"
        sub_data = {
            'subscribed_fields': 'messages,messaging_postbacks,feed',
            'access_token': self.api_token
        }
        
        try:
            resp = requests.post(subscribe_url, data=sub_data).json()
            if resp.get('success'):
                raise exceptions.UserError("BAŞARILI! Facebook sayfanız Odoo tetikleyicisine başarıyla bağlandı. Artık mesajlar Odoo'ya düşecek.")
            else:
                raise exceptions.UserError(f"HATA! Facebook tetikleyiciyi reddetti: {resp}")
        except Exception as e:
            if "BAŞARILI" in str(e) or "HATA" in str(e):
                raise e
            raise exceptions.UserError(f"Bağlantı hatası: {e}")

    def action_open_qr_wizard(self):
        self.ensure_one()
        if self.platform != 'whatsapp':
            raise exceptions.UserError("Bu işlem sadece WhatsApp için geçerlidir.")
        
        wizard = self.env['social.media.whatsapp.qr.wizard'].create({
            'account_id': self.id
        })
        wizard.action_fetch_qr()
        return wizard._reopen()

    def action_setup_webhook(self):
        self.ensure_one()
        if self.platform != 'whatsapp':
            raise exceptions.UserError("Bu işlem sadece WhatsApp için geçerlidir.")
        if not self.whatsapp_api_url or not self.api_token or not self.whatsapp_instance_name:
            raise exceptions.UserError("API URL, API Şifresi ve Instance Name alanları dolu olmalıdır.")

        import requests
        base_url = self.whatsapp_api_url.rstrip('/')
        instance_name = self.whatsapp_instance_name
        headers = {
            'apikey': self.api_token,
            'Content-Type': 'application/json'
        }

        # Odoo'nun dışarıdan erişilebilir web adresi (Config'den çekilir veya sistem parametresinden)
        base_web_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        webhook_url = f"{base_web_url}/social_media_ai/webhook/whatsapp"

        set_webhook_url = f"{base_url}/webhook/set/{instance_name}"
        payload = {
            "webhook": {
                "enabled": True,
                "url": webhook_url,
                "webhookByEvents": False,
                "events": ["MESSAGES_UPSERT"]
            }
        }

        try:
            res = requests.post(set_webhook_url, headers=headers, json=payload, timeout=10)
            if res.ok:
                raise exceptions.UserError(f"BAŞARILI! Webhook başarıyla ayarlandı.\nAdres: {webhook_url}")
            else:
                raise exceptions.UserError(f"HATA: Webhook ayarlanamadı. Yanıt: {res.text}")
        except Exception as e:
            if "BAŞARILI" in str(e) or "HATA" in str(e):
                raise e
            raise exceptions.UserError(f"Webhook bağlantı hatası: {e}")

    def action_login_facebook(self):
        """ Redirect to Facebook Login """
        return {
            'type': 'ir.actions.act_url',
            'url': '/social_media_ai/facebook/login',
            'target': 'self',
        }

    def action_login_youtube(self):
        """ Redirect to Google OAuth Login for YouTube """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/social_media_ai/youtube/login?account_id={self.id}',
            'target': 'self',
        }

    def action_login_tiktok(self):
        """ Redirect to TikTok OAuth Login """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/social_media_ai/tiktok/login?account_id={self.id}',
            'target': 'self',
        }

    def _refresh_tiktok_token(self):
        """ Refresh TikTok Access Token using the refresh token """
        self.ensure_one()
        if self.platform != 'tiktok' or not self.tiktok_refresh_token:
            return False

        client_key = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.tiktok_client_key')
        client_secret = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.tiktok_client_secret')

        if not client_key or not client_secret:
            return False

        import requests
        token_url = "https://open.tiktokapis.com/v2/oauth/token/"
        data = {
            'client_key': client_key,
            'client_secret': client_secret,
            'refresh_token': self.tiktok_refresh_token,
            'grant_type': 'refresh_token'
        }

        try:
            resp = requests.post(token_url, data=data, headers={'Content-Type': 'application/x-www-form-urlencoded'}).json()
            if 'access_token' in resp:
                self.api_token = resp['access_token']
                if resp.get('refresh_token'):
                    self.tiktok_refresh_token = resp['refresh_token']
                return True
        except Exception:
            pass

        return False

    def _refresh_youtube_token(self):
        """ Refresh YouTube Access Token using the refresh token """
        self.ensure_one()
        if self.platform != 'youtube' or not self.youtube_refresh_token:
            return False

        client_id = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.youtube_client_id')
        client_secret = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.youtube_client_secret')

        if not client_id or not client_secret:
            return False

        import requests
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'refresh_token': self.youtube_refresh_token,
            'grant_type': 'refresh_token'
        }
        
        try:
            resp = requests.post(token_url, data=data).json()
            if 'access_token' in resp:
                self.api_token = resp['access_token']
                return True
        except Exception:
            pass
            
        return False

    @api.model
    def _cron_sync_youtube_comments(self):
        accounts = self.search([('platform', '=', 'youtube'), ('state', '=', 'connected')])
        for account in accounts:
            account._sync_youtube_comments()

    def _sync_youtube_comments(self):
        self.ensure_one()
        if self.platform != 'youtube':
            return
            
        self._refresh_youtube_token()
        if not self.api_token:
            return
            
        import requests
        url = "https://www.googleapis.com/youtube/v3/commentThreads"
        params = {
            'part': 'snippet',
            'allThreadsRelatedToChannelId': self.youtube_channel_id,
            'maxResults': 50,
            'access_token': self.api_token
        }
        
        try:
            res = requests.get(url, params=params, timeout=10)
            if not res.ok:
                return
                
            data = res.json()
            for item in data.get('items', []):
                snippet = item['snippet']['topLevelComment']['snippet']
                comment_id = item['id']
                video_id = item['snippet'].get('videoId')
                text_original = snippet.get('textOriginal')
                author_id = snippet.get('authorChannelId', {}).get('value')
                author_name = snippet.get('authorDisplayName')
                
                if not author_id or author_id == self.youtube_channel_id:
                    continue # Skip our own comments
                    
                # Check if comment already exists
                existing_msg = self.env['social.media.message'].search([('platform_message_id', '=', comment_id)], limit=1)
                if existing_msg:
                    continue
                    
                # Find or create Partner
                partner = self.env['res.partner'].search([('ref', '=', f'yt_{author_id}')], limit=1)
                if not partner:
                    partner = self.env['res.partner'].create({
                        'name': author_name or f"YouTube User {author_id}",
                        'ref': f'yt_{author_id}'
                    })
                    
                # Find or create Conversation
                conversation = self.env['social.media.conversation'].search([
                    ('social_user_id', '=', author_id),
                    ('account_id', '=', self.id)
                ], limit=1)
                
                if not conversation:
                    conversation = self.env['social.media.conversation'].create({
                        'account_id': self.id,
                        'social_user_id': author_id,
                        'partner_id': partner.id,
                        'state': 'bot'
                    })
                    
                # Find Linked Post
                linked_post = False
                if video_id:
                    post_line = self.env['social.media.post.line'].search([('platform_post_id', '=', video_id)], limit=1)
                    if post_line:
                        linked_post = post_line.post_id

                # Create Message
                msg = self.env['social.media.message'].create({
                    'conversation_id': conversation.id,
                    'message_type': 'incoming',
                    'content': f"[YORUM]: {text_original}",
                    'is_read': False,
                    'platform_message_id': comment_id,
                    'post_link': f"https://youtube.com/watch?v={video_id}" if video_id else False,
                    'post_id': linked_post.id if linked_post else False
                })
                conversation.write({'unread_count': conversation.unread_count + 1})
                
                # AI Routing logic moved to Cron job
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"YouTube Sync Error: {e}")

    def _trigger_youtube_ai_response(self, conversation, user_message, account, comment_id, video_id):
        ai_provider = self.env['social.media.ai.provider'].sudo()
        
        system_context = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.system_prompt', 'Sen profesyonel bir müşteri temsilcisisin. Sorulara kısa ve nazik cevaplar ver.')
        system_context += f"\n\nKullanıcı YouTube üzerinden yorum yazıyor. ÖNEMLİ KURAL: Mesajlarında KESİNLİKLE '**' veya '*' gibi markdown kalınlaştırma işaretleri KULLANMA. Bunun yerine maddeleri ayırmak için şık emojiler (👗, 💳, 📦, 🛍️ vb.) ve temiz satır boşlukları kullanarak çok profesyonel ve zarif bir görünüm sağla."
        
        # Check if the video is linked to a post in Odoo to get products
        linked_post = False
        if video_id:
            post_line = self.env['social.media.post.line'].search([('platform_post_id', '=', video_id)], limit=1)
            if post_line:
                linked_post = post_line.post_id

        whatsapp_number = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.whatsapp_number', '').strip()
        wa_link = f"https://wa.me/{whatsapp_number}?text=Merhaba+YouTube'dan+geliyorum" if whatsapp_number else ""

        if linked_post and hasattr(linked_post, 'product_tmpl_ids') and linked_post.product_tmpl_ids:
            system_context += "\n\nKULLANICININ YORUM YAPTIĞI VİDEODAKİ ÜRÜNLER:"
            system_context += "\n(LÜTFEN DİKKAT: Yorumlar herkese açık olduğu için FİYAT BİLGİSİ VERME. Sadece stok durumunu ve ürün özelliklerini belirt. Ardından detaylı bilgi ve sipariş için WhatsApp hattına yönlendir.)\n"
            
            for p in linked_post.product_tmpl_ids:
                stock = p.qty_available if hasattr(p, 'qty_available') else 10
                stock_text = f"{stock} Adet (Tükenmek üzere, aciliyet bildir!)" if 0 < stock < 5 else f"{stock} Adet" if stock > 0 else "Stokta Yok"
                
                system_context += f"\n\n- Ürün: {p.name}"
                system_context += f"\n  Stok Durumu: {stock_text}"
                
        if wa_link:
            system_context += f"\n\nMesajının sonuna MUTLAKA şu WhatsApp sipariş ve detaylı bilgi linkini ekle: {wa_link}"

        reply_text = ai_provider.generate_response(user_message, system_context)
        
        if reply_text and not str(reply_text).startswith("[ERROR]"):
            if "[DEVRET]" in reply_text.upper():
                reply_text = reply_text.replace("[DEVRET]", "").replace("[devret]", "").strip()
                conversation.sudo().write({'state': 'open'})
                if not reply_text:
                    reply_text = f"Detaylı bilgi için müşteri temsilcimize WhatsApp üzerinden ulaşabilirsiniz: {wa_link}"

            self.env['social.media.message'].create({
                'conversation_id': conversation.id,
                'message_type': 'outgoing',
                'content': reply_text,
                'is_read': True
            })
            
            self._send_youtube_comment_reply(comment_id, reply_text, account)

    def _send_youtube_comment_reply(self, comment_id, reply_text, account):
        import requests
        import logging
        url = "https://www.googleapis.com/youtube/v3/comments?part=snippet"
        headers = {
            'Authorization': f'Bearer {account.api_token}',
            'Content-Type': 'application/json'
        }
        payload = {
            "snippet": {
                "parentId": comment_id,
                "textOriginal": reply_text
            }
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if not res.ok:
                logging.getLogger(__name__).error(f"Failed to reply to YouTube comment {comment_id}: {res.status_code} - {res.text}")
        except Exception as e:
            logging.getLogger(__name__).error(f"Exception replying to YouTube comment: {e}")

    def _send_meta_comment_reply(self, comment_id, message_text):
        """ Send a public reply to a Meta comment """
        if not self.api_token: return
        import requests, logging
        endpoint = "replies" if self.platform == 'instagram' else "comments"
        url = f"https://graph.facebook.com/v19.0/{comment_id}/{endpoint}"
        payload = {"message": message_text, "access_token": self.api_token}
        try:
            requests.post(url, data=payload, timeout=10)
        except Exception as e:
            logging.getLogger(__name__).error(f"Exception replying to Meta comment: {e}")

    def _send_meta_private_reply(self, comment_id, message_text, attachment=None, attachment_name=None):
        """ Send a private DM reply based on a comment """
        if not self.api_token: return False
        import requests, logging, json, base64
        url = "https://graph.facebook.com/v19.0/me/messages"
        
        success = True
        if attachment:
            payload = {
                "recipient": json.dumps({"comment_id": comment_id}),
                "message": json.dumps({"attachment": {"type": "image", "payload": {"is_reusable": True}}})
            }
            files = {
                'filedata': (attachment_name or 'image.jpg', base64.b64decode(attachment), 'image/jpeg')
            }
            try:
                res = requests.post(url, data=payload, files=files, params={"access_token": self.api_token}, timeout=20)
                if not res.ok:
                    logging.getLogger(__name__).error(f"Meta Private Image Error: {res.status_code} - {res.text}")
                    success = False
            except Exception as e:
                logging.getLogger(__name__).error(f"Exception sending Meta private image: {e}")
                success = False

        if message_text and message_text.strip():
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_token}"}
            payload = {"recipient": {"comment_id": comment_id}, "message": {"text": message_text}}
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=10)
                if not res.ok:
                    logging.getLogger(__name__).error(f"Meta Private Text Error: {res.status_code} - {res.text}")
                    success = False
            except Exception as e:
                logging.getLogger(__name__).error(f"Exception sending Meta private text: {e}")
                success = False
        return success

    def _send_meta_message(self, recipient_id, message_text, attachment=None, attachment_name=None):
        """ Send a DM using Meta Graph API """
        if not self.api_token: return
        import requests, logging, json, base64
        url = "https://graph.facebook.com/v19.0/me/messages"
        
        if attachment:
            payload = {
                "recipient": json.dumps({"id": recipient_id}),
                "message": json.dumps({"attachment": {"type": "image", "payload": {"is_reusable": True}}})
            }
            files = {
                'filedata': (attachment_name or 'image.jpg', base64.b64decode(attachment), 'image/jpeg')
            }
            try:
                res = requests.post(url, data=payload, files=files, params={"access_token": self.api_token}, timeout=20)
                if not res.ok:
                    logging.getLogger(__name__).error(f"Meta Image Error: {res.status_code} - {res.text}")
            except Exception as e:
                logging.getLogger(__name__).error(f"Exception sending Meta image: {e}")
                
        if message_text and message_text.strip():
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_token}"}
            payload = {"recipient": {"id": recipient_id}, "message": {"text": message_text}}
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=10)
                if not res.ok:
                    logging.getLogger(__name__).error(f"Meta Text Error: {res.status_code} - {res.text}")
            except Exception as e:
                logging.getLogger(__name__).error(f"Exception sending Meta text: {e}")

    def _send_whatsapp_message(self, recipient_id, message_text, attachment=None, attachment_name=None):
        """ Send WhatsApp message via Evolution API """
        if not self.api_token or not self.whatsapp_api_url or not self.whatsapp_instance_name:
            import logging
            logging.getLogger(__name__).warning("WhatsApp credentials missing (API Token, URL or Instance Name)")
            return False

        import requests
        import logging

        base_url = self.whatsapp_api_url.rstrip('/')
        instance_name = self.whatsapp_instance_name

        headers = {
            'apikey': self.api_token,
            'Content-Type': 'application/json'
        }

        # Evolution API accepts number in pure digits or with @s.whatsapp.net
        clean_number = ''.join(filter(str.isdigit, str(recipient_id)))
        remote_jid = f"{clean_number}@s.whatsapp.net"

        success = True

        # Send Media if attachment exists
        if attachment:
            url = f"{base_url}/message/sendMedia/{instance_name}"
            # Basic mimetype detection
            mimetype = "application/octet-stream"
            mediatype = "document"
            if attachment_name:
                name_lower = attachment_name.lower()
                if name_lower.endswith('.jpg') or name_lower.endswith('.jpeg'):
                    mimetype, mediatype = "image/jpeg", "image"
                elif name_lower.endswith('.png'):
                    mimetype, mediatype = "image/png", "image"
                elif name_lower.endswith('.pdf'):
                    mimetype, mediatype = "application/pdf", "document"
                elif name_lower.endswith('.mp4'):
                    mimetype, mediatype = "video/mp4", "video"

            # Check if attachment is bytes (decode to str if needed)
            import base64
            media_b64 = attachment.decode('utf-8') if isinstance(attachment, bytes) else attachment
            
            # Evolution API expects base64 data to have data prefix if mediatype is specified, 
            # or just raw base64. Best practice is raw base64 and explicit mimetype.
            # But the documentation specifies sending base64 in "media" field.
            # Adding data URL format to be safe: data:image/jpeg;base64,...
            if not media_b64.startswith('data:'):
                media_b64 = f"data:{mimetype};base64,{media_b64}"

            media_message = {
                "number": remote_jid,
                "mediatype": mediatype,
                "mimetype": mimetype,
                "caption": message_text if message_text else "",
                "media": media_b64,
                "fileName": attachment_name or "file"
            }
            try:
                res = requests.post(url, headers=headers, json=media_message, timeout=20)
                if not res.ok:
                    logging.getLogger(__name__).error(f"Evolution API Media Error: {res.status_code} - {res.text}")
                    success = False
                else:
                    return True # If text is sent as caption, we are done
            except Exception as e:
                logging.getLogger(__name__).error(f"Exception sending Evolution API media: {e}")
                success = False

        # Send Text
        if message_text:
            url = f"{base_url}/message/sendText/{instance_name}"
            text_message = {
                "number": remote_jid,
                "text": message_text
            }
            try:
                res = requests.post(url, headers=headers, json=text_message, timeout=10)
                if not res.ok:
                    logging.getLogger(__name__).error(f"Evolution API Text Error: {res.status_code} - {res.text}")
                    success = False
            except Exception as e:
                logging.getLogger(__name__).error(f"Exception sending Evolution API text: {e}")
                success = False

        return success

    def action_test_whatsapp(self):
        """ Send a test message to the configured phone number """
        from odoo import exceptions
        self.ensure_one()
        if self.platform != 'whatsapp':
            raise exceptions.UserError("Bu özellik sadece WhatsApp hesapları için geçerlidir.")
            
        test_number = self.phone_number
        if not test_number:
            raise exceptions.UserError("Lütfen önce formda 'Phone Number' alanını doldurun (örn: 905551234567)")
            
        success = self._send_whatsapp_message(test_number, "Merhaba! Odoo'dan Evolution API test mesajıdır. 🚀")
        if success:
            raise exceptions.UserError("Test mesajı başarıyla gönderildi!")
        else:
            raise exceptions.UserError("Mesaj gönderilemedi. Lütfen logları ve API bağlantısını kontrol edin.")

    def action_fix_youtube_errors(self):
        self.ensure_one()
        if self.platform != 'youtube':
            return
            
        self._refresh_youtube_token()
        error_msgs = self.env['social.media.message'].search([
            ('message_type', '=', 'outgoing'),
            ('content', 'ilike', 'An error occurred with the Gemini service.')
        ])
        
        import requests
        ai_provider = self.env['social.media.ai.provider'].sudo()
        
        system_context = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.system_prompt', 'Sen profesyonel bir müşteri temsilcisisin. Sorulara kısa ve nazik cevaplar ver.')
        system_context += f"\n\nKullanıcı YouTube üzerinden yorum yazıyor. ÖNEMLİ KURAL: Mesajlarında KESİNLİKLE '**' veya '*' gibi markdown kalınlaştırma işaretleri KULLANMA. Bunun yerine maddeleri ayırmak için şık emojiler (👗, 💳, 📦, 🛍️ vb.) ve temiz satır boşlukları kullanarak çok profesyonel ve zarif bir görünüm sağla."
        whatsapp_number = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.whatsapp_number', '').strip()
        wa_link = f"https://wa.me/{whatsapp_number}?text=Merhaba+YouTube'dan+geliyorum" if whatsapp_number else ""
        if wa_link:
            system_context += f"\n\nMesajının sonuna MUTLAKA şu WhatsApp sipariş ve detaylı bilgi linkini ekle: {wa_link}"
        
        for msg in error_msgs:
            # Find the incoming message before this
            incoming = self.env['social.media.message'].search([
                ('conversation_id', '=', msg.conversation_id.id),
                ('message_type', '=', 'incoming'),
                ('date', '<=', msg.date)
            ], order='date desc', limit=1)
            
            if not incoming or not incoming.platform_message_id:
                continue
                
            parent_id = incoming.platform_message_id
            
            # Generate new reply
            user_text = incoming.content.replace("[YORUM]:", "").strip()
            new_reply = ai_provider.generate_response(user_text, system_context)
            
            if not new_reply or str(new_reply).startswith("[ERROR]"):
                continue
                
            if "[DEVRET]" in new_reply.upper():
                new_reply = new_reply.replace("[DEVRET]", "").replace("[devret]", "").strip()
            if not new_reply:
                new_reply = f"Detaylı bilgi için WhatsApp üzerinden ulaşabilirsiniz: {wa_link}"
            
            # Fetch replies from YouTube
            url = f"https://www.googleapis.com/youtube/v3/comments?parentId={parent_id}&part=snippet&access_token={self.api_token}"
            res = requests.get(url).json()
            reply_id_to_update = None
            
            for item in res.get('items', []):
                snippet = item.get('snippet', {})
                if snippet.get('authorChannelId', {}).get('value') == self.youtube_channel_id:
                    reply_id_to_update = item['id']
                    break
                    
            if reply_id_to_update:
                put_url = "https://www.googleapis.com/youtube/v3/comments?part=snippet"
                headers = {
                    'Authorization': f'Bearer {self.api_token}',
                    'Content-Type': 'application/json'
                }
                payload = {
                    "id": reply_id_to_update,
                    "snippet": {
                        "textOriginal": new_reply
                    }
                }
                update_res = requests.put(put_url, headers=headers, json=payload)
                if update_res.ok:
                    msg.content = new_reply
