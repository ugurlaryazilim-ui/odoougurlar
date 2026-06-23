/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

import { ScanScreen } from "./screens/scan_screen";
import { CaptureScreen } from "./screens/capture_screen";
import { SettingsScreen } from "./screens/settings_screen";
import { ProcessingScreen } from "./screens/processing_screen";
import { ReviewScreen } from "./screens/review_screen";
import { BatchReview } from "./screens/batch_review";
import { HistoryScreen } from "./screens/history_screen";

/**
 * Ana AI Studio Client Action — Ekran yoneticisi.
 * Mobil-first SPA mimarisi.
 */
export class AiStudioAction extends Component {
    static template = "ugurlar_ai_studio.AiStudioAction";
    static components = {
        ScanScreen,
        CaptureScreen,
        SettingsScreen,
        ProcessingScreen,
        ReviewScreen,
        BatchReview,
        HistoryScreen,
    };
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.actionService = useService("action");

        this.state = useState({
            currentScreen: "scan",
            sessionId: null,
            sessionName: "",
            productId: null,
            productInfo: null,
            photos: [],
            generations: [],
            presets: [],
            rejectReasons: [],
            promptTemplates: [],
            dashboardStats: {},
        });

        onWillStart(async () => {
            await this.loadInitialData();
        });
    }

    async _jsonRpc(url, params = {}) {
        const response = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                jsonrpc: "2.0",
                method: "call",
                params: params,
            }),
        });
        const data = await response.json();
        if (data.error) {
            throw new Error(data.error.data?.message || data.error.message || "RPC Error");
        }
        return data.result;
    }

    async loadInitialData() {
        try {
            const [presetsRes, reasonsRes, templatesRes, statsRes] = await Promise.all([
                this._jsonRpc("/ai_studio/get_presets", {}),
                this._jsonRpc("/ai_studio/get_reject_reasons", {}),
                this._jsonRpc("/ai_studio/get_prompt_templates", {}),
                this._jsonRpc("/ai_studio/dashboard_stats", {}),
            ]);
            this.state.presets = presetsRes.presets || [];
            this.state.rejectReasons = reasonsRes.reasons || [];
            this.state.promptTemplates = templatesRes.templates || [];
            this.state.dashboardStats = statsRes || {};
        } catch (e) {
            console.error("AI Studio initial data load failed:", e);
        }
    }

    // --- Ekran Navigasyonu ---

    navigateTo(screen, data = {}) {
        Object.assign(this.state, data);
        this.state.currentScreen = screen;
    }

    onProductFound(productInfo) {
        this.state.productInfo = productInfo;
        this.state.productId = productInfo.id;
        this.navigateTo("capture");
    }

    async onPhotosReady(photos) {
        this.state.photos = photos;
        try {
            const res = await this._jsonRpc("/ai_studio/create_session", {
                product_id: this.state.productId,
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
                console.error("Session create error:", res.error);
                return;
            }
            if (res.success) {
                this.state.sessionId = res.session_id;
                this.state.sessionName = res.session_name;

                for (const photo of photos) {
                    try {
                        await this._jsonRpc("/ai_studio/upload_photo", {
                            session_id: res.session_id,
                            photo_type: photo.type,
                            image_data: photo.data,
                        });
                    } catch (uploadErr) {
                        console.error("Photo upload error:", uploadErr);
                    }
                }
                this.navigateTo("settings");
            }
        } catch (e) {
            this.notification.add(e.message || _t("Oturum olusturulamadi."), { type: "danger" });
            console.error("Session creation exception:", e);
        }
    }

    async onStartProcessing(settings) {
        try {
            await this.orm.write("ai.studio.session", [this.state.sessionId], {
                model_preset_id: settings.presetId,
                category: settings.category,
                quality_mode: settings.qualityMode,
                extra_prompt: settings.extraPrompt || "",
                prompt_template_id: settings.promptTemplateId || false,
            });
            await this.orm.call("ai.studio.session", "action_start_processing", [this.state.sessionId]);
            this.navigateTo("processing");
        } catch (e) {
            this.notification.add(e.message || _t("Islem baslatilamadi."), { type: "danger" });
        }
    }

    async onProcessingComplete() {
        const res = await this._jsonRpc("/ai_studio/generation_status/" + this.state.sessionId, {});
        this.state.generations = res.generations || [];
        this.navigateTo("review");
    }

    async onApproveGeneration(genId, isPrimary) {
        const res = await this._jsonRpc("/ai_studio/approve_generation", {
            generation_id: genId,
            is_primary: isPrimary,
        });
        if (res.success) {
            this.notification.add(_t("Gorsel onaylandi."), { type: "success" });
            await this.refreshGenerations();
        }
    }

    async onRejectGeneration(genId, reasonId, prompt) {
        const res = await this._jsonRpc("/ai_studio/reject_generation", {
            generation_id: genId,
            reason_id: reasonId,
            revision_prompt: prompt,
        });
        if (res.success) {
            this.notification.add(_t("Revizyon gonderildi."), { type: "warning" });
            this.navigateTo("processing");
        } else if (res.needs_supervisor) {
            this.notification.add(res.error, { type: "danger" });
        }
    }

    async onCompleteSession() {
        const res = await this._jsonRpc("/ai_studio/complete_session", {
            session_id: this.state.sessionId,
        });
        if (res.success) {
            this.notification.add(_t("Gorseller urune kaydedildi!"), { type: "success", sticky: true });
            this.resetSession();
            this.navigateTo("scan");
        } else {
            this.notification.add(res.error || _t("Hata olustu."), { type: "danger" });
        }
    }

    async refreshGenerations() {
        const res = await this._jsonRpc("/ai_studio/generation_status/" + this.state.sessionId, {});
        this.state.generations = res.generations || [];
    }

    resetSession() {
        this.state.sessionId = null;
        this.state.sessionName = "";
        this.state.productId = null;
        this.state.productInfo = null;
        this.state.photos = [];
        this.state.generations = [];
    }

    onBackToScan() {
        this.resetSession();
        this.navigateTo("scan");
    }

    onGoToHistory() {
        this.navigateTo("history");
    }

    onGoToBatchReview() {
        this.navigateTo("batch");
    }
}

registry.category("actions").add("ugurlar_ai_studio.main", AiStudioAction);
