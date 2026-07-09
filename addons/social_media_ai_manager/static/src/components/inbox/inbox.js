/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

export class SocialInbox extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        
        this.state = useState({
            conversations: [],
            activeConversation: null,
            messages: [],
            newMessage: "",
            showChatOnMobile: false,
        });

        onWillStart(async () => {
            await this.loadConversations();
        });
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
            ["id", "name", "platform", "unread_count", "state"],
            { order: "last_message_date desc" }
        );
    }

    async selectConversation(convId) {
        this.state.activeConversation = this.state.conversations.find(c => c.id === convId);
        this.state.showChatOnMobile = true;
        await this.loadMessages(convId);
    }
    
    backToList() {
        this.state.showChatOnMobile = false;
        // Optionally clear active conversation: this.state.activeConversation = null;
    }

    formatTime(dateStr) {
        if (!dateStr) return "";
        try {
            // Odoo returns UTC strings like "2026-07-09 14:30:00"
            // Convert to local time
            let utcDate = dateStr;
            if (!dateStr.endsWith('Z')) {
                utcDate = dateStr.replace(' ', 'T') + 'Z';
            }
            const date = new Date(utcDate);
            return date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        } catch(e) {
            return dateStr;
        }
    }

    async loadMessages(convId) {
        this.state.messages = await this.orm.searchRead(
            "social.media.message",
            [["conversation_id", "=", convId]],
            ["id", "content", "message_type", "date", "is_read", "post_link"],
            { order: "date asc" }
        );
    }

    onKeyup(ev) {
        if (ev.key === "Enter") {
            this.sendMessage();
        }
    }

    async sendMessage() {
        if (!this.state.newMessage.trim() || !this.state.activeConversation) return;
        
        await this.orm.create("social.media.message", [{
            conversation_id: this.state.activeConversation.id,
            content: this.state.newMessage,
            message_type: "outgoing",
        }]);
        
        this.state.newMessage = "";
        await this.loadMessages(this.state.activeConversation.id);
    }
    
    async handoffToHuman() {
        if (!this.state.activeConversation) return;
        await this.orm.write("social.media.conversation", [this.state.activeConversation.id], {
            state: "open"
        });
        this.state.activeConversation.state = "open";
    }
}

SocialInbox.template = "social_media_ai_manager.SocialInbox";

registry.category("actions").add("social_media_ai.inbox", SocialInbox);
