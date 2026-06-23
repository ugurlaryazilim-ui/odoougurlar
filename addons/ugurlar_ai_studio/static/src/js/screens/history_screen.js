/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class HistoryScreen extends Component {
    static template = "ugurlar_ai_studio.HistoryScreen";
    static props = {
        dashboardStats: { type: Object },
        onBackToScan: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ recentSessions: [] });

        onWillStart(async () => {
            const sessions = await this.orm.searchRead(
                "ai.studio.session",
                [],
                ["name", "product_id", "state", "total_cost", "approval_rate", "create_date"],
                { limit: 20, order: "create_date desc" }
            );
            this.state.recentSessions = sessions;
        });
    }

    getStateIcon(state) {
        const icons = {
            draft: "📝", photos_ready: "📸", preprocessing: "🔄",
            processing: "⏳", review: "👁️", done: "✅", cancelled: "❌",
        };
        return icons[state] || "❓";
    }
}
