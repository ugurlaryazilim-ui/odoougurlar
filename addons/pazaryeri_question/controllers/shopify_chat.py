import hashlib
import hmac
import json
import logging
import time
from odoo import http, fields, _
from odoo.http import request

_logger = logging.getLogger(__name__)

# Basit rate limiter — IP bazlı
_rate_limits = {}
RATE_LIMIT_WINDOW = 60  # saniye
RATE_LIMIT_MAX = 60  # pencere başına max istek


def _check_rate_limit(ip):
    """IP bazlı basit rate limiter."""
    now = time.time()
    if ip not in _rate_limits:
        _rate_limits[ip] = []
    # Eski kayıtları temizle
    _rate_limits[ip] = [t for t in _rate_limits[ip] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limits[ip]) >= RATE_LIMIT_MAX:
        return False
    _rate_limits[ip].append(now)
    return True


def _json_response(data, status=200):
    """Standart JSON response."""
    return request.make_json_response(data, status=status)


def _error_response(message, status=400):
    """Hata response."""
    return request.make_json_response({'success': False, 'error': message}, status=status)


class ShopifyChatController(http.Controller):
    """Shopify canlı sohbet HTTP controller'ı.
    
    Tüm endpoint'ler /shopify/chat/ altındadır.
    Shopify App Proxy bu URL'leri ugurlar.com/apps/chat/* üzerinden yönlendirir.
    """

    # ─── SOHBET BAŞLAT ──────────────────────────────────────────
    @http.route('/shopify/chat/start', type='json', auth='public', methods=['POST'], csrf=False, cors='*')
    def chat_start(self, **kwargs):
        """Yeni sohbet konuşması başlat veya mevcut olanı döndür.
        
        Request body:
        {
            "customer_name": "Ali Veli",       // opsiyonel
            "customer_email": "ali@mail.com",  // opsiyonel
            "shop_domain": "ugurlar.com",      // zorunlu
            "page_url": "https://...",         // opsiyonel
            "page_title": "Ürün Adı",          // opsiyonel
            "conversation_uid": "xxx"          // opsiyonel — mevcut konuşmayı devam ettir
        }
        """
        ip = request.httprequest.remote_addr
        if not _check_rate_limit(ip):
            return {'success': False, 'error': 'Çok fazla istek. Lütfen bekleyin.'}
        
        data = kwargs
        shop_domain = data.get('shop_domain', '')
        
        if not shop_domain:
            return {'success': False, 'error': 'shop_domain zorunludur.'}
        
        Conversation = request.env['marketplace.chat.conversation'].sudo()
        
        # Mevcut konuşma var mı?
        conv_uid = data.get('conversation_uid')
        if conv_uid:
            existing = Conversation.search([
                ('conversation_uid', '=', conv_uid),
                ('state', '!=', 'closed'),
            ], limit=1)
            if existing:
                return {
                    'success': True,
                    'conversation_uid': existing.conversation_uid,
                    'state': existing.state,
                    'operator_name': existing.operator_id.name if existing.operator_id else None,
                }
        
        # Yeni konuşma oluştur
        conv = Conversation.create({
            'marketplace_type': 'shopify',
            'shop_domain': shop_domain,
            'customer_name': data.get('customer_name', ''),
            'customer_email': data.get('customer_email', ''),
            'page_url': data.get('page_url', ''),
            'page_title': data.get('page_title', ''),
        })
        
        # Hoşgeldin mesajı
        request.env['marketplace.chat.message'].sudo().create({
            'conversation_id': conv.id,
            'message_text': 'Merhaba! 👋 Uğurlar\'a hoş geldiniz. Size nasıl yardımcı olabiliriz?',
            'sender_type': 'bot',
            'sender_name': 'Uğurlar Destek',
        })
        
        # Operatörlere bildirim
        self._notify_operators(conv)
        
        _logger.info("Yeni sohbet başladı: %s (müşteri: %s, domain: %s)", 
                     conv.conversation_uid[:8], conv.customer_name or 'Anonim', shop_domain)
        
        return {
            'success': True,
            'conversation_uid': conv.conversation_uid,
            'state': conv.state,
        }

    # ─── MESAJ GÖNDER ────────────────────────────────────────────
    @http.route('/shopify/chat/send', type='json', auth='public', methods=['POST'], csrf=False, cors='*')
    def chat_send(self, **kwargs):
        """Müşteri mesaj gönderir.
        
        Request body:
        {
            "conversation_uid": "xxx",     // zorunlu
            "message": "Merhaba...",       // zorunlu
            "customer_name": "Ali",        // opsiyonel — güncelleme
            "customer_email": "a@b.com"    // opsiyonel — güncelleme
        }
        """
        ip = request.httprequest.remote_addr
        if not _check_rate_limit(ip):
            return {'success': False, 'error': 'Çok fazla istek.'}
        
        data = kwargs
        conv_uid = data.get('conversation_uid')
        message_text = (data.get('message') or '').strip()
        
        if not conv_uid:
            return {'success': False, 'error': 'conversation_uid zorunludur.'}
        if not message_text:
            return {'success': False, 'error': 'Mesaj boş olamaz.'}
        if len(message_text) > 5000:
            return {'success': False, 'error': 'Mesaj çok uzun (max 5000 karakter).'}
        
        Conversation = request.env['marketplace.chat.conversation'].sudo()
        conv = Conversation.search([
            ('conversation_uid', '=', conv_uid),
        ], limit=1)
        
        if not conv:
            return {'success': False, 'error': 'Konuşma bulunamadı.'}
        
        if conv.state == 'closed':
            # Kapalı konuşmayı yeniden aç
            conv.write({'state': 'open', 'closed_date': False})
        
        # Müşteri bilgilerini güncelle
        update_vals = {}
        if data.get('customer_name') and not conv.customer_name:
            update_vals['customer_name'] = data['customer_name']
        if data.get('customer_email') and not conv.customer_email:
            update_vals['customer_email'] = data['customer_email']
        if update_vals:
            conv.write(update_vals)
        
        # Mesaj oluştur
        msg = request.env['marketplace.chat.message'].sudo().create({
            'conversation_id': conv.id,
            'message_text': message_text,
            'sender_type': 'customer',
            'sender_name': conv.customer_name or 'Müşteri',
        })
        
        return {
            'success': True,
            'message_id': msg.id,
            'sent_date': msg.sent_date.isoformat() if msg.sent_date else None,
        }

    # ─── MESAJ POLLING ───────────────────────────────────────────
    @http.route('/shopify/chat/poll', type='json', auth='public', methods=['POST'], csrf=False, cors='*')
    def chat_poll(self, **kwargs):
        """Yeni mesajları kontrol et (müşteri tarafı polling).
        
        Request body:
        {
            "conversation_uid": "xxx",
            "last_message_id": 123    // son alınan mesaj ID'si
        }
        """
        ip = request.httprequest.remote_addr
        if not _check_rate_limit(ip):
            return {'success': False, 'error': 'Çok fazla istek.'}
        
        data = kwargs
        conv_uid = data.get('conversation_uid')
        last_id = int(data.get('last_message_id', 0))
        
        if not conv_uid:
            return {'success': False, 'error': 'conversation_uid zorunludur.'}
        
        Conversation = request.env['marketplace.chat.conversation'].sudo()
        conv = Conversation.search([
            ('conversation_uid', '=', conv_uid),
        ], limit=1)
        
        if not conv:
            return {'success': False, 'error': 'Konuşma bulunamadı.'}
        
        # Yeni mesajları getir (sadece operator/bot mesajları — müşteri kendi mesajlarını zaten bilir)
        Message = request.env['marketplace.chat.message'].sudo()
        new_messages = Message.search([
            ('conversation_id', '=', conv.id),
            ('id', '>', last_id),
            ('sender_type', 'in', ['operator', 'bot', 'system']),
        ], order='sent_date asc', limit=50)
        
        messages = []
        for msg in new_messages:
            messages.append({
                'id': msg.id,
                'text': msg.message_text,
                'sender_type': msg.sender_type,
                'sender_name': msg.sender_name or '',
                'sent_date': msg.sent_date.isoformat() if msg.sent_date else None,
            })
        
        return {
            'success': True,
            'messages': messages,
            'conversation_state': conv.state,
            'operator_name': conv.operator_id.name if conv.operator_id else None,
            'operator_typing': False,  # TODO: implement typing indicator
        }

    # ─── SOHBET GEÇMİŞİ ─────────────────────────────────────────
    @http.route('/shopify/chat/history', type='json', auth='public', methods=['POST'], csrf=False, cors='*')
    def chat_history(self, **kwargs):
        """Sohbet geçmişini getir (sayfa yenilendiğinde).
        
        Request body:
        {
            "conversation_uid": "xxx"
        }
        """
        ip = request.httprequest.remote_addr
        if not _check_rate_limit(ip):
            return {'success': False, 'error': 'Çok fazla istek.'}
        
        conv_uid = kwargs.get('conversation_uid')
        if not conv_uid:
            return {'success': False, 'error': 'conversation_uid zorunludur.'}
        
        Conversation = request.env['marketplace.chat.conversation'].sudo()
        conv = Conversation.search([
            ('conversation_uid', '=', conv_uid),
        ], limit=1)
        
        if not conv:
            return {'success': False, 'error': 'Konuşma bulunamadı.'}
        
        Message = request.env['marketplace.chat.message'].sudo()
        all_messages = Message.search([
            ('conversation_id', '=', conv.id),
        ], order='sent_date asc', limit=200)
        
        messages = []
        for msg in all_messages:
            messages.append({
                'id': msg.id,
                'text': msg.message_text,
                'sender_type': msg.sender_type,
                'sender_name': msg.sender_name or '',
                'sent_date': msg.sent_date.isoformat() if msg.sent_date else None,
            })
        
        return {
            'success': True,
            'messages': messages,
            'conversation': {
                'uid': conv.conversation_uid,
                'state': conv.state,
                'customer_name': conv.customer_name or '',
                'operator_name': conv.operator_id.name if conv.operator_id else None,
                'started_date': conv.started_date.isoformat() if conv.started_date else None,
            },
        }

    # ─── SOHBET KAPAT ────────────────────────────────────────────
    @http.route('/shopify/chat/close', type='json', auth='public', methods=['POST'], csrf=False, cors='*')
    def chat_close(self, **kwargs):
        """Müşteri sohbeti kapatır."""
        conv_uid = kwargs.get('conversation_uid')
        if not conv_uid:
            return {'success': False, 'error': 'conversation_uid zorunludur.'}
        
        Conversation = request.env['marketplace.chat.conversation'].sudo()
        conv = Conversation.search([
            ('conversation_uid', '=', conv_uid),
        ], limit=1)
        
        if conv and conv.state != 'closed':
            conv.write({
                'state': 'closed',
                'closed_date': fields.Datetime.now(),
            })
            # Kapanış mesajı
            request.env['marketplace.chat.message'].sudo().create({
                'conversation_id': conv.id,
                'message_text': 'Sohbet müşteri tarafından kapatıldı.',
                'sender_type': 'system',
                'sender_name': 'Sistem',
            })
        
        return {'success': True}

    # ─── DEĞERLENDİRME ──────────────────────────────────────────
    @http.route('/shopify/chat/rate', type='json', auth='public', methods=['POST'], csrf=False, cors='*')
    def chat_rate(self, **kwargs):
        """Müşteri değerlendirmesi."""
        conv_uid = kwargs.get('conversation_uid')
        rating = kwargs.get('rating')
        
        if not conv_uid or not rating:
            return {'success': False, 'error': 'conversation_uid ve rating zorunludur.'}
        if str(rating) not in ('1', '2', '3', '4', '5'):
            return {'success': False, 'error': 'Rating 1-5 arasında olmalıdır.'}
        
        Conversation = request.env['marketplace.chat.conversation'].sudo()
        conv = Conversation.search([
            ('conversation_uid', '=', conv_uid),
        ], limit=1)
        
        if conv:
            conv.write({'rating': str(rating)})
        
        return {'success': True}

    # ─── HIZLI CEVAPLAR ──────────────────────────────────────────
    @http.route('/shopify/chat/quick-replies', type='json', auth='public', methods=['POST'], csrf=False, cors='*')
    def chat_quick_replies(self, **kwargs):
        """Hızlı cevap butonlarını döndür."""
        quick_replies = [
            {'id': 'order_track', 'label': '📦 Sipariş Takibi', 'message': 'Siparişimi takip etmek istiyorum.'},
            {'id': 'return', 'label': '↩️ İade Talebi', 'message': 'İade işlemi hakkında bilgi almak istiyorum.'},
            {'id': 'product', 'label': '👗 Ürün Bilgisi', 'message': 'Ürün hakkında bilgi almak istiyorum.'},
            {'id': 'cargo', 'label': '🚚 Kargo Durumu', 'message': 'Kargom nerede?'},
            {'id': 'size', 'label': '📏 Beden Bilgisi', 'message': 'Beden tablosu hakkında bilgi istiyorum.'},
            {'id': 'live', 'label': '💬 Canlı Destek', 'message': 'Canlı destek ile görüşmek istiyorum.'},
        ]
        return {'success': True, 'quick_replies': quick_replies}

    # ─── YARDIMCI METOTLAR ───────────────────────────────────────
    def _notify_operators(self, conversation):
        """Yeni sohbet geldiğinde operatörlere Odoo bildirimi gönder."""
        try:
            ICP = request.env['ir.config_parameter'].sudo()
            user_ids_str = ICP.get_param('pazaryeri_question.representative_user_ids', '[]')
            user_ids = json.loads(user_ids_str) if user_ids_str else []
            
            if user_ids:
                users = request.env['res.users'].sudo().browse(user_ids)
                for user in users.exists():
                    user.partner_id.message_post(
                        body=f"💬 Yeni Shopify sohbeti!\n"
                             f"Müşteri: {conversation.customer_name or 'Anonim'}\n"
                             f"Sayfa: {conversation.page_title or conversation.page_url or '-'}",
                        message_type='notification',
                        subtype_xmlid='mail.mt_note',
                    )
        except Exception as e:
            _logger.warning("Operatör bildirimi gönderilemedi: %s", e)
