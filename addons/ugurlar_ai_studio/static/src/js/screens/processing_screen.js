/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

export class ProcessingScreen extends Component {
    static template = "ugurlar_ai_studio.ProcessingScreen";
    static props = {
        sessionId: { type: Number },
        sessionName: { type: String },
        onProcessingComplete: { type: Function },
        onBackToScan: { type: Function },
    };

    setup() {
        this.state = useState({
            generations: [],
            allDone: false,
            pollInterval: null,
        });

        onMounted(() => this.startPolling());
        onWillUnmount(() => this.stopPolling());
    }

    async _jsonRpc(url, params = {}) {
        const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ jsonrpc: "2.0", method: "call", params }),
        });
        const data = await response.json();
        if (data.error) {
            throw new Error(data.error.data?.message || data.error.message || "RPC Error");
        }
        return data.result;
    }

    startPolling() {
        this.checkStatus();
        this.state.pollInterval = setInterval(() => this.checkStatus(), 5000);
    }

    stopPolling() {
        if (this.state.pollInterval) {
            clearInterval(this.state.pollInterval);
            this.state.pollInterval = null;
        }
    }

    async checkStatus() {
        try {
            const res = await this._jsonRpc("/ai_studio/generation_status/" + this.props.sessionId, {});
            this.state.generations = res.generations || [];

            const allDone = this.state.generations.every(
                g => g.state === "done" || g.state === "failed"
            );
            if (allDone && this.state.generations.length > 0) {
                this.state.allDone = true;
                this.stopPolling();
            }
        } catch (e) {
            console.error("Status check error:", e);
        }
    }

    getProgressPercent(gen) {
        switch (gen.state) {
            case "pending": return 0;
            case "processing": return 60;
            case "done": return 100;
            case "failed": return 100;
            default: return 0;
        }
    }

    getStateLabel(state) {
        const labels = {
            pending: _t("Sirada"),
            processing: _t("Isleniyor..."),
            done: _t("Tamamlandi"),
            failed: _t("Basarisiz"),
        };
        return labels[state] || state;
    }

    getTypeLabel(type) {
        const labels = {
            front: _t("On Yuz"),
            back: _t("Arka Yuz"),
            detail: _t("Detay"),
        };
        return labels[type] || type;
    }

    goToReview() {
        this.props.onProcessingComplete();
    }
}
