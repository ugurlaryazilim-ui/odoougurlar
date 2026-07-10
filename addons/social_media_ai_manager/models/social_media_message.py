# -*- coding: utf-8 -*-
from odoo import models, fields, api

class SocialMediaMessage(models.Model):
    _name = 'social.media.message'
    _description = 'Social Media Message / Comment'
    _order = 'date asc'

    conversation_id = fields.Many2one('social.media.conversation', string="Conversation", required=True, ondelete='cascade')
    platform_message_id = fields.Char(string="Platform Message ID", help="Unique ID from WhatsApp/Meta")
    post_link = fields.Char(string="Post URL", help="Direct link to the post if this is a comment")
    
    message_type = fields.Selection([
        ('incoming', 'Incoming (Customer)'),
        ('outgoing', 'Outgoing (Agent/AI)'),
        ('system', 'System Note')
    ], string="Direction", required=True)
    
    content = fields.Text(string="Message Content", required=True)
    date = fields.Datetime(string="Date", default=fields.Datetime.now)
    
    is_read = fields.Boolean(string="Read", default=False)
    author_id = fields.Many2one('res.users', string="Sent By (Agent)", help="If empty and outgoing, sent by AI")
    ai_processed = fields.Boolean(string="AI Processed", default=False, help="True if AI has answered this incoming message")

    @api.model
    def _cron_process_ai_queue(self, limit=50):
        import logging
        _logger = logging.getLogger(__name__)
        
        # 1. Find unprocessed incoming messages
        messages = self.search([
            ('message_type', '=', 'incoming'),
            ('ai_processed', '=', False),
            ('conversation_id.state', '=', 'bot')
        ], limit=limit, order='create_date asc')
        
        if not messages:
            return
            
        ai_provider = self.env['social.media.ai.provider'].sudo()
        
        for msg in messages:
            try:
                conversation = msg.conversation_id
                account = conversation.account_id
                
                # Setup Context
                system_context = self.env['ir.config_parameter'].sudo().get_param(
                    'social_media_ai.system_prompt', 
                    'Sen profesyonel bir müşteri temsilcisisin. Sorulara kısa ve nazik cevaplar ver.'
                )
                system_context += f"\n\nKullanıcı {account.platform} üzerinden yazıyor. ÖNEMLİ KURAL: Mesajlarında KESİNLİKLE '**' veya '*' gibi markdown kalınlaştırma işaretleri KULLANMA. Bunun yerine maddeleri ayırmak için şık emojiler (👗, 💳, 📦, 🛍️ vb.) ve temiz satır boşlukları kullanarak çok profesyonel ve zarif bir görünüm sağla."
                
                whatsapp_number = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.whatsapp_number', '').strip()
                wa_link = f"https://wa.me/{whatsapp_number}?text=Merhaba+{account.platform}'dan+geliyorum" if whatsapp_number else ""
                
                # Extract Product Info from Post if applicable (YouTube/Meta)
                linked_post = False
                if msg.post_link and 'youtube.com/watch?v=' in msg.post_link:
                    video_id = msg.post_link.split('v=')[-1]
                    post_line = self.env['social.media.post.line'].search([('platform_post_id', '=', video_id)], limit=1)
                    if post_line: linked_post = post_line.post_id
                elif msg.platform_message_id and account.platform in ['facebook', 'instagram']:
                    # We might not have the direct post ID stored for Meta comments easily here,
                    # but if we do, it would be checked here. For simplicity, we skip linking for Meta in cron unless stored.
                    pass
                
                if linked_post and hasattr(linked_post, 'product_tmpl_ids') and linked_post.product_tmpl_ids:
                    system_context += "\n\nKULLANICININ YORUM YAPTIĞI GÖNDERİDEKİ ÜRÜNLER:"
                    for p in linked_post.product_tmpl_ids:
                        stock = p.qty_available if hasattr(p, 'qty_available') else 10
                        stock_text = f"{stock} Adet (Tükenmek üzere, aciliyet bildir!)" if 0 < stock < 5 else f"{stock} Adet" if stock > 0 else "Stokta Yok"
                        system_context += f"\n\n- Ürün: {p.name}\n  Stok Durumu: {stock_text}"
                
                if wa_link:
                    system_context += f"\n\nMesajının sonuna MUTLAKA şu WhatsApp sipariş ve detaylı bilgi linkini ekle: {wa_link}"

                user_message = msg.content.replace("[YORUM]:", "").strip()
                
                # Generate Reply
                reply_text = ai_provider.generate_response(user_message, system_context)
                
                if not reply_text or str(reply_text).startswith("[ERROR]"):
                    _logger.error(f"AI Provider error or empty reply for message {msg.id}")
                    continue # Will retry next cron run
                    
                # Process Handoff
                if "[DEVRET]" in reply_text.upper():
                    reply_text = reply_text.replace("[DEVRET]", "").replace("[devret]", "").strip()
                    conversation.sudo().write({'state': 'open'})
                    if not reply_text:
                        reply_text = f"Detaylı bilgi için müşteri temsilcimize WhatsApp üzerinden ulaşabilirsiniz: {wa_link}"
                        
                # Create Outgoing Message Record
                out_msg = self.create({
                    'conversation_id': conversation.id,
                    'message_type': 'outgoing',
                    'content': reply_text,
                    'is_read': True
                })
                
                # Send back to platform
                if account.platform == 'youtube':
                    if msg.platform_message_id: # it's a comment
                        account._send_youtube_comment_reply(msg.platform_message_id, reply_text, account)
                elif account.platform in ['facebook', 'instagram']:
                    if msg.platform_message_id: # it's a comment
                        auto_reply = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.comment_auto_reply', 'Merhaba, detaylı bilgi DM üzerinden iletilmiştir.')
                        account._send_meta_comment_reply(msg.platform_message_id, auto_reply)
                        account._send_meta_private_reply(msg.platform_message_id, reply_text)
                    else: # it's a DM
                        account._send_meta_message(conversation.social_user_id, reply_text)
                elif account.platform == 'whatsapp':
                    account._send_whatsapp_message(conversation.social_user_id, reply_text)
                    
                # Mark as processed
                msg.ai_processed = True
                
                # Commit progress (Odoo 19 Best Practice for crons)
                self.env.cr.commit()
                
            except Exception as e:
                _logger.error(f"Failed to process AI queue for message {msg.id}: {e}")
                self.env.cr.rollback()
