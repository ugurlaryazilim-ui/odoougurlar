/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";

const CONV_PAGE = 100;
const MSG_PAGE = 200;

export class SocialInbox extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.chatContainerRef = useRef("chatMessagesContainer");
        this.galleryInputRef = useRef("galleryInput");
        this.cameraInputRef = useRef("cameraInput");
        this.productSearchInputRef = useRef("productSearchInput");
        this.messageInputRef = useRef("messageInput");
        
        this.state = useState({
            conversations: [],
            activeConversation: null,
            messages: [],
            newMessage: "",
            showChatOnMobile: false,
            attachmentData: null,
            attachmentPreview: null,
            attachmentName: null,
            showProductSearch: false,
            productQuery: "",
            productResults: [],
            // NEDEN: ilk sayfa eskisiyle aynı (100 görüşme / 200 mesaj); fazlası "daha fazla yükle" ile istenir.
            // Yoklama mevcut sınırla yeniden okur, böylece yüklenmiş sayfalar kaybolmaz.
            convLimit: CONV_PAGE,
            msgLimit: MSG_PAGE,
            hasMoreConvs: false,
            hasMoreMsgs: false,
        });

        onWillStart(async () => {
            await this.loadConversations();
        });
        
        onMounted(() => {
            // Live Polling every 10 seconds
            // NEDEN: gizli sekmede ve önceki tur bitmeden sorgu atılmaz (10 sn'de bir limitsiz okuma sunucuyu yoruyordu).
            this.pollInterval = setInterval(async () => {
                if (document.hidden || this._polling) {
                    return;
                }
                this._polling = true;
                try {
                    await this._pollOnce();
                } catch (e) {
                    // geçici ağ/sunucu hatası: sonraki turda yeniden denenir
                } finally {
                    this._polling = false;
                }
            }, 10000);
            this.scrollToBottom();
        });
        
        onPatched(() => {
            // NEDEN (A5 B1/B2): eskiden her yamada koşulsuz en alta kaydırılıyordu; "önceki mesajlar" yükleyince
            // ve geçmişi okuyan kullanıcıda 10 sn'lik yoklama konumu bozuyordu. Artık kaydırma niyeti
            // loadMessages'ta (mesajlar state'e yazıldığı AYNI anda) belirlenir; niyet yoksa konuma dokunulmaz.
            const el = this.chatContainerRef.el;
            const intent = this._scrollIntent;
            if (!intent || !el) {
                return;
            }
            this._scrollIntent = null;
            if (intent.fromBottom !== undefined) {
                // yeni içerik üste eklendi: alttan uzaklık sabit kalırsa okunan satır yerinde durur
                el.scrollTop = el.scrollHeight - intent.fromBottom;
            } else {
                this.scrollToBottom();
            }
        });
        
        onWillUnmount(() => {
            if (this.pollInterval) {
                clearInterval(this.pollInterval);
            }
        });
    }

    scrollToBottom() {
        if (this.chatContainerRef.el) {
            this.chatContainerRef.el.scrollTop = this.chatContainerRef.el.scrollHeight;
        }
    }

    t(enStr) {
        let isTR = true; // Fallback default to Turkish for this specific user's system
        try {
            if (user && user.lang) {
                isTR = user.lang.startsWith("tr");
            }
        } catch(e) {}
        
        if (isTR) {
            const trMap = {
                "Conversations": "Görüşmeler",
                "Handoff to Human": "İnsana Devret",
                "Type a message...": "Bir mesaj yazın...",
                "Send": "Gönder",
                "Select a conversation to start messaging": "Mesajlaşmaya başlamak için bir görüşme seçin"
            };
            if (trMap[enStr]) return trMap[enStr];
        }
        
        try {
            const translated = _t(enStr);
            if (translated && translated !== enStr) return translated;
        } catch(e) {}
        
        return enStr;
    }

    async _pollOnce() {
        await this.loadConversations();
        if (this.state.activeConversation) {
            // kaydırma kararı (alttaysa alta, değilse konumu koru) loadMessages içinde verilir
            await this.loadMessages(this.state.activeConversation.id);
        }
    }

    async loadConversations() {
        // NEDEN: limit+1 satır istenir; fazla gelen satır "devamı var" işaretidir, listeye girmez.
        const rows = await this.orm.searchRead(
            "social.media.conversation",
            [],
            ["id", "name", "platform", "unread_count", "state", "user_id"],
            { order: "last_message_date desc", limit: this.state.convLimit + 1 }
        );
        this.state.hasMoreConvs = rows.length > this.state.convLimit;
        this.state.conversations = rows.slice(0, this.state.convLimit);
    }

    async loadMoreConversations() {
        this.state.convLimit += CONV_PAGE;
        await this.loadConversations();
    }

    async loadMoreMessages() {
        this.state.msgLimit += MSG_PAGE;
        await this.loadMessages(this.state.activeConversation.id, { keepPosition: true });
    }

    async selectConversation(convId) {
        this.state.activeConversation = this.state.conversations.find(c => c.id === convId);
        this.state.showChatOnMobile = true;
        if (this.state.activeConversation?.id !== this._msgConvId) {
            this.state.msgLimit = MSG_PAGE;  // başka görüşme: sayfalama baştan
        }
        
        // CRM: Mark as read
        await this.orm.call("social.media.conversation", "mark_as_read", [[convId]]);
        if (this.state.activeConversation) {
            this.state.activeConversation.unread_count = 0;
        }
        
        await this.loadMessages(convId);
        setTimeout(() => this.scrollToBottom(), 50);
    }
    
    backToList() {
        this.state.showChatOnMobile = false;
    }

    formatTime(dateStr) {
        if (!dateStr) return "";
        try {
            let utcDate = dateStr;
            if (!dateStr.endsWith('Z')) {
                utcDate = dateStr.replace(' ', 'T') + 'Z';
            }
            const date = new Date(utcDate);
            const today = new Date();
            const yesterday = new Date();
            yesterday.setDate(yesterday.getDate() - 1);
            
            const timeStr = date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
            
            if (date.toDateString() === today.toDateString()) {
                return timeStr;
            } else if (date.toDateString() === yesterday.toDateString()) {
                return `Dün ${timeStr}`;
            } else {
                const dateFmt = date.toLocaleDateString([], {day: 'numeric', month: 'short'});
                return `${dateFmt} ${timeStr}`;
            }
        } catch(e) {
            return dateStr;
        }
    }

    async loadMessages(convId, { keepPosition = false } = {}) {
        // NEDEN: uzun görüşmede tüm geçmiş her 10 sn okunmasın; son msgLimit mesaj (en yeni → eski çekilip çevrilir).
        // Fazla gelen 1 satır eski mesaj olduğunu gösterir ("önceki mesajları yükle" düğmesi).
        const msgs = await this.orm.searchRead(
            "social.media.message",
            [["conversation_id", "=", convId]],
            ["id", "content", "message_type", "date", "is_read", "post_link", "has_attachment"],
            { order: "date desc, id desc", limit: this.state.msgLimit + 1 }
        );
        const next = msgs.slice(0, this.state.msgLimit).reverse();
        this._decideScroll(convId, next, keepPosition);
        this.state.hasMoreMsgs = msgs.length > this.state.msgLimit;
        this.state.messages = next;
        this._msgConvId = convId;
    }

    _decideScroll(convId, next, keepPosition) {
        // DIKKAT: state yazılmadan hemen önce çağrılır; böylece niyeti tüketen yama mutlaka bu mesajları
        // içeren yamadır (araya giren görüşme listesi yamaları niyeti harcayamaz).
        const el = this.chatContainerRef.el;
        if (this._msgConvId !== convId || !el) {
            this._scrollIntent = { bottom: true };   // başka görüşme / ilk çizim: en alta
            return;
        }
        if (keepPosition) {
            this._scrollIntent = { fromBottom: el.scrollHeight - el.scrollTop };
            return;
        }
        const atBottom = el.scrollHeight - el.scrollTop <= el.clientHeight + 50;
        const prev = this.state.messages;
        const hasNew = next.length > 0 && (prev.length === 0 || prev.at(-1).id !== next.at(-1).id);
        // yeni mesaj yalnız kullanıcı zaten alttaysa alta kaydırır; geçmişi okuyanın konumu korunur
        this._scrollIntent = atBottom && hasNew ? { bottom: true } : null;
    }

    autoResizeInput(ev) {
        const el = ev.target;
        el.style.height = "auto";
        el.style.height = (el.scrollHeight) + "px";
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    async sendMessage() {
        if (!this.state.newMessage.trim() && !this.state.attachmentData) return;
        if (!this.state.activeConversation) return;
        
        await this.orm.create("social.media.message", [{
            conversation_id: this.state.activeConversation.id,
            content: this.state.newMessage.trim() || "[GÖRSEL]",
            message_type: "outgoing",
            attachment: this.state.attachmentData,
            attachment_name: this.state.attachmentName
        }]);
        
        this.state.newMessage = "";
        if (this.messageInputRef.el) {
            this.messageInputRef.el.style.height = "auto";
        }
        this.removeAttachment();
        await this.loadMessages(this.state.activeConversation.id);
        setTimeout(() => this.scrollToBottom(), 50);
    }

    triggerGalleryInput() {
        if (this.galleryInputRef.el) {
            this.galleryInputRef.el.click();
        }
    }

    triggerCameraInput() {
        if (this.cameraInputRef.el) {
            this.cameraInputRef.el.click();
        }
    }

    onFileChange(ev) {
        const file = ev.target.files[0];
        if (!file) return;

        this.state.attachmentName = file.name;
        
        const reader = new FileReader();
        reader.onload = (e) => {
            this.state.attachmentPreview = e.target.result;
            this.state.attachmentData = e.target.result.split(',')[1];
        };
        reader.readAsDataURL(file);
    }

    removeAttachment() {
        this.state.attachmentData = null;
        this.state.attachmentPreview = null;
        this.state.attachmentName = null;
        if (this.galleryInputRef.el) {
            this.galleryInputRef.el.value = "";
        }
        if (this.cameraInputRef.el) {
            this.cameraInputRef.el.value = "";
        }
    }

    openProductSearch() {
        this.state.showProductSearch = true;
        this.state.productQuery = "";
        this.state.productResults = [];
        setTimeout(() => {
            if (this.productSearchInputRef.el) {
                this.productSearchInputRef.el.focus();
            }
        }, 100);
    }

    closeProductSearch() {
        this.state.showProductSearch = false;
    }

    async searchProduct(ev) {
        if (ev && ev.key === "Enter" || this.state.productQuery.length > 2) {
            this.state.productResults = await this.orm.call(
                "social.media.message",
                "search_product_for_chat",
                [this.state.productQuery]
            );
        }
    }

    selectProduct(prod) {
        this.state.newMessage += (this.state.newMessage ? "\n\n" : "") + prod.chat_text;
        this.closeProductSearch();
        setTimeout(() => {
            if (this.messageInputRef.el) {
                const el = this.messageInputRef.el;
                el.focus();
                el.selectionStart = el.selectionEnd = el.value.length;
                el.style.height = "auto";
                el.style.height = el.scrollHeight + "px";
            }
        }, 50);
    }

    startBarcodeScanner() {
        openCameraScanner((barcode) => {
            if (barcode) {
                this.state.productQuery = barcode;
                this.searchProduct({ key: "Enter" });
            }
        });
    }
    
    async handoffToHuman() {
        if (!this.state.activeConversation) return;
        await this.orm.call("social.media.conversation", "action_handoff_to_human", [[this.state.activeConversation.id]]);
        
        // Reload conversations to get the newly assigned user_id and state
        await this.loadConversations();
        this.state.activeConversation = this.state.conversations.find(c => c.id === this.state.activeConversation.id);
    }
}

SocialInbox.template = "social_media_ai_manager.SocialInbox";

registry.category("actions").add("social_media_ai.inbox", SocialInbox);
