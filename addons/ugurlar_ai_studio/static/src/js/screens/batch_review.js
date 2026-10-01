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
        this.state = useState({ sessions: [], inRevisionCount: 0 });

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
        // Revizesi süren oturumlar yeni sürüm bitene kadar listede gösterilmez
        const queue = await this.orm.call("ai.studio.session", "get_review_queue", []);
        this.state.sessions = queue.sessions;
        this.state.inRevisionCount = queue.in_revision_count;
    }

    async openSession(sessionId) {
        // Form yerine doğrudan inceleme popup'ı (onay, red, aday seçimi tek yerde)
        await openReviewPopup(this.env.services.action, sessionId);
    }
}
