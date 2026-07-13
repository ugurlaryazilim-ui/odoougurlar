/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";

export class SocialInbox extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.chatContainerRef = useRef("chatMessagesContainer");
        this.galleryInputRef = useRef("galleryInput");
        this.cameraInputRef = useRef("cameraInput");
        this.productSearchInputRef = useRef("productSearchInput");
        
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
        });

        onWillStart(async () => {
            await this.loadConversations();
        });
        
        onMounted(() => {
            // Live Polling every 10 seconds
            this.pollInterval = setInterval(async () => {
                await this.loadConversations();
                if (this.state.activeConversation) {
                    // Save scroll position before reload to see if we need to auto-scroll
                    const isAtBottom = this.chatContainerRef.el ? 
                        (this.chatContainerRef.el.scrollHeight - this.chatContainerRef.el.scrollTop <= this.chatContainerRef.el.clientHeight + 50) : false;
                    
                    await this.loadMessages(this.state.activeConversation.id);
                    
                    if (isAtBottom) {
                        setTimeout(() => this.scrollToBottom(), 50);
                    }
                }
            }, 10000);
            this.scrollToBottom();
        });
        
        onPatched(() => {
            // Scroll to bottom after state changes if needed
            this.scrollToBottom();
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

    async loadConversations() {
        this.state.conversations = await this.orm.searchRead(
            "social.media.conversation",
            [],
            ["id", "name", "platform", "unread_count", "state", "user_id"],
            { order: "last_message_date desc" }
        );
    }

    async selectConversation(convId) {
        this.state.activeConversation = this.state.conversations.find(c => c.id === convId);
        this.state.showChatOnMobile = true;
        
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

    async loadMessages(convId) {
        this.state.messages = await this.orm.searchRead(
            "social.media.message",
            [["conversation_id", "=", convId]],
            ["id", "content", "message_type", "date", "is_read", "post_link", "has_attachment"],
            { order: "date asc" }
        );
    }

    onKeyup(ev) {
        if (ev.key === "Enter") {
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
