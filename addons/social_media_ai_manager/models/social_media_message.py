# -*- coding: utf-8 -*-
from odoo import models, fields, api

class SocialMediaMessage(models.Model):
    _name = 'social.media.message'
    _description = 'Social Media Message / Comment'
    _order = 'date asc'

    conversation_id = fields.Many2one('social.media.conversation', string="Conversation", required=True, ondelete='cascade')
    platform_message_id = fields.Char(string="Platform Message ID", help="Unique ID from WhatsApp/Meta")
    post_link = fields.Char(string="Post URL", help="Direct link to the post if this is a comment")
    post_id = fields.Many2one('social.media.post', string="Linked Post", help="The social media post this message belongs to")
    
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

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        
        # If created manually from the UI, send to the platform!
        if not self.env.context.get('from_ai_cron'):
            import logging
            _logger = logging.getLogger(__name__)
            for rec in records:
                if rec.message_type == 'outgoing':
                    account = rec.conversation_id.account_id
                    conv = rec.conversation_id
                    
                    # Find last incoming message to determine if we reply to a comment or DM
                    last_incoming = self.search([
                        ('conversation_id', '=', conv.id),
                        ('message_type', '=', 'incoming')
                    ], order='date desc', limit=1)
                    
                    is_comment = last_incoming and last_incoming.content and last_incoming.content.startswith('[YORUM]:')
                    comment_id = last_incoming.platform_message_id if is_comment else False

                    try:
                        if account.platform == 'youtube':
                            if comment_id:
                                account._send_youtube_comment_reply(comment_id, rec.content, account)
                        elif account.platform in ['facebook', 'instagram']:
                            if is_comment and comment_id:
                                # For human replies, we just send a private message to the comment
                                account._send_meta_private_reply(comment_id, rec.content)
                            else:
                                account._send_meta_message(conv.social_user_id, rec.content)
                        elif account.platform == 'whatsapp':
                            account._send_whatsapp_message(conv.social_user_id, rec.content)
                    except Exception as e:
                        _logger.error(f"Failed to send manual message for conversation {conv.id}: {e}")
                        
        return records

    @api.model
    def _cron_process_ai_queue(self, limit=50):
        import logging
        _logger = logging.getLogger(__name__)
        
        # 1. Find unprocessed incoming messages from the last 10 minutes (to prevent spamming old messages)
        from datetime import datetime, timedelta
        from dateutil.relativedelta import relativedelta
        from odoo import fields
        ten_mins_ago = fields.Datetime.now() - relativedelta(minutes=10)
        
        messages = self.search([
            ('message_type', '=', 'incoming'),
            ('ai_processed', '=', False),
            ('conversation_id.state', '=', 'bot'),
            ('create_date', '>=', ten_mins_ago)
        ], limit=limit, order='create_date asc')
        
        if not messages:
            return
            
        ai_provider = self.env['social.media.ai.provider'].sudo()
        
        # Group by conversation to avoid multiple AI calls for consecutive messages (debouncing)
        conversations = messages.mapped('conversation_id')
        
        for conversation in conversations:
            try:
                # All unprocessed messages for this conversation in this batch
                conv_msgs = messages.filtered(lambda m: m.conversation_id.id == conversation.id)
                account = conversation.account_id
                
                # Combine user messages into one paragraph
                user_message = "\n".join([m.content.replace("[YORUM]:", "").strip() for m in conv_msgs])
                
                # Fetch Conversation History for AI Context
                past_messages = self.search([
                    ('conversation_id', '=', conversation.id),
                    ('id', 'not in', conv_msgs.ids)
                ], order='date desc', limit=6)
                
                if past_messages:
                    history_text = "\n".join([
                        f"{'Müşteri' if m.message_type == 'incoming' else 'Asistan'}: {m.content.replace('[YORUM]:', '').strip()}"
                        for m in reversed(past_messages)
                    ])
                    system_context += f"\n\nÖNCEKİ KONUŞMA GEÇMİŞİ (Bu konuşma geçmişine göre yanıt ver):\n{history_text}\n"
                
                # We use the LAST message for context (like which post they commented on)
                last_msg = conv_msgs[-1]
                
                # Setup Context
                system_context = self.env['ir.config_parameter'].sudo().get_param(
                    'social_media_ai.system_prompt', 
                    'Sen profesyonel bir müşteri temsilcisisin. Sorulara kısa ve nazik cevaplar ver.'
                )
                system_context += f"\n\nKullanıcı {account.platform} üzerinden yazıyor. ÖNEMLİ KURAL: Mesajlarında KESİNLİKLE '**' veya '*' gibi markdown kalınlaştırma işaretleri KULLANMA. Bunun yerine maddeleri ayırmak için şık emojiler (👗, 💳, 📦, 🛍️ vb.) ve temiz satır boşlukları kullanarak çok profesyonel ve zarif bir görünüm sağla."
                
                whatsapp_number = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.whatsapp_number', '').strip()
                wa_link = f"https://wa.me/{whatsapp_number}?text=Merhaba+{account.platform}'dan+geliyorum" if whatsapp_number else ""
                
                # Extract Product Info from Post
                linked_post = last_msg.post_id
                
                if linked_post and hasattr(linked_post, 'product_tmpl_ids') and linked_post.product_tmpl_ids:
                    system_context += "\n\nKULLANICININ YORUM YAPTIĞI GÖNDERİDEKİ ÜRÜNLER HAKKINDA DETAYLI BİLGİ:"
                    
                    if account.platform == 'youtube':
                        system_context += "\n(YOUTUBE İÇİN KURAL: Müşteriye ürünün adını, stok durumunu, beden/renk seçeneklerini ve aşağıda verilen sipariş linkini çok şık ve net bir şekilde listele. ASLA FİYAT BİLGİSİ VERME. En sona da her türlü soru için WhatsApp destek hattını ekle.)\n"
                    else:
                        system_context += "\n(INSTAGRAM/FACEBOOK İÇİN KURAL: Müşteriye ürünün adını, FİYATINI, stok durumunu, beden/renk seçeneklerini ve aşağıda verilen sipariş linkini çok şık ve net bir şekilde listele. En sona da her türlü soru için WhatsApp destek hattını ekle.)\n"

                    for p in linked_post.product_tmpl_ids:
                        stock = p.qty_available if hasattr(p, 'qty_available') else 10
                        stock_text = f"Sadece {int(stock)} adet kaldı, tükenmek üzere!" if 0 < stock < 5 else f"{int(stock)} Adet" if stock > 0 else "Stokta Yok"
                        
                        # Extract variants
                        variants = []
                        if hasattr(p, 'attribute_line_ids'):
                            for attr in p.attribute_line_ids:
                                vals = ", ".join(attr.value_ids.mapped('name'))
                                variants.append(f"{attr.attribute_id.name}: {vals}")
                        variant_text = " | ".join(variants) if variants else "Tek Çeşit"
                        
                        # Order Link (Prioritize Barcode)
                        search_query = p.barcode or p.default_code
                        if not search_query and p.product_variant_ids:
                            for variant in p.product_variant_ids:
                                if variant.barcode:
                                    search_query = variant.barcode
                                    break
                                elif variant.default_code and not search_query:
                                    search_query = variant.default_code
                                    
                        if not search_query:
                            search_query = p.name.replace(" ", "+")
                            
                        order_link = f"https://www.ugurlar.com/search?q={search_query}"
                        
                        system_context += f"\n\n- Ürün: {p.name}"
                        if account.platform != 'youtube':
                            system_context += f"\n  Fiyat: {p.list_price} TL"
                        system_context += f"\n  Stok Durumu: {stock_text}"
                        system_context += f"\n  Seçenekler: {variant_text}"
                        system_context += f"\n  Sipariş Linki: {order_link}"
                
                if wa_link:
                    system_context += f"\n\nMesajının sonuna MUTLAKA şu WhatsApp sipariş ve detaylı bilgi linkini ekle: {wa_link}"

                # Generate Reply ONCE for all consecutive messages
                reply_text = ai_provider.generate_response(user_message, system_context)
                
                if not reply_text or str(reply_text).startswith("[ERROR]"):
                    _logger.error(f"AI Provider error or empty reply for conversation {conversation.id}")
                    continue # Will retry next cron run
                    
                # Process Handoff
                if "[DEVRET]" in reply_text.upper():
                    reply_text = reply_text.replace("[DEVRET]", "").replace("[devret]", "").strip()
                    conversation.sudo().write({'state': 'open'})
                    if not reply_text:
                        reply_text = f"Detaylı bilgi için müşteri temsilcimize WhatsApp üzerinden ulaşabilirsiniz: {wa_link}"
                        
                # Create ONE Outgoing Message Record
                out_msg = self.with_context(from_ai_cron=True).create({
                    'conversation_id': conversation.id,
                    'message_type': 'outgoing',
                    'content': reply_text,
                    'is_read': True
                })
                
                # Send back to platform
                if account.platform == 'youtube':
                    if last_msg.platform_message_id: # it's a comment
                        account._send_youtube_comment_reply(last_msg.platform_message_id, reply_text, account)
                elif account.platform in ['facebook', 'instagram']:
                    # Separate comment logic to find the exact comment ID
                    comment_msgs = [m for m in conv_msgs if m.content.startswith('[YORUM]:')]
                    if comment_msgs:
                        last_comment_id = comment_msgs[-1].platform_message_id
                        if last_comment_id:
                            auto_reply = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.comment_auto_reply', 'Merhaba, detaylı bilgi DM üzerinden iletilmiştir.')
                            account._send_meta_comment_reply(last_comment_id, auto_reply)
                            account._send_meta_private_reply(last_comment_id, reply_text)
                    else:
                        account._send_meta_message(conversation.social_user_id, reply_text)
                elif account.platform == 'whatsapp':
                    account._send_whatsapp_message(conversation.social_user_id, reply_text)
                    
                # Mark ALL messages in this batch as processed
                for m in conv_msgs:
                    m.ai_processed = True
                
                # Commit progress (Odoo 19 Best Practice for crons)
                self.env.cr.commit()
                
            except Exception as e:
                _logger.error(f"Failed to process AI queue for conversation {conversation.id}: {e}")
                self.env.cr.rollback()
