/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { openReviewPopup } from "../rpc_utils";

export class BatchReview extends Component {
    static template = "ugurlar_ai_studio.BatchReview";
    static props = {
        onBackToScan: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ sessions: [] });

        onWillStart(() => this.loadSessions());
        // Popup kapanınca / başka onaycı bitirince liste bayatlamasın
        this.onFocus = () => this.loadSessions();
        onMounted(() => {
            window.addEventListener("focus", this.onFocus);
            this.refreshTimer = setInterval(() => {
                if (!document.hidden) {
                    this.loadSessions();
                }
            }, 60000);
        });
        onWillUnmount(() => {
            window.removeEventListener("focus", this.onFocus);
            clearInterval(this.refreshTimer);
        });
    }

    async loadSessions() {
        this.state.sessions = await this.orm.searchRead(
            "ai.studio.session",
            [["state", "=", "review"]],
            ["name", "product_id", "generation_count", "approval_rate", "create_date"],
            { limit: 50, order: "create_date desc" }
        );
    }

    async openSession(sessionId) {
        // Form yerine doğrudan inceleme popup'ı (onay, red, aday seçimi tek yerde)
        await openReviewPopup(this.env.services.action, sessionId);
    }
}
