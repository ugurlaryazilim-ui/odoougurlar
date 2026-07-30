import json
import logging
import time
from odoo import http, fields, _
from odoo.http import request

_logger = logging.getLogger(__name__)

# Basit rate limiter — IP bazlı
_rate_limits = {}
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 120


def _check_rate_limit(ip):
    now = time.time()
    if ip not in _rate_limits:
        _rate_limits[ip] = []
    _rate_limits[ip] = [t for t in _rate_limits[ip] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limits[ip]) >= RATE_LIMIT_MAX:
        return False
    _rate_limits[ip].append(now)
    return True


def _get_json_body():
    """Request body'den JSON parse et."""
    try:
        # Yöntem 1: Werkzeug get_json
        data = request.httprequest.get_json(force=True, silent=True)
        if data:
            # Eski JSON-RPC wrapper kontrolü
            if 'jsonrpc' in data and 'params' in data:
                _logger.info("JSON-RPC wrapper tespit edildi, params kullanılıyor")
                return data['params']
            return data
    except Exception:
        pass

    try:
        # Yöntem 2: Ham veri
        raw = request.httprequest.data
        if raw:
            data = json.loads(raw)
            if 'jsonrpc' in data and 'params' in data:
                return data['params']
            return data
    except Exception:
        pass

    try:
        # Yöntem 3: get_data
        raw = request.httprequest.get_data(as_text=True)
        if raw:
            data = json.loads(raw)
            if 'jsonrpc' in data and 'params' in data:
                return data['params']
            return data
    except Exception:
        pass

    _logger.warning("Chat: Request body boş veya parse edilemedi")
    return {}


def _json_ok(data):
    """Başarılı JSON response — JSON-RPC uyumlu."""
    wrapped = {'jsonrpc': '2.0', 'id': None, 'result': data}
    return request.make_json_response(wrapped, status=200)


def _json_error(message, status=400):
    """Hata JSON response — JSON-RPC uyumlu."""
    error_data = {'success': False, 'error': message}
    wrapped = {'jsonrpc': '2.0', 'id': None, 'result': error_data}
    return request.make_json_response(wrapped, status=status)


