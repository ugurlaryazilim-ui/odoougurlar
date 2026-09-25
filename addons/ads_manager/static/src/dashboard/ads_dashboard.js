/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { user } from "@web/core/user";
import { Component, onWillStart, onWillUnmount, useState, useRef, useEffect } from "@odoo/owl";

export class AdsManagerDashboard extends Component {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");

        this.trendChartRef = useRef("trendChart");
        this.platformChartRef = useRef("platformChart");
        this.trendChartInstance = null;
        this.platformChartInstance = null;

        this.state = useState({
            loading: true,
            period: "7d",
            platform: "all",
            currency_symbol: "",
            kpis: {
                spend: 0,
                spend_delta: 0,
                conversion_value: 0,
                revenue_delta: 0,
                clicks: 0,
                clicks_delta: 0,
                impressions: 0,
                conversions: 0,
                conversions_delta: 0,
                ctr: 0,
                cpc: 0,
                cpa: 0,
                roas: 0,
                roas_delta: 0,
            },
            charts: [],
            platform_breakdown: {},
            top_campaigns: [],
            recommendations: [],
            accounts: { total: 0, connected: 0, error: 0 },
            pacing: { total_active: 0, on_track: 0, over: 0, under: 0 },
        });

        onWillStart(async () => {
            await this.loadChartJS();
            await this.loadData();
        });

        onWillUnmount(() => {
            if (this.trendChartInstance) {
                this.trendChartInstance.destroy();
                this.trendChartInstance = null;
            }
            if (this.platformChartInstance) {
                this.platformChartInstance.destroy();
                this.platformChartInstance = null;
            }
        });

