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
    
    content = fields.Text(string="Message Content", required=False)
    attachment = fields.Binary(string="Attachment")
    attachment_name = fields.Char(string="Attachment Name")
    has_attachment = fields.Boolean(compute="_compute_has_attachment")
    
    date = fields.Datetime(string="Date", default=fields.Datetime.now)
    
    is_read = fields.Boolean(string="Read", default=False)
    author_id = fields.Many2one('res.users', string="Sent By (Agent)", help="If empty and outgoing, sent by AI")
    ai_processed = fields.Boolean(string="AI Processed", default=False, help="True if AI has answered this incoming message")

    @api.depends('attachment')
    def _compute_has_attachment(self):
        for rec in self:
            rec.has_attachment = bool(rec.attachment)

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
                                if rec.attachment:
                                    _logger.warning("YouTube comments do not support image replies. Sending text only.")
                                account._send_youtube_comment_reply(comment_id, rec.content, account)
                        elif account.platform in ['facebook', 'instagram']:
                            if is_comment and comment_id:
                                # For human replies, we try to send a private message to the comment
                                success = account._send_meta_private_reply(comment_id, rec.content, attachment=rec.attachment, attachment_name=rec.attachment_name)
                                if not success:
                                    # Meta only allows ONE private reply per comment. If it fails, fallback to public comment.
                                    account._send_meta_comment_reply(comment_id, rec.content)
                            else:
                                account._send_meta_message(conv.social_user_id, rec.content, attachment=rec.attachment, attachment_name=rec.attachment_name)
                        elif account.platform == 'whatsapp':
                            account._send_whatsapp_message(conv.social_user_id, rec.content, attachment=rec.attachment, attachment_name=rec.attachment_name)
                    except Exception as e:
                        _logger.error(f"Failed to send manual message for conversation {conv.id}: {e}")
                        
        return records

    @api.model
    def search_product_for_chat(self, query):
        """ Used by OWL Component to search products and return formatted chat message """
        Product = self.env['product.product']
        domain = ['|', ('barcode', '=', query), ('name', 'ilike', query)]
        products = Product.search(domain, limit=10)
        
        results = []
        for p in products:
            tmpl = p.product_tmpl_id
            stock = tmpl.qty_available if hasattr(tmpl, 'qty_available') else p.qty_available if hasattr(p, 'qty_available') else 10
            stock_text = f"Sadece {int(stock)} adet kaldı, tükenmek üzere!" if 0 < stock < 5 else f"{int(stock)} Adet" if stock > 0 else "Stokta Yok"
            
            variants = []
            if hasattr(tmpl, 'attribute_line_ids'):
                allowed_attrs = ['renk', 'beden', 'numara']
                for attr in tmpl.attribute_line_ids:
                    attr_name = attr.attribute_id.name
                    if any(a in attr_name.lower() for a in allowed_attrs):
                        vals = ", ".join(attr.value_ids.mapped('name'))
                        variants.append(f"{attr_name}: {vals}")
            variant_text = " | ".join(variants) if variants else "Tek Çeşit"
            
            search_query = p.barcode or p.default_code
            if not search_query:
                for variant in tmpl.product_variant_ids:
                    if variant.barcode:
                        search_query = variant.barcode
                        break
                    elif variant.default_code and not search_query:
                        search_query = variant.default_code
            if not search_query:
                search_query = tmpl.name.replace(" ", "+")
                
            order_link = f"https://www.ugurlar.com/search?q={search_query}"
            
            chat_text = f"👗 Ürün: {tmpl.name}\n"
            chat_text += f"💰 Fiyat: {tmpl.list_price} TL\n"
            chat_text += f"📦 Stok Durumu: {stock_text}\n"
            if variants:
                chat_text += f"🎨 Seçenekler: {variant_text}\n"
            chat_text += f"🔗 Sipariş Linki: {order_link}\n"
            
            results.append({
                'id': p.id,
                'display_name': p.display_name,
                'barcode': p.barcode or '-',
                'list_price': p.list_price,
                'qty_available': stock,
                'chat_text': chat_text
            })
            
    @api.model
    def _cron_process_ai_queue(self, limit=50):
        import logging
        _logger = logging.getLogger(__name__)
        
        # Process incoming messages from the last 24 hours (to avoid skipping if AI API goes down temporarily)
        from datetime import datetime, timedelta
        from dateutil.relativedelta import relativedelta
        from odoo import fields
        one_day_ago = fields.Datetime.now() - relativedelta(days=1)
        
        # First: Get messages from bot-state conversations (DMs)
        dm_messages = self.search([
            ('message_type', '=', 'incoming'),
            ('ai_processed', '=', False),
            ('conversation_id.state', '=', 'bot'),
            ('create_date', '>=', one_day_ago),
            ('content', 'not like', '[YORUM]:%')
        ], limit=limit, order='create_date asc')
        
        # Second: Get COMMENT messages regardless of conversation state
        # Comments should always be replied to even if conversation was handed off
        comment_messages = self.search([
            ('message_type', '=', 'incoming'),
            ('ai_processed', '=', False),
            ('content', 'like', '[YORUM]:%'),
            ('create_date', '>=', one_day_ago)
        ], limit=limit, order='create_date asc')
        
        messages = dm_messages | comment_messages
        
        if not messages:
            return
            
        ai_provider = self.env['social.media.ai.provider'].sudo()
        conversations = messages.mapped('conversation_id')
        
        import time
        consecutive_429s = 0
        MAX_CONSECUTIVE_429S = 3  # 3 ard arda 429 alırsak dur
        
        for conversation in conversations:
            # Rate limit: 429 hataları arka arkaya geliyorsa dur
            if consecutive_429s >= MAX_CONSECUTIVE_429S:
                _logger.warning(
                    'Gemini 429 rate limit: %d ard arda hata, kalan konuşmalar sonraki cron döngüsüne bırakılıyor',
                    consecutive_429s
                )
                break
            
            try:
                account = conversation.account_id
                conv_msgs = messages.filtered(lambda m: m.conversation_id.id == conversation.id)
                
                # Separate comments and DMs
                comment_msgs = conv_msgs.filtered(lambda m: m.content and m.content.startswith('[YORUM]:'))
                dm_msgs = conv_msgs - comment_msgs
                
                # We need to process each comment separately because they might be on different posts
                batches_to_process = []
                for c_msg in comment_msgs:
                    batches_to_process.append([c_msg])
                    
                # Group all DMs together to avoid replying 5 times if user sends 5 short messages
                if dm_msgs:
                    batches_to_process.append(list(dm_msgs))
                    
                for batch in batches_to_process:
                    last_msg = batch[-1]
                    # Combine user messages into one paragraph for this batch
                    user_message = "\n".join([m.content.replace("[YORUM]:", "").strip() for m in batch])
                    
                    # Fetch Conversation History for AI Context
                    # For comments: only fetch history from the SAME post to avoid context confusion
                    is_comment = any(m.content and m.content.startswith('[YORUM]:') for m in batch)
                    
                    if is_comment and getattr(last_msg, 'post_id', None):
                        # Only get past messages from the same post
                        past_messages = self.search([
                            ('conversation_id', '=', conversation.id),
                            ('post_id', '=', last_msg.post_id.id),
                            ('id', 'not in', [m.id for m in batch])
                        ], order='date desc', limit=6)
                    else:
                        past_messages = self.search([
                            ('conversation_id', '=', conversation.id),
                            ('id', 'not in', [m.id for m in batch])
                        ], order='date desc', limit=6)
                    
                    system_context = self.env['ir.config_parameter'].sudo().get_param(
                        'social_media_ai.system_prompt', 
                        'Sen profesyonel bir müşteri temsilcisisin. Sorulara kısa ve nazik cevaplar ver.'
                    )
                    
                    if past_messages:
                        history_text = "\n".join([
                            f"{'Müşteri' if m.message_type == 'incoming' else 'Asistan'}: {m.content.replace('[YORUM]:', '').strip()}"
                            for m in reversed(past_messages)
                        ])
                        system_context += f"\n\nÖNCEKİ KONUŞMA GEÇMİŞİ (Bu konuşma geçmişine göre yanıt ver):\n{history_text}\n"
                    
                    system_context += f"\n\nKullanıcı {account.platform.capitalize()} üzerinden yazıyor. ÖNEMLİ KURAL: Mesajlarında KESİNLİKLE '**' veya '*' gibi markdown kalınlaştırma işaretleri KULLANMA. Bunun yerine maddeleri ayırmak için şık emojiler (👗, 💳, 📦, 🛍️ vb.) ve temiz satır boşlukları kullanarak çok profesyonel ve zarif bir görünüm sağla."
                    
                    # Setup WhatsApp Link with Context
                    whatsapp_number = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.whatsapp_number', '').strip()
                    linked_post = last_msg.post_id
                    
                    wa_text = f"Merhaba, {account.platform.capitalize()}'dan geliyorum."
                    if last_msg.post_link:
                        wa_text += f"\nGeldiğim Link: {last_msg.post_link}"
                        
                    if linked_post and hasattr(linked_post, 'product_tmpl_ids') and linked_post.product_tmpl_ids:
                        product_names = ", ".join([p.name for p in linked_post.product_tmpl_ids])
                        wa_text += f"\nİlgilendiğim Ürün(ler): {product_names}"
                    
                    import urllib.parse
                    encoded_wa_text = urllib.parse.quote(wa_text)
                    wa_link = f"https://wa.me/{whatsapp_number}?text={encoded_wa_text}" if whatsapp_number else ""
                    
                    # Extract Product Info from Post
                    if linked_post and hasattr(linked_post, 'product_tmpl_ids') and linked_post.product_tmpl_ids:
                        system_context += "\n\nKULLANICININ YORUM YAPTIĞI GÖNDERİDEKİ ÜRÜNLER HAKKINDA DETAYLI BİLGİ:"
                        
                        if account.platform == 'youtube':
                            system_context += "\n(YOUTUBE İÇİN KESİN KURAL: Müşteri sadece 'Bilgi alabilir miyim' veya 'Fiyat nedir' yazsa bile, müşteriye soru sormadan DOĞRUDAN aşağıdaki ürünlerin adını, stok durumunu, seçeneklerini ve sipariş linkini listele. YOUTUBE'DA ASLA FİYAT BİLGİSİ YAZMA! Sadece stok ve link verip en sona WhatsApp hattını ekle.)\n"
                        else:
                            system_context += "\n(INSTAGRAM/FACEBOOK İÇİN KESİN KURAL: Müşteri sadece 'Bilgi alabilir miyim' veya 'Fiyat nedir' yazsa bile, müşteriye soru sormadan DOĞRUDAN aşağıdaki ürünlerin adını, FİYATINI, stok durumunu, seçeneklerini ve sipariş linkini listele. En sona WhatsApp hattını ekle.)\n"
    
                        for p in linked_post.product_tmpl_ids:
                            stock = p.qty_available if hasattr(p, 'qty_available') else 10
                            stock_text = f"Sadece {int(stock)} adet kaldı, tükenmek üzere!" if 0 < stock < 5 else f"{int(stock)} Adet" if stock > 0 else "Stokta Yok"
                            
                            # Extract variants
                            variants = []
                            if hasattr(p, 'attribute_line_ids'):
                                allowed_attrs = ['renk', 'beden', 'numara']
                                for attr in p.attribute_line_ids:
                                    attr_name = attr.attribute_id.name
                                    if any(a in attr_name.lower() for a in allowed_attrs):
                                        vals = ", ".join(attr.value_ids.mapped('name'))
                                        variants.append(f"{attr_name}: {vals}")
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
    
                    # Generate Reply ONCE for this batch
                    reply_text = ai_provider.generate_response(user_message, system_context)
                    
                    if not reply_text or str(reply_text).startswith("[ERROR]"):
                        _logger.error(f"AI Provider error or empty reply for conversation {conversation.id}")
                        # 429 rate limit kontrolü
                        if '429' in str(reply_text) or not reply_text:
                            consecutive_429s += 1
                        continue # Will retry next cron run
                    
                    # Başarılı yanıt — 429 sayacını sıfırla
                    consecutive_429s = 0
                        
                    # Process Handoff (only for DMs, not comments)
                    if "[DEVRET]" in reply_text.upper():
                        reply_text = reply_text.replace("[DEVRET]", "").replace("[devret]", "").strip()
                        # Only change state for DMs, NOT for public comments
                        # Comments should continue to be auto-replied even after handoff
                        if not is_comment:
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
                        if last_msg.content.startswith('[YORUM]:'):
                            last_comment_id = last_msg.platform_message_id
                            if last_comment_id:
                                auto_reply = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.comment_auto_reply', 'Merhaba, detaylı bilgi DM üzerinden iletilmiştir.')
                                account._send_meta_comment_reply(last_comment_id, auto_reply)
                                account._send_meta_private_reply(last_comment_id, reply_text)
                        else:
                            account._send_meta_message(conversation.social_user_id, reply_text)
                    elif account.platform == 'whatsapp':
                        account._send_whatsapp_message(conversation.social_user_id, reply_text)
                        
                    # Mark messages in this batch as processed
                    for m in batch:
                        m.ai_processed = True
                    
                    # Commit progress
                    self.env.cr.commit()
                    
                    # Rate limiting: Gemini rate limit'e takılmamak için bekleme
                    time.sleep(2)
                
            except Exception as e:
                _logger.error(f"Failed to process AI queue for conversation {conversation.id}: {e}")
                self.env.cr.rollback()
