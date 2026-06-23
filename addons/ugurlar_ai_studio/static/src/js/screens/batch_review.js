/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class BatchReview extends Component {
    static template = "ugurlar_ai_studio.BatchReview";
    static props = {
        onBackToScan: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ sessions: [] });

        onWillStart(async () => {
            const sessions = await this.orm.searchRead(
                "ai.studio.session",
                [["state", "=", "review"]],
                ["name", "product_id", "generation_count", "approval_rate", "create_date"],
                { limit: 50, order: "create_date desc" }
            );
            this.state.sessions = sessions;
        });
    }

    async openSession(sessionId) {
        // Backend form view'a git
        await this.env.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: "ai.studio.session",
            res_id: sessionId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}
