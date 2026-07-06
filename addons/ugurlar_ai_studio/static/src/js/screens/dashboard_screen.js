/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class AiStudioDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        
        this.state = useState({
            overview: {},
            leaderboard: [],
            past_winners: [],
            my_stats: {}
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        const data = await this.orm.call("ai.studio.leaderboard", "get_dashboard_data", []);
        this.state.overview = data.overview;
        this.state.leaderboard = data.leaderboard;
        this.state.past_winners = data.past_winners;
        this.state.my_stats = data.my_stats;
    }
}

AiStudioDashboard.template = "ugurlar_ai_studio.DashboardScreen";

// Register action
registry.category("actions").add("ai_studio_dashboard_action", AiStudioDashboard);
