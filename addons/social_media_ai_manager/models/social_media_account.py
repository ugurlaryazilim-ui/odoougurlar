# -*- coding: utf-8 -*-
from odoo import models, fields, exceptions

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
                    
                # Create Message
                msg = self.env['social.media.message'].create({
                    'conversation_id': conversation.id,
                    'message_type': 'incoming',
                    'content': f"[YORUM]: {text_original}",
                    'is_read': False,
                    'platform_message_id': comment_id,
                    'post_link': f"https://youtube.com/watch?v={video_id}" if video_id else False
                })
                conversation.write({'unread_count': conversation.unread_count + 1})
                
                # AI Routing
                if conversation.state == 'bot':
                    self._trigger_youtube_ai_response(conversation, text_original, self, comment_id, video_id)
        except Exception as e:
            pass

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
        
        if reply_text:
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
