/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { aisRpc } from "../rpc_utils";

const POLL_MS = 5000;
// Bu süreden sonra ekran beklemeyi bırakır (iş arka planda sürer, cron devralır)
const MAX_POLL_MS = 20 * 60 * 1000;

export class ProcessingScreen extends Component {
    static template = "ugurlar_ai_studio.ProcessingScreen";
    static props = {
        sessionId: { type: Number },
        sessionName: { type: String },
        userRole: { type: String, optional: true },
        onProcessingComplete: { type: Function },
        onBackToScan: { type: Function },
    };

    setup() {
        this.state = useState({
            generations: [],
            allDone: false,
            timedOut: false,
        });
        // Zamanlayıcı reaktif state'te tutulmaz
        this.pollInterval = null;
        this.polling = false;
        this.pollStartedAt = 0;

        // Anlık güncelleme: sunucu oturum durumu değişince bus olayı gönderir;
        // polling yalnızca yedek olarak kalır
        this.busService = useService("bus_service");
        this.onBusUpdate = (payload) => {
            if (payload && payload.session_id === this.props.sessionId) {
                this.checkStatus(true);
            }
        };

        onMounted(() => {
            this.busService.subscribe("ai_studio.session_update", this.onBusUpdate);
            this.startPolling();
        });
        onWillUnmount(() => {
            this.busService.unsubscribe("ai_studio.session_update", this.onBusUpdate);
            this.stopPolling();
        });
    }

    async _jsonRpc(url, params = {}) {
        return aisRpc(url, params);
    }

    startPolling() {
        this.pollStartedAt = Date.now();
        this.checkStatus();
        this.pollInterval = setInterval(() => this.checkStatus(), POLL_MS);
    }

    stopPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
    }

    async checkStatus(force = false) {
        // Önceki istek bitmediyse üst üste binme; sekme gizliyken sunucuyu yorma
        if (this.polling || (document.hidden && !force)) return;
        if (!force && Date.now() - this.pollStartedAt > MAX_POLL_MS) {
            this.state.timedOut = true;
            this.stopPolling();
            return;
        }
        this.polling = true;
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
        } finally {
            this.polling = false;
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
            side: _t("Yan"),
            detail: _t("Detay"),
        };
        return labels[type] || type;
    }

    goToReview() {
        this.props.onProcessingComplete();
    }
}
