/**
 * Uğurlar Canlı Destek Chat Widget
 * Shopify mağazası için self-contained chat widget
 * Odoo backend ile JSON-RPC üzerinden haberleşir
 * 
 * Kullanım: <script src="https://odoo.ugurlar.com/pazaryeri_question/static/src/js/shopify_chat_widget.js"></script>
 * veya Shopify tema.liquid içine eklenir
 */
(function () {
  'use strict';

  // ─── KONFİGÜRASYON ─────────────────────────────────────────
  const CONFIG = {
    // Odoo server URL — Shopify App Proxy kullanılıyorsa '/apps/chat' olur
    serverUrl: window.UGURLAR_CHAT_SERVER || 'https://odoo.ugurlar.com',
    shopDomain: window.location.hostname,
    pollInterval: 4000,       // 4 saniye polling
    maxPollInterval: 15000,   // Idle durumda 15 saniye
    storageKey: 'ugurlar_chat',
    brandName: window.UGURLAR_CHAT_BRAND || 'Uğurlar Destek',
    brandColor: window.UGURLAR_CHAT_COLOR || '#1a1a2e',
    accentColor: window.UGURLAR_CHAT_ACCENT || '#e94560',
    welcomeMessage: 'Merhaba! 👋 Size nasıl yardımcı olabiliriz?',
    placeholder: 'Mesajınızı yazın...',
    offlineMessage: 'Şu an çevrimdışıyız. Mesajınızı bırakın, en kısa sürede dönüş yapacağız.',
    soundEnabled: true,
  };

  // ─── STATE ──────────────────────────────────────────────────
  let state = {
    isOpen: false,
    isMinimized: false,
    conversationUid: null,
    messages: [],
    lastMessageId: 0,
    pollTimer: null,
    currentPollInterval: CONFIG.pollInterval,
    quickReplies: [],
    customerName: '',
    customerEmail: '',
    operatorName: null,
    unreadCount: 0,
    isTyping: false,
  };

  // ─── STORAGE ────────────────────────────────────────────────
  function saveState() {
    try {
      localStorage.setItem(CONFIG.storageKey, JSON.stringify({
        conversationUid: state.conversationUid,
        customerName: state.customerName,
        customerEmail: state.customerEmail,
        lastMessageId: state.lastMessageId,
      }));
    } catch (e) { /* ignore */ }
  }

  function loadState() {
    try {
      const saved = JSON.parse(localStorage.getItem(CONFIG.storageKey));
      if (saved) {
        state.conversationUid = saved.conversationUid || null;
        state.customerName = saved.customerName || '';
        state.customerEmail = saved.customerEmail || '';
        state.lastMessageId = saved.lastMessageId || 0;
      }
    } catch (e) { /* ignore */ }
  }

  // ─── API ────────────────────────────────────────────────────
  async function apiCall(endpoint, data = {}) {
    const url = `${CONFIG.serverUrl}/shopify/chat/${endpoint}`;
    try {
      if (window.UGURLAR_CHAT_DEBUG) debugLog(`→ POST ${endpoint}: ${JSON.stringify(data).substring(0, 200)}`);
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const json = await resp.json();
      if (window.UGURLAR_CHAT_DEBUG) debugLog(`← ${endpoint}: ${JSON.stringify(json).substring(0, 200)}`);
      return json;
    } catch (e) {
      if (window.UGURLAR_CHAT_DEBUG) debugLog(`❌ ${endpoint} HATA: ${e.message}`);
      console.warn('[UgurlarChat] API hatası:', e);
      return { success: false, error: 'Sunucuya bağlanılamadı' };
    }
  }

  function debugLog(msg) {
    const el = document.getElementById('debug');
    if (el) {
      el.textContent += `[${new Date().toLocaleTimeString('tr-TR')}] ${msg}\n`;
      el.scrollTop = el.scrollHeight;
    }
    console.log('[UgurlarChat]', msg);
  }

  // ─── SOHBET BAŞLAT ──────────────────────────────────────────
  async function startConversation() {
    const result = await apiCall('start', {
      shop_domain: CONFIG.shopDomain,
      customer_name: state.customerName,
      customer_email: state.customerEmail,
      page_url: window.location.href,
      page_title: document.title,
      conversation_uid: state.conversationUid,
    });

    if (result.success) {
      state.conversationUid = result.conversation_uid;
      state.operatorName = result.operator_name;
      saveState();

      // Geçmiş mesajları yükle
      await loadHistory();
      startPolling();
    }
    return result;
  }

  // ─── MESAJ GÖNDER ───────────────────────────────────────────
  async function sendMessage(text) {
    if (!text || !text.trim()) return;
    text = text.trim();

    if (!state.conversationUid) {
      await startConversation();
    }

    // Optimistik UI — mesajı hemen göster
    const tempMsg = {
      id: Date.now(),
      text: text,
      sender_type: 'customer',
      sender_name: state.customerName || 'Ben',
      sent_date: new Date().toISOString(),
      _pending: true,
    };
    state.messages.push(tempMsg);
    renderMessages();

    const result = await apiCall('send', {
      conversation_uid: state.conversationUid,
      message: text,
      customer_name: state.customerName,
      customer_email: state.customerEmail,
    });

    if (result.success) {
      tempMsg._pending = false;
      tempMsg.id = result.message_id;
      state.lastMessageId = Math.max(state.lastMessageId, result.message_id);
      saveState();
      // Polling hızlandır — cevap bekleniyor
      state.currentPollInterval = CONFIG.pollInterval;
    } else {
      tempMsg._error = true;
    }
    renderMessages();
  }

  // ─── POLLING ────────────────────────────────────────────────
  function startPolling() {
    stopPolling();
    poll();
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
  }

  async function poll() {
    if (!state.conversationUid) return;

    const result = await apiCall('poll', {
      conversation_uid: state.conversationUid,
      last_message_id: state.lastMessageId,
    });

    if (result.success && result.messages && result.messages.length > 0) {
      let hasNew = false;
      result.messages.forEach(msg => {
        if (!state.messages.find(m => m.id === msg.id)) {
          state.messages.push(msg);
          hasNew = true;
          state.lastMessageId = Math.max(state.lastMessageId, msg.id);
        }
      });
      if (hasNew) {
        saveState();
        renderMessages();
        if (!state.isOpen) {
          state.unreadCount += result.messages.length;
          renderBadge();
        }
        playNotificationSound();
      }
      // Yeni mesaj geldi — hızlı polling
      state.currentPollInterval = CONFIG.pollInterval;
    } else {
      // Yeni mesaj yok — yavaş polling
      state.currentPollInterval = Math.min(state.currentPollInterval * 1.3, CONFIG.maxPollInterval);
    }

    if (result.operator_name) state.operatorName = result.operator_name;

    // Sonraki poll
    state.pollTimer = setTimeout(poll, state.currentPollInterval);
  }

  // ─── GEÇMİŞ YÜKLE ─────────────────────────────────────────
  async function loadHistory() {
    if (!state.conversationUid) return;
    const result = await apiCall('history', {
      conversation_uid: state.conversationUid,
    });
    if (result.success && result.messages) {
      state.messages = result.messages;
      if (result.messages.length > 0) {
        state.lastMessageId = Math.max(...result.messages.map(m => m.id));
      }
      if (result.conversation) {
        state.operatorName = result.conversation.operator_name;
      }
      renderMessages();
      saveState();
    }
  }

  // ─── HIZLI CEVAPLAR ────────────────────────────────────────
  async function loadQuickReplies() {
    const result = await apiCall('quick-replies', {});
    if (result.success && result.quick_replies) {
      state.quickReplies = result.quick_replies;
      renderQuickReplies();
    }
  }

  // ─── SES BİLDİRİMİ ─────────────────────────────────────────
  function playNotificationSound() {
    if (!CONFIG.soundEnabled) return;
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 800;
      osc.type = 'sine';
      gain.gain.setValueAtTime(0.1, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.3);
    } catch (e) { /* ignore */ }
  }

  // ─── RENDER ─────────────────────────────────────────────────
  function renderWidget() {
    // Ana container
    const container = document.createElement('div');
    container.id = 'ugurlar-chat-widget';
    container.innerHTML = `
      <div id="uc-bubble" title="Canlı Destek">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
        <span id="uc-badge" class="uc-hidden">0</span>
      </div>
      <div id="uc-window" class="uc-hidden">
        <div id="uc-header">
          <div id="uc-header-info">
            <div id="uc-header-avatar">U</div>
            <div>
              <div id="uc-header-title">${CONFIG.brandName}</div>
              <div id="uc-header-status">Çevrimiçi</div>
            </div>
          </div>
          <div id="uc-header-actions">
            <button id="uc-minimize" title="Küçült">─</button>
            <button id="uc-close" title="Kapat">✕</button>
          </div>
        </div>
        <div id="uc-body">
          <div id="uc-messages"></div>
          <div id="uc-quick-replies"></div>
          <div id="uc-typing" class="uc-hidden">
            <div class="uc-typing-dots"><span></span><span></span><span></span></div>
            <span>Yazıyor...</span>
          </div>
        </div>
        <div id="uc-footer">
          <div id="uc-input-area">
            <input type="text" id="uc-input" placeholder="${CONFIG.placeholder}" maxlength="5000" autocomplete="off"/>
            <button id="uc-send" title="Gönder">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
              </svg>
            </button>
          </div>
          <div id="uc-powered">Uğurlar Destek</div>
        </div>
      </div>
    `;
    document.body.appendChild(container);

    // Event listeners
    document.getElementById('uc-bubble').addEventListener('click', toggleChat);
    document.getElementById('uc-close').addEventListener('click', closeChat);
    document.getElementById('uc-minimize').addEventListener('click', minimizeChat);
    document.getElementById('uc-send').addEventListener('click', handleSend);
    document.getElementById('uc-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });
  }

  function renderMessages() {
    const container = document.getElementById('uc-messages');
    if (!container) return;

    container.innerHTML = state.messages.map(msg => {
      const isCustomer = msg.sender_type === 'customer';
      const isBot = msg.sender_type === 'bot';
      const isSystem = msg.sender_type === 'system';
      const time = msg.sent_date ? new Date(msg.sent_date).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }) : '';
      const pendingClass = msg._pending ? ' uc-pending' : '';
      const errorClass = msg._error ? ' uc-error' : '';

      if (isSystem) {
        return `<div class="uc-msg-system">${escapeHtml(msg.text)}</div>`;
      }

      return `
        <div class="uc-msg ${isCustomer ? 'uc-msg-customer' : 'uc-msg-operator'}${pendingClass}${errorClass}">
          ${!isCustomer ? `<div class="uc-msg-avatar">${isBot ? '🤖' : '👤'}</div>` : ''}
          <div class="uc-msg-content">
            ${!isCustomer ? `<div class="uc-msg-sender">${escapeHtml(msg.sender_name || '')}</div>` : ''}
            <div class="uc-msg-text">${escapeHtml(msg.text)}</div>
            <div class="uc-msg-time">${time}${msg._pending ? ' ⏳' : ''}${msg._error ? ' ❌' : ''}</div>
          </div>
        </div>
      `;
    }).join('');

    // Scroll to bottom
    container.scrollTop = container.scrollHeight;
  }

  function renderQuickReplies() {
    const container = document.getElementById('uc-quick-replies');
    if (!container || state.quickReplies.length === 0) return;
    if (state.messages.length > 2) {
      container.innerHTML = '';
      return;
    }

    container.innerHTML = state.quickReplies.map(qr =>
      `<button class="uc-qr-btn" data-msg="${escapeAttr(qr.message)}">${qr.label}</button>`
    ).join('');

    container.querySelectorAll('.uc-qr-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        sendMessage(btn.dataset.msg);
        container.innerHTML = '';
      });
    });
  }

  function renderBadge() {
    const badge = document.getElementById('uc-badge');
    if (!badge) return;
    if (state.unreadCount > 0) {
      badge.textContent = state.unreadCount;
      badge.classList.remove('uc-hidden');
    } else {
      badge.classList.add('uc-hidden');
    }
  }

  // ─── CHAT ACTIONS ───────────────────────────────────────────
  async function toggleChat() {
    if (state.isOpen) {
      closeChat();
    } else {
      openChat();
    }
  }

  async function openChat() {
    state.isOpen = true;
    state.unreadCount = 0;
    renderBadge();
    const win = document.getElementById('uc-window');
    const bubble = document.getElementById('uc-bubble');
    if (win) win.classList.remove('uc-hidden');
    if (bubble) bubble.classList.add('uc-hidden');

    if (!state.conversationUid) {
      await startConversation();
      await loadQuickReplies();
    } else {
      await loadHistory();
      startPolling();
    }

    // Focus input
    setTimeout(() => {
      const input = document.getElementById('uc-input');
      if (input) input.focus();
    }, 300);
  }

  function closeChat() {
    state.isOpen = false;
    const win = document.getElementById('uc-window');
    const bubble = document.getElementById('uc-bubble');
    if (win) win.classList.add('uc-hidden');
    if (bubble) bubble.classList.remove('uc-hidden');
    stopPolling();
  }

  function minimizeChat() {
    closeChat();
  }

  function handleSend() {
    const input = document.getElementById('uc-input');
    if (!input) return;
    const text = input.value;
    input.value = '';
    sendMessage(text);
    input.focus();
  }

  // ─── UTILS ──────────────────────────────────────────────────
  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function escapeAttr(str) {
    return str.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // ─── CSS ────────────────────────────────────────────────────
  function injectStyles() {
    const style = document.createElement('style');
    style.textContent = `
      #ugurlar-chat-widget { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; line-height: 1.5; z-index: 999999; }
      #ugurlar-chat-widget * { box-sizing: border-box; margin: 0; padding: 0; }

      /* ─── BUBBLE ─── */
      #uc-bubble {
        position: fixed; bottom: 24px; right: 24px; width: 60px; height: 60px;
        background: linear-gradient(135deg, ${CONFIG.brandColor}, ${CONFIG.accentColor});
        border-radius: 50%; display: flex; align-items: center; justify-content: center;
        cursor: pointer; color: #fff; box-shadow: 0 4px 24px rgba(0,0,0,0.25);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
        animation: uc-pulse 2s infinite;
      }
      #uc-bubble:hover { transform: scale(1.1); box-shadow: 0 6px 32px rgba(0,0,0,0.35); }
      @keyframes uc-pulse {
        0%, 100% { box-shadow: 0 4px 24px rgba(0,0,0,0.25); }
        50% { box-shadow: 0 4px 24px rgba(233,69,96,0.4); }
      }

      /* ─── BADGE ─── */
      #uc-badge {
        position: absolute; top: -4px; right: -4px; min-width: 20px; height: 20px;
        background: #ff3b3b; color: #fff; border-radius: 10px; font-size: 11px;
        font-weight: 700; display: flex; align-items: center; justify-content: center;
        padding: 0 5px; border: 2px solid #fff;
      }

      /* ─── WINDOW ─── */
      #uc-window {
        position: fixed; bottom: 24px; right: 24px; width: 380px; height: 560px;
        background: #fff; border-radius: 16px; display: flex; flex-direction: column;
        box-shadow: 0 8px 48px rgba(0,0,0,0.18); overflow: hidden;
        animation: uc-slideUp 0.3s ease;
      }
      @keyframes uc-slideUp {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
      }

      /* ─── HEADER ─── */
      #uc-header {
        background: linear-gradient(135deg, ${CONFIG.brandColor}, ${CONFIG.accentColor});
        color: #fff; padding: 16px; display: flex; align-items: center;
        justify-content: space-between; flex-shrink: 0;
      }
      #uc-header-info { display: flex; align-items: center; gap: 12px; }
      #uc-header-avatar {
        width: 40px; height: 40px; background: rgba(255,255,255,0.2);
        border-radius: 50%; display: flex; align-items: center; justify-content: center;
        font-weight: 700; font-size: 16px;
      }
      #uc-header-title { font-weight: 600; font-size: 15px; }
      #uc-header-status { font-size: 12px; opacity: 0.8; }
      #uc-header-status::before {
        content: ''; display: inline-block; width: 8px; height: 8px;
        background: #4ade80; border-radius: 50%; margin-right: 6px;
      }
      #uc-header-actions { display: flex; gap: 8px; }
      #uc-header-actions button {
        background: rgba(255,255,255,0.15); border: none; color: #fff;
        width: 28px; height: 28px; border-radius: 6px; cursor: pointer;
        font-size: 14px; display: flex; align-items: center; justify-content: center;
        transition: background 0.2s;
      }
      #uc-header-actions button:hover { background: rgba(255,255,255,0.3); }

      /* ─── BODY ─── */
      #uc-body { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: #f8f9fb; }
      #uc-messages {
        flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column;
        gap: 8px; scroll-behavior: smooth;
      }
      #uc-messages::-webkit-scrollbar { width: 4px; }
      #uc-messages::-webkit-scrollbar-thumb { background: #ccc; border-radius: 2px; }

      /* ─── MESSAGES ─── */
      .uc-msg { display: flex; gap: 8px; max-width: 85%; animation: uc-fadeIn 0.2s ease; }
      @keyframes uc-fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
      .uc-msg-customer { align-self: flex-end; flex-direction: row-reverse; }
      .uc-msg-operator { align-self: flex-start; }
      .uc-msg-avatar {
        width: 30px; height: 30px; border-radius: 50%; display: flex;
        align-items: center; justify-content: center; font-size: 16px;
        background: #e8eaed; flex-shrink: 0;
      }
      .uc-msg-content { display: flex; flex-direction: column; gap: 2px; }
      .uc-msg-sender { font-size: 11px; color: #888; font-weight: 500; }
      .uc-msg-text {
        padding: 10px 14px; border-radius: 16px; font-size: 13.5px;
        line-height: 1.5; word-wrap: break-word; white-space: pre-wrap;
      }
      .uc-msg-customer .uc-msg-text {
        background: linear-gradient(135deg, ${CONFIG.brandColor}, ${CONFIG.accentColor});
        color: #fff; border-bottom-right-radius: 4px;
      }
      .uc-msg-operator .uc-msg-text {
        background: #fff; color: #333; border: 1px solid #e8eaed;
        border-bottom-left-radius: 4px;
      }
      .uc-msg-time { font-size: 10px; color: #aaa; padding: 0 4px; }
      .uc-msg-customer .uc-msg-time { text-align: right; }
      .uc-msg-system {
        text-align: center; font-size: 12px; color: #999; padding: 8px;
        font-style: italic;
      }
      .uc-pending .uc-msg-text { opacity: 0.7; }
      .uc-error .uc-msg-text { border: 1px solid #ff3b3b; }

      /* ─── QUICK REPLIES ─── */
      #uc-quick-replies {
        display: flex; flex-wrap: wrap; gap: 6px; padding: 0 16px 12px;
      }
      .uc-qr-btn {
        background: #fff; border: 1.5px solid ${CONFIG.accentColor}; color: ${CONFIG.accentColor};
        padding: 6px 14px; border-radius: 20px; font-size: 12.5px; cursor: pointer;
        transition: all 0.2s; font-weight: 500; white-space: nowrap;
      }
      .uc-qr-btn:hover {
        background: ${CONFIG.accentColor}; color: #fff;
        transform: translateY(-1px); box-shadow: 0 2px 8px rgba(233,69,96,0.3);
      }

      /* ─── TYPING ─── */
      #uc-typing {
        display: flex; align-items: center; gap: 8px; padding: 8px 16px;
        font-size: 12px; color: #888;
      }
      .uc-typing-dots { display: flex; gap: 3px; }
      .uc-typing-dots span {
        width: 6px; height: 6px; background: #bbb; border-radius: 50%;
        animation: uc-dotBounce 1.2s infinite;
      }
      .uc-typing-dots span:nth-child(2) { animation-delay: 0.2s; }
      .uc-typing-dots span:nth-child(3) { animation-delay: 0.4s; }
      @keyframes uc-dotBounce {
        0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
        40% { transform: scale(1); opacity: 1; }
      }

      /* ─── FOOTER ─── */
      #uc-footer { border-top: 1px solid #eee; background: #fff; flex-shrink: 0; }
      #uc-input-area {
        display: flex; align-items: center; gap: 8px; padding: 12px 16px;
      }
      #uc-input {
        flex: 1; border: 1.5px solid #e0e0e0; border-radius: 24px; padding: 10px 16px;
        font-size: 13.5px; outline: none; transition: border-color 0.2s;
        font-family: inherit;
      }
      #uc-input:focus { border-color: ${CONFIG.accentColor}; }
      #uc-input::placeholder { color: #bbb; }
      #uc-send {
        width: 40px; height: 40px; border-radius: 50%; border: none;
        background: linear-gradient(135deg, ${CONFIG.brandColor}, ${CONFIG.accentColor});
        color: #fff; cursor: pointer; display: flex; align-items: center;
        justify-content: center; transition: transform 0.2s, box-shadow 0.2s;
        flex-shrink: 0;
      }
      #uc-send:hover { transform: scale(1.05); box-shadow: 0 2px 12px rgba(233,69,96,0.4); }
      #uc-send:active { transform: scale(0.95); }
      #uc-powered {
        text-align: center; font-size: 10px; color: #ccc; padding: 4px 0 8px;
      }

      /* ─── HIDDEN ─── */
      .uc-hidden { display: none !important; }

      /* ─── MOBİL ─── */
      @media (max-width: 480px) {
        #uc-window {
          width: 100vw; height: 100vh; bottom: 0; right: 0;
          border-radius: 0; max-height: 100%;
        }
        #uc-bubble { bottom: 16px; right: 16px; width: 54px; height: 54px; }
      }
    `;
    document.head.appendChild(style);
  }

  // ─── INIT ───────────────────────────────────────────────────
  function init() {
    // Shopify Checkout sayfalarında gösterme
    if (window.location.pathname.includes('/checkout')) return;

    loadState();
    injectStyles();
    renderWidget();

    // Shopify müşteri bilgilerini al (giriş yapmışsa)
    if (window.ShopifyAnalytics && window.ShopifyAnalytics.meta) {
      const meta = window.ShopifyAnalytics.meta;
      if (meta.page && meta.page.customerId) {
        // Giriş yapmış müşteri
      }
    }

    // Sayfa kapanırken polling durdur
    window.addEventListener('beforeunload', stopPolling);
  }

  // DOM hazır olduğunda başlat
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
