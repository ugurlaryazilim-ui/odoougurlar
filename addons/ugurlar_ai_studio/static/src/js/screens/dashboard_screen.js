/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState, useRef, useEffect } from "@odoo/owl";

export class AiStudioDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.chartRef = useRef("rejectReasonsChart");
        this.chartInstance = null;
        
        this.state = useState({
            period: 'this_month',
            overview: {},
            leaderboard: [],
            past_winners: [],
            reject_reasons: [],
            cost_data: {},
            my_stats: {}
        });

        onWillStart(async () => {
            await this.loadData();
        });

        useEffect(() => {
            this.renderChart();
        }, () => [this.state.reject_reasons]);
    }

    async loadData() {
        const data = await this.orm.call("ai.studio.leaderboard", "get_dashboard_data", [this.state.period]);
        this.state.overview = data.overview;
        this.state.leaderboard = data.leaderboard;
        this.state.past_winners = data.past_winners;
        this.state.reject_reasons = data.reject_reasons || [];
        this.state.cost_data = data.cost_data || {};
        this.state.my_stats = data.my_stats;
    }

    async setPeriod(period) {
        if (this.state.period !== period) {
            this.state.period = period;
            await this.loadData();
        }
    }

    renderChart() {
        if (!this.chartRef.el || this.state.reject_reasons.length === 0) return;

        if (this.chartInstance) {
            this.chartInstance.destroy();
        }

        const labels = this.state.reject_reasons.map(r => r.name);
        const data = this.state.reject_reasons.map(r => r.count);
        
        // Generate beautiful distinct colors
        const colors = [
            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', 
            '#FF9F40', '#8AC926', '#1982C4', '#F15BB5', '#00BBF9'
        ];

        this.chartInstance = new Chart(this.chartRef.el, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: colors.slice(0, data.length),
                    borderWidth: 2,
                    borderColor: '#ffffff',
                    hoverOffset: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'right',
                        labels: {
                            font: {
                                family: 'Inter, sans-serif',
                                size: 12
                            }
                        }
                    }
                },
                cutout: '70%',
            }
        });
    }
}

AiStudioDashboard.template = "ugurlar_ai_studio.DashboardScreen";

// Register action
registry.category("actions").add("ai_studio_dashboard_action", AiStudioDashboard);
