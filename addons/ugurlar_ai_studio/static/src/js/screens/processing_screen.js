/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
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
        this.rpc = useService("rpc");
        this.state = useState({
            generations: [],
            allDone: false,
            pollInterval: null,
        });

        onMounted(() => this.startPolling());
        onWillUnmount(() => this.stopPolling());
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
            const res = await this.rpc("/ai_studio/generation_status/" + this.props.sessionId, {});
            this.state.generations = res.generations || [];

            const allDone = this.state.generations.every(
                g => g.state === "done" || g.state === "failed"
            );
            if (allDone && this.state.generations.length > 0) {
                this.state.allDone = true;
                this.stopPolling();
            }
        } catch (e) {
            console.error("Durum sorgulama hatası:", e);
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
            pending: _t("Sırada"),
            processing: _t("İşleniyor..."),
            done: _t("Tamamlandı"),
            failed: _t("Başarısız"),
        };
        return labels[state] || state;
    }

    getTypeLabel(type) {
        const labels = {
            front: _t("Ön Yüz"),
            back: _t("Arka Yüz"),
            detail: _t("Detay"),
        };
        return labels[type] || type;
    }

    goToReview() {
        this.props.onProcessingComplete();
    }
}
