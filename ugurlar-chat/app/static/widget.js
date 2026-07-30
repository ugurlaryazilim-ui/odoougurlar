/**
 * Uğurlar Chat Widget v2.0 — WebSocket destekli
 * 
 * Kullanım (Shopify theme.liquid):
 *   <script>
 *     window.UGURLAR_CHAT_SERVER = 'https://chat.ugurlar.com';
 *   </script>
 *   <script src="https://chat.ugurlar.com/static/widget.js"></script>
 */
(function () {
  'use strict';

  // ─── Config ──────────────────────────────────────────────
  const CONFIG = {
    serverUrl: window.UGURLAR_CHAT_SERVER || 'https://chat.ugurlar.com',
    storeDomain: window.location.hostname,
    storageKey: 'ugurlar_chat_v2',
    reconnectDelay: 3000,
    maxReconnect: 10,
    heartbeatInterval: 30000,
  };

  // ─── State ───────────────────────────────────────────────
  let state = {
    conversationUid: null,
    ws: null,
    isOpen: false,
    isMinimized: false,
    messages: [],
    quickReplies: [],
    reconnectCount: 0,
    heartbeatTimer: null,
  };

  // ─── Storage ─────────────────────────────────────────────
  function loadState() {
    try {
      const saved = localStorage.getItem(CONFIG.storageKey);
      if (saved) {
        const parsed = JSON.parse(saved);
        state.conversationUid = parsed.conversationUid || null;
        state.messages = parsed.messages || [];
      }
    } catch (e) { /* ignore */ }
  }

  function saveState() {
    try {
      localStorage.setItem(CONFIG.storageKey, JSON.stringify({
        conversationUid: state.conversationUid,
        messages: state.messages.slice(-50), // Son 50 mesajı sakla
      }));
    } catch (e) { /* ignore */ }
  }

  // ─── API ─────────────────────────────────────────────────
  async function apiCall(endpoint, data = {}) {
    const url = `${CONFIG.serverUrl}/api/chat/${endpoint}`;
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      return await resp.json();
    } catch (e) {
      console.warn('[UgurlarChat] API hatası:', e);
      return { success: false, error: 'Sunucuya bağlanılamadı' };
    }
  }

  // ─── WebSocket ───────────────────────────────────────────
  function connectWebSocket() {
    if (!state.conversationUid) return;
    if (state.ws && state.ws.readyState <= 1) return; // Already connected/connecting

    const wsUrl = CONFIG.serverUrl.replace(/^http/, 'ws');
    const url = `${wsUrl}/ws/chat/${state.conversationUid}`;
    
    console.log('[UgurlarChat] WebSocket bağlanıyor:', url);
    
    try {
      state.ws = new WebSocket(url);
    } catch (e) {
      console.warn('[UgurlarChat] WebSocket oluşturulamadı:', e);
      return;
    }

    state.ws.onopen = () => {
      console.log('[UgurlarChat] ✅ WebSocket bağlandı');
      state.reconnectCount = 0;
      startHeartbeat();
    };

    state.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
      } catch (e) {
        console.warn('[UgurlarChat] WS mesaj parse hatası:', e);
      }
    };

    state.ws.onclose = (event) => {
      console.log('[UgurlarChat] WebSocket kapandı:', event.code);
      stopHeartbeat();
      // Auto-reconnect
      if (state.reconnectCount < CONFIG.maxReconnect) {
        state.reconnectCount++;
        const delay = CONFIG.reconnectDelay * Math.min(state.reconnectCount, 5);
        setTimeout(connectWebSocket, delay);
      }
    };

    state.ws.onerror = (error) => {
      console.warn('[UgurlarChat] WebSocket hatası:', error);
    };
  }

  function handleWebSocketMessage(data) {
    if (data.type === 'pong') return; // Heartbeat response

    if (data.type === 'new_message' || data.type === 'operator_reply') {
      const msg = data.message;
      // Duplicate check
      if (!state.messages.some(m => m.id === msg.id)) {
        state.messages.push(msg);
        renderMessages();
        saveState();
        // Scroll to bottom
        const list = document.getElementById('uc-messages');
        if (list) list.scrollTop = list.scrollHeight;
        // Notify if minimized
        if (state.isMinimized && msg.sender_type !== 'customer') {
          showNotificationBadge();
        }
      }
    }

    if (data.type === 'typing') {
      showTypingIndicator(data.operator_name || 'Operatör');
    }

    if (data.type === 'closed') {
      addSystemMessage('Bu sohbet kapatıldı.');
    }
  }

  function startHeartbeat() {
    stopHeartbeat();
    state.heartbeatTimer = setInterval(() => {
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, CONFIG.heartbeatInterval);
  }

  function stopHeartbeat() {
    if (state.heartbeatTimer) {
      clearInterval(state.heartbeatTimer);
      state.heartbeatTimer = null;
    }
  }

  // ─── Chat Logic ──────────────────────────────────────────
  async function startChat() {
    const result = await apiCall('start', {
      shop_domain: CONFIG.storeDomain,
      customer_name: null,
      customer_email: null,
      page_url: window.location.href,
      page_title: document.title,
    });

    if (result.success) {
      state.conversationUid = result.conversation_uid;
      state.quickReplies = result.quick_replies || [];
      
      // Hoşgeldin mesajını ekle
      state.messages = [{
        id: 0,
        text: result.welcome_message,
        sender_type: 'system',
        sender_name: 'Uğurlar Destek',
        created_at: new Date().toISOString(),
        is_read: false,
      }];

      saveState();
      renderMessages();
      renderQuickReplies();
      connectWebSocket();
    }
    return result;
  }

  async function sendMessage(text) {
    if (!text.trim()) return;
    if (!state.conversationUid) {
      await startChat();
    }

    // Optimistic UI — hemen göster
    const tempMsg = {
      id: Date.now(),
      text: text,
      sender_type: 'customer',
      sender_name: 'Siz',
      created_at: new Date().toISOString(),
      is_read: false,
    };
    state.messages.push(tempMsg);
    renderMessages();
    clearInput();

    // API'ye gönder
    const result = await apiCall('send', {
      conversation_uid: state.conversationUid,
      message: text,
    });

    if (result.success) {
      // Gerçek ID ile güncelle
      tempMsg.id = result.message_id;
      saveState();
    } else {
      // Hata durumunda mesajı işaretle
      tempMsg.text += ' ❌';
      renderMessages();
    }
  }

  // ─── UI Helpers ──────────────────────────────────────────
  function addSystemMessage(text) {
    state.messages.push({
      id: Date.now(),
      text: text,
      sender_type: 'system',
      sender_name: 'Sistem',
      created_at: new Date().toISOString(),
      is_read: true,
    });
    renderMessages();
  }

  function showNotificationBadge() {
    const badge = document.getElementById('uc-badge');
    if (badge) {
      badge.style.display = 'flex';
      badge.textContent = '!';
    }
  }

  function showTypingIndicator(name) {
    const el = document.getElementById('uc-typing');
    if (el) {
      el.textContent = `${name} yazıyor...`;
      el.style.display = 'block';
      setTimeout(() => { el.style.display = 'none'; }, 3000);
    }
  }

  function clearInput() {
    const input = document.getElementById('uc-input');
    if (input) input.value = '';
  }

  // ─── Render ──────────────────────────────────────────────
  function renderMessages() {
    const list = document.getElementById('uc-messages');
    if (!list) return;

    list.innerHTML = state.messages.map(msg => {
      const isCustomer = msg.sender_type === 'customer';
      const isSystem = msg.sender_type === 'system' || msg.sender_type === 'bot';
      const time = new Date(msg.created_at).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });

      if (isSystem) {
        return `<div class="uc-msg uc-msg-system">
          <div class="uc-msg-avatar">🤖</div>
          <div class="uc-msg-bubble uc-bubble-system">
            <div class="uc-msg-name">${escapeHtml(msg.sender_name || 'Sistem')}</div>
            <div class="uc-msg-text">${escapeHtml(msg.text)}</div>
            <div class="uc-msg-time">${time}</div>
          </div>
        </div>`;
      }

      if (isCustomer) {
        return `<div class="uc-msg uc-msg-customer">
          <div class="uc-msg-bubble uc-bubble-customer">
            <div class="uc-msg-text">${escapeHtml(msg.text)}</div>
            <div class="uc-msg-time">${time}</div>
          </div>
        </div>`;
      }

      // Operator
      return `<div class="uc-msg uc-msg-operator">
        <div class="uc-msg-avatar">👤</div>
        <div class="uc-msg-bubble uc-bubble-operator">
          <div class="uc-msg-name">${escapeHtml(msg.sender_name || 'Operatör')}</div>
          <div class="uc-msg-text">${escapeHtml(msg.text)}</div>
          <div class="uc-msg-time">${time}</div>
        </div>
      </div>`;
    }).join('');

    list.scrollTop = list.scrollHeight;
  }

  function renderQuickReplies() {
    const container = document.getElementById('uc-quick-replies');
    if (!container || !state.quickReplies.length) return;

    container.innerHTML = state.quickReplies.map(qr =>
      `<button class="uc-qr-btn" onclick="window.__ugurlarChat.sendMessage('${escapeHtml(qr.message)}')">${escapeHtml(qr.label)}</button>`
    ).join('');
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // ─── Widget DOM ──────────────────────────────────────────
  function createWidget() {
    // CSS yükle
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `${CONFIG.serverUrl}/static/widget.css`;
    document.head.appendChild(link);

    const widget = document.createElement('div');
    widget.id = 'uc-widget';
    widget.innerHTML = `
      <!-- Fab Button -->
      <button id="uc-fab" onclick="window.__ugurlarChat.toggle()">
        💬
        <span id="uc-badge" style="display:none"></span>
      </button>

      <!-- Chat Window -->
      <div id="uc-window" style="display:none">
        <div id="uc-header">
          <div id="uc-header-info">
            <div id="uc-header-title">Uğurlar Destek</div>
            <div id="uc-header-status">● Çevrimiçi</div>
          </div>
          <div id="uc-header-actions">
            <button onclick="window.__ugurlarChat.minimize()" title="Küçült">−</button>
            <button onclick="window.__ugurlarChat.close()" title="Kapat">✕</button>
          </div>
        </div>

        <div id="uc-messages"></div>
        
        <div id="uc-typing" style="display:none"></div>
        
        <div id="uc-quick-replies"></div>
        
        <div id="uc-footer">
          <input id="uc-input" type="text" placeholder="Mesajınızı yazın..."
                 onkeydown="if(event.key==='Enter'){window.__ugurlarChat.sendMessage(this.value)}" />
          <button id="uc-send" onclick="window.__ugurlarChat.sendMessage(document.getElementById('uc-input').value)">
            ➤
          </button>
        </div>
      </div>
    `;

    document.body.appendChild(widget);
  }

  // ─── Public API ──────────────────────────────────────────
  function toggle() {
    const win = document.getElementById('uc-window');
    if (!win) return;

    if (win.style.display === 'none') {
      win.style.display = 'flex';
      state.isOpen = true;
      state.isMinimized = false;
      
      // İlk açılışta chat başlat
      if (!state.conversationUid) {
        startChat();
      } else {
        renderMessages();
        renderQuickReplies();
        connectWebSocket();
      }

      // Badge'i gizle
      const badge = document.getElementById('uc-badge');
      if (badge) badge.style.display = 'none';

      // Input'a focus
      setTimeout(() => {
        const input = document.getElementById('uc-input');
        if (input) input.focus();
      }, 100);
    } else {
      win.style.display = 'none';
      state.isOpen = false;
    }
  }

  function minimize() {
    const win = document.getElementById('uc-window');
    if (win) {
      win.style.display = 'none';
      state.isMinimized = true;
    }
  }

  function closeChat() {
    const win = document.getElementById('uc-window');
    if (win) win.style.display = 'none';
    state.isOpen = false;
    state.isMinimized = false;
  }

  // ─── Init ────────────────────────────────────────────────
  function init() {
    loadState();
    createWidget();

    // Expose public API
    window.__ugurlarChat = {
      toggle,
      minimize,
      close: closeChat,
      sendMessage,
      startChat,
    };

    console.log('[UgurlarChat] v2.0 WebSocket widget yüklendi');
  }

  // DOM hazır olduğunda başlat
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