        useEffect(() => {
            if (!this.state.loading) {
                this.renderCharts();
            }
        }, () => [this.state.charts, this.state.platform_breakdown, this.state.loading]);
    }

    async loadChartJS() {
        if (window.Chart) return;
        try {
            await loadJS("/web/static/lib/Chart/Chart.js");
        } catch (e) {
            console.warn("Chart.js failed to load via loadJS:", e);
        }
    }

    async loadData() {
        this.state.loading = true;
        try {
            const data = await this.orm.call("ads.account", "get_dashboard_data", [], {
                period: this.state.period,
                platform: this.state.platform,
            }, { silent: true });

            this.state.currency_symbol = data.currency_symbol || "";
            this.state.kpis = data.kpis || this.state.kpis;
            this.state.charts = data.charts || [];
            this.state.platform_breakdown = data.platform_breakdown || {};
            this.state.top_campaigns = data.top_campaigns || [];
            this.state.recommendations = data.recommendations || [];
            this.state.accounts = data.accounts || this.state.accounts;
            this.state.pacing = data.pacing || this.state.pacing;
        } catch (error) {
            console.error("Failed to load ads dashboard data:", error);
            this.notification.add("Dashboard verileri yüklenirken hata oluştu.", {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    async setPeriod(period) {
        if (this.state.period !== period) {
            this.state.period = period;
            await this.loadData();
        }
    }

    async setPlatform(platform) {
        if (this.state.platform !== platform) {
            this.state.platform = platform;
            await this.loadData();
        }
    }

    async refresh() {
        await this.loadData();
        this.notification.add("Dashboard verileri güncellendi.", {
            type: "info",
        });
    }

    renderCharts() {
        this.renderTrendChart();
        this.renderPlatformChart();
    }

    renderTrendChart() {
        if (!this.trendChartRef.el) return;

        if (this.trendChartInstance) {
            this.trendChartInstance.destroy();
            this.trendChartInstance = null;
        }

        const labels = this.state.charts.map(d => d.date);
        const spendData = this.state.charts.map(d => d.spend);
        const revenueData = this.state.charts.map(d => d.revenue);

        const ctx = this.trendChartRef.el.getContext("2d");
        this.trendChartInstance = new Chart(ctx, {
            type: "line",
            data: {
                labels: labels,
                datasets: [
                    {
                        label: `Harcama (${this.state.currency_symbol})`,
                        data: spendData,
                        borderColor: "#6366F1",
                        backgroundColor: "rgba(99, 102, 241, 0.15)",
                        borderWidth: 2.5,
                        fill: true,
                        tension: 0.35,
                        pointRadius: 3,
                        pointHoverRadius: 6,
                        yAxisID: "y",
                    },
                    {
                        label: `Dönüşüm Değeri (${this.state.currency_symbol})`,
                        data: revenueData,
                        borderColor: "#10B981",
                        backgroundColor: "rgba(16, 185, 129, 0.1)",
                        borderWidth: 2.5,
                        fill: true,
                        tension: 0.35,
                        pointRadius: 3,
                        pointHoverRadius: 6,
                        yAxisID: "y",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: "index",
                    intersect: false,
                },
                plugins: {
                    legend: {
                        position: "top",
                        labels: {
                            usePointStyle: true,
                            font: { family: "Inter, sans-serif", size: 12 },
                        },
                    },
                    tooltip: {
                        backgroundColor: "rgba(17, 24, 39, 0.9)",
                        titleFont: { size: 13, weight: "bold" },
                        bodyFont: { size: 12 },
                        padding: 10,
                        cornerRadius: 8,
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 11 } },
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: "rgba(0, 0, 0, 0.05)" },
                        ticks: {
                            font: { size: 11 },
                            callback: (val) => `${val} ${this.state.currency_symbol}`,
                        },
                    },
                },
            },
        });
    }

    renderPlatformChart() {
        if (!this.platformChartRef.el) return;

        if (this.platformChartInstance) {
            this.platformChartInstance.destroy();
            this.platformChartInstance = null;
        }

        const breakdown = this.state.platform_breakdown;
        const platforms = Object.keys(breakdown);
        const spendValues = platforms.map(p => breakdown[p].spend);

        const labels = platforms.map(p => {
            if (p === "meta") return "Meta Ads";
            if (p === "google") return "Google Ads";
            return p.toUpperCase();
        });

        const colors = platforms.map(p => {
            if (p === "meta") return "#1877F2";
            if (p === "google") return "#EA4335";
            return "#94A3B8";
        });

        const ctx = this.platformChartRef.el.getContext("2d");
        this.platformChartInstance = new Chart(ctx, {
            type: "doughnut",
            data: {
                labels: labels.length ? labels : ["Veri Yok"],
                datasets: [
                    {
                        data: spendValues.length ? spendValues : [1],
                        backgroundColor: colors.length ? colors : ["#E2E8F0"],
                        borderWidth: 3,
                        borderColor: "#FFFFFF",
                        hoverOffset: 4,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            usePointStyle: true,
                            font: { family: "Inter, sans-serif", size: 12 },
                        },
                    },
                },
                cutout: "68%",
            },
        });
    }

    // Actions & Navigation
    openCampaign(id) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "ads.campaign",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openAllCampaigns() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Kampanyalar",
            res_model: "ads.campaign",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    openAllRecommendations() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Optimizasyon Önerileri",
            res_model: "ads.recommendation",
            views: [
                [false, "list"],
                [false, "kanban"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    openRecommendation(id) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "ads.recommendation",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openSyncWizard() {
        this.actionService.doAction("ads_manager.action_ads_sync_wizard");
    }

    openPlatformComparison() {
        this.actionService.doAction("ads_manager.action_ads_platform_comparison");
    }

    async quickApplyRecommendation(id) {
        try {
            await this.orm.call("ads.recommendation", "action_apply", [[id]]);
            this.notification.add("Öneri başarıyla uygulandı.", { type: "success" });
            await this.loadData();
        } catch (e) {
            this.notification.add(`Öneri uygulanamadı: ${e.message}`, { type: "danger" });
        }
    }

    async quickDismissRecommendation(id) {
        try {
            await this.orm.call("ads.recommendation", "action_dismiss", [[id]]);
            this.notification.add("Öneri yok sayıldı.", { type: "info" });
            await this.loadData();
        } catch (e) {
            this.notification.add(`İşlem başarısız: ${e.message}`, { type: "danger" });
        }
    }

    formatCurrency(amount) {
        if (amount === undefined || amount === null) return "0.00 " + this.state.currency_symbol;
        const locale = user.lang ? user.lang.replace('_', '-') : "tr-TR";
        return (
            Number(amount).toLocaleString(locale, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            }) +
            " " +
            this.state.currency_symbol
        );
    }

    formatNumber(num) {
        if (num === undefined || num === null) return "0";
        const locale = user.lang ? user.lang.replace('_', '-') : "tr-TR";
        return Number(num).toLocaleString(locale);
    }
}

AdsManagerDashboard.template = "ads_manager.Dashboard";

registry.category("actions").add("ads_manager_dashboard", AdsManagerDashboard);