class ShopifyChatController(http.Controller):
    """Shopify canlı sohbet HTTP controller'ı — type='http' ile harici JS uyumlu."""

    # ─── SOHBET BAŞLAT ──────────────────────────────────────────
    @http.route('/shopify/chat/start', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def chat_start(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers=self._cors_headers())

        ip = request.httprequest.remote_addr
        if not _check_rate_limit(ip):
            return _json_error('Çok fazla istek.', 429)

        data = _get_json_body()
        _logger.info("Chat START — data keys: %s, ip: %s", list(data.keys()), ip)
        
        shop_domain = data.get('shop_domain', '') or request.httprequest.host or 'unknown'

        Conversation = request.env['marketplace.chat.conversation'].sudo()

        # Mevcut konuşma?
        conv_uid = data.get('conversation_uid')
        if conv_uid:
            existing = Conversation.search([
                ('conversation_uid', '=', conv_uid),
                ('state', '!=', 'closed'),
            ], limit=1)
            if existing:
                _logger.info("Mevcut sohbet bulundu: %s", conv_uid[:8])
                return _json_ok({
                    'success': True,
                    'conversation_uid': existing.conversation_uid,
                    'state': existing.state,
                    'operator_name': existing.operator_id.name if existing.operator_id else None,
                })

        # Yeni konuşma
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

        self._notify_operators(conv)

        _logger.info("✅ Yeni sohbet başladı: %s (müşteri: %s, domain: %s)",
                     conv.conversation_uid[:8], conv.customer_name or 'Anonim', shop_domain)

        return _json_ok({
            'success': True,
            'conversation_uid': conv.conversation_uid,
            'state': conv.state,
        })

    # ─── MESAJ GÖNDER ────────────────────────────────────────────
    @http.route('/shopify/chat/send', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def chat_send(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers=self._cors_headers())

        ip = request.httprequest.remote_addr
        if not _check_rate_limit(ip):
            return _json_error('Çok fazla istek.', 429)

        data = _get_json_body()
        _logger.info("Chat SEND — data keys: %s", list(data.keys()))
        conv_uid = data.get('conversation_uid')
        message_text = (data.get('message') or '').strip()

        if not conv_uid:
            return _json_error('conversation_uid zorunludur.')
        if not message_text:
            return _json_error('Mesaj boş olamaz.')
        if len(message_text) > 5000:
            return _json_error('Mesaj çok uzun (max 5000 karakter).')

        Conversation = request.env['marketplace.chat.conversation'].sudo()
        conv = Conversation.search([('conversation_uid', '=', conv_uid)], limit=1)

        if not conv:
            return _json_error('Konuşma bulunamadı.')

        if conv.state == 'closed':
            conv.write({'state': 'open', 'closed_date': False})

        # Müşteri bilgi güncelle
        update_vals = {}
        if data.get('customer_name') and not conv.customer_name:
            update_vals['customer_name'] = data['customer_name']
        if data.get('customer_email') and not conv.customer_email:
            update_vals['customer_email'] = data['customer_email']
        if update_vals:
            conv.write(update_vals)

        msg = request.env['marketplace.chat.message'].sudo().create({
            'conversation_id': conv.id,
            'message_text': message_text,
            'sender_type': 'customer',
            'sender_name': conv.customer_name or 'Müşteri',
        })

        _logger.info("💬 Müşteri mesajı: conv=%s, msg_id=%s", conv_uid[:8], msg.id)

        return _json_ok({
            'success': True,
            'message_id': msg.id,
            'sent_date': msg.sent_date.isoformat() if msg.sent_date else None,
        })

    # ─── MESAJ POLLING ───────────────────────────────────────────
    @http.route('/shopify/chat/poll', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def chat_poll(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers=self._cors_headers())

        ip = request.httprequest.remote_addr
        if not _check_rate_limit(ip):
            return _json_error('Çok fazla istek.', 429)

        data = _get_json_body()
        conv_uid = data.get('conversation_uid')
        last_id = int(data.get('last_message_id', 0))

        if not conv_uid:
            return _json_error('conversation_uid zorunludur.')

        Conversation = request.env['marketplace.chat.conversation'].sudo()
        conv = Conversation.search([('conversation_uid', '=', conv_uid)], limit=1)

        if not conv:
            return _json_error('Konuşma bulunamadı.')

        Message = request.env['marketplace.chat.message'].sudo()
        new_messages = Message.search([
            ('conversation_id', '=', conv.id),
            ('id', '>', last_id),
            ('sender_type', 'in', ['operator', 'bot', 'system']),
        ], order='sent_date asc', limit=50)

        messages = [{
            'id': m.id,
            'text': m.message_text,
            'sender_type': m.sender_type,
            'sender_name': m.sender_name or '',
            'sent_date': m.sent_date.isoformat() if m.sent_date else None,
        } for m in new_messages]

        return _json_ok({
            'success': True,
            'messages': messages,
            'conversation_state': conv.state,
            'operator_name': conv.operator_id.name if conv.operator_id else None,
        })

    # ─── SOHBET GEÇMİŞİ ─────────────────────────────────────────
    @http.route('/shopify/chat/history', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def chat_history(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers=self._cors_headers())

        ip = request.httprequest.remote_addr
        if not _check_rate_limit(ip):
            return _json_error('Çok fazla istek.', 429)

        data = _get_json_body()
        conv_uid = data.get('conversation_uid')
        if not conv_uid:
            return _json_error('conversation_uid zorunludur.')

        Conversation = request.env['marketplace.chat.conversation'].sudo()
        conv = Conversation.search([('conversation_uid', '=', conv_uid)], limit=1)

        if not conv:
            return _json_error('Konuşma bulunamadı.')

        Message = request.env['marketplace.chat.message'].sudo()
        all_messages = Message.search([
            ('conversation_id', '=', conv.id),
        ], order='sent_date asc', limit=200)

        messages = [{
            'id': m.id,
            'text': m.message_text,
            'sender_type': m.sender_type,
            'sender_name': m.sender_name or '',
            'sent_date': m.sent_date.isoformat() if m.sent_date else None,
        } for m in all_messages]

        return _json_ok({
            'success': True,
            'messages': messages,
            'conversation': {
                'uid': conv.conversation_uid,
                'state': conv.state,
                'customer_name': conv.customer_name or '',
                'operator_name': conv.operator_id.name if conv.operator_id else None,
                'started_date': conv.started_date.isoformat() if conv.started_date else None,
            },
        })

    # ─── SOHBET KAPAT ────────────────────────────────────────────
    @http.route('/shopify/chat/close', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def chat_close(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers=self._cors_headers())

        data = _get_json_body()
        conv_uid = data.get('conversation_uid')
        if not conv_uid:
            return _json_error('conversation_uid zorunludur.')

        Conversation = request.env['marketplace.chat.conversation'].sudo()
        conv = Conversation.search([('conversation_uid', '=', conv_uid)], limit=1)

        if conv and conv.state != 'closed':
            conv.write({'state': 'closed', 'closed_date': fields.Datetime.now()})
            request.env['marketplace.chat.message'].sudo().create({
                'conversation_id': conv.id,
                'message_text': 'Sohbet müşteri tarafından kapatıldı.',
                'sender_type': 'system',
                'sender_name': 'Sistem',
            })

        return _json_ok({'success': True})

    # ─── DEĞERLENDİRME ──────────────────────────────────────────
    @http.route('/shopify/chat/rate', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def chat_rate(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers=self._cors_headers())

        data = _get_json_body()
        conv_uid = data.get('conversation_uid')
        rating = data.get('rating')
        if not conv_uid or not rating:
            return _json_error('conversation_uid ve rating zorunludur.')
        if str(rating) not in ('1', '2', '3', '4', '5'):
            return _json_error('Rating 1-5 arasında olmalıdır.')

        Conversation = request.env['marketplace.chat.conversation'].sudo()
        conv = Conversation.search([('conversation_uid', '=', conv_uid)], limit=1)
        if conv:
            conv.write({'rating': str(rating)})

        return _json_ok({'success': True})

    # ─── HIZLI CEVAPLAR ──────────────────────────────────────────
    @http.route('/shopify/chat/quick-replies', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def chat_quick_replies(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers=self._cors_headers())

        return _json_ok({
            'success': True,
            'quick_replies': [
                {'id': 'order_track', 'label': '📦 Sipariş Takibi', 'message': 'Siparişimi takip etmek istiyorum.'},
                {'id': 'return', 'label': '↩️ İade Talebi', 'message': 'İade işlemi hakkında bilgi almak istiyorum.'},
                {'id': 'product', 'label': '👗 Ürün Bilgisi', 'message': 'Ürün hakkında bilgi almak istiyorum.'},
                {'id': 'cargo', 'label': '🚚 Kargo Durumu', 'message': 'Kargom nerede?'},
                {'id': 'size', 'label': '📏 Beden Bilgisi', 'message': 'Beden tablosu hakkında bilgi istiyorum.'},
                {'id': 'live', 'label': '💬 Canlı Destek', 'message': 'Canlı destek ile görüşmek istiyorum.'},
            ],
        })

    # ─── TEST SAYFASI ────────────────────────────────────────────
    @http.route('/shopify/chat/test', type='http', auth='public', csrf=False, cors='*')
    def chat_test_page(self, **kwargs):
        html = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <title>Uğurlar Chat Widget Test</title>
    <style>
        body { font-family: 'Inter', sans-serif; background: #f5f5f5; margin: 0; padding: 40px; }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { color: #1a1a2e; }
        p { color: #666; line-height: 1.6; }
        .card { background: #fff; padding: 24px; border-radius: 12px; margin: 20px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        code { background: #f0f0f0; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
        .status { padding: 8px 16px; border-radius: 8px; background: #d4edda; color: #155724; display: inline-block; }
        #debug { font-family: monospace; font-size: 12px; background: #1a1a2e; color: #4ade80; padding: 16px; border-radius: 8px; max-height: 300px; overflow-y: auto; white-space: pre-wrap; }
    </style>
</head>
<body>
    <div class="container">
        <h1>💬 Uğurlar Chat Widget Test Sayfası</h1>
        <div class="card">
            <div class="status">✅ Aktif</div>
            <p style="margin-top:12px">Chat widget sağ alt köşede görünmelidir. Tıklayarak test edin.</p>
        </div>
        <div class="card">
            <h3>Debug Log</h3>
            <div id="debug">Widget yükleniyor...\n</div>
        </div>
        <div class="card">
            <h3>Shopify Tema Entegrasyonu</h3>
            <p>Aşağıdaki kodu <code>theme.liquid</code> dosyasına <code>&lt;/body&gt;</code> etiketinden önce ekleyin:</p>
            <pre><code>&lt;script&gt;
  window.UGURLAR_CHAT_SERVER = 'https://odoo.ugurlar.com';
&lt;/script&gt;
&lt;script src="https://odoo.ugurlar.com/pazaryeri_question/static/src/js/shopify_chat_widget.js"&gt;&lt;/script&gt;</code></pre>
        </div>
    </div>
    <script>
        // Debug logger
        window.UGURLAR_CHAT_DEBUG = true;
        window.UGURLAR_CHAT_SERVER = window.location.origin;
    </script>
    <script src="/pazaryeri_question/static/src/js/shopify_chat_widget.js"></script>
</body>
</html>"""
        return request.make_response(html, headers=[('Content-Type', 'text/html')])

    # ─── CORS HEADERS ────────────────────────────────────────────
    def _cors_headers(self):
        return [
            ('Access-Control-Allow-Origin', '*'),
            ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
            ('Access-Control-Allow-Headers', 'Content-Type'),
            ('Access-Control-Max-Age', '86400'),
        ]

    # ─── BİLDİRİM ───────────────────────────────────────────────
    def _notify_operators(self, conversation):
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
