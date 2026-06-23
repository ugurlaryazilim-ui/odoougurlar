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
 * Ana AI Stüdyo Client Action — Ekran yöneticisi.
 *
 * Mobil-first SPA mimarisi ile tüm ekranları yönetir.
 * Her ekran bağımsız bir OWL component'idir.
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
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.action = useService("action");

        this.state = useState({
            currentScreen: "scan", // scan, capture, settings, processing, review, batch, history
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

    async loadInitialData() {
        try {
            const [presetsRes, reasonsRes, templatesRes, statsRes] = await Promise.all([
                this.rpc("/ai_studio/get_presets", {}),
                this.rpc("/ai_studio/get_reject_reasons", {}),
                this.rpc("/ai_studio/get_prompt_templates", {}),
                this.rpc("/ai_studio/dashboard_stats", {}),
            ]);
            this.state.presets = presetsRes.presets || [];
            this.state.rejectReasons = reasonsRes.reasons || [];
            this.state.promptTemplates = templatesRes.templates || [];
            this.state.dashboardStats = statsRes || {};
        } catch (e) {
            console.error("AI Stüdyo başlangıç verisi yüklenemedi:", e);
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

        // Oturum oluştur
        try {
            const res = await this.rpc("/ai_studio/create_session", {
                product_id: this.state.productId,
            });
            if (res.success) {
                this.state.sessionId = res.session_id;
                this.state.sessionName = res.session_name;

                // Fotoğrafları yükle
                for (const photo of photos) {
                    await this.rpc("/ai_studio/upload_photo", {
                        session_id: res.session_id,
                        photo_type: photo.type,
                        image_data: photo.data,
                    });
                }
                this.navigateTo("settings");
            }
        } catch (e) {
            this.notification.add(_t("Oturum oluşturulamadı."), { type: "danger" });
            console.error(e);
        }
    }

    async onStartProcessing(settings) {
        try {
            // Oturum ayarlarını güncelle
            await this.orm.write("ai.studio.session", [this.state.sessionId], {
                model_preset_id: settings.presetId,
                category: settings.category,
                quality_mode: settings.qualityMode,
                extra_prompt: settings.extraPrompt || "",
                prompt_template_id: settings.promptTemplateId || false,
            });

            // AI işlemeyi başlat
            await this.orm.call("ai.studio.session", "action_start_processing", [this.state.sessionId]);

            this.navigateTo("processing");
        } catch (e) {
            this.notification.add(e.message || _t("İşlem başlatılamadı."), { type: "danger" });
        }
    }

    async onProcessingComplete() {
        // Generation durumlarını yükle
        const res = await this.rpc("/ai_studio/generation_status/" + this.state.sessionId, {});
        this.state.generations = res.generations || [];
        this.navigateTo("review");
    }

    async onApproveGeneration(genId, isPrimary) {
        const res = await this.rpc("/ai_studio/approve_generation", {
            generation_id: genId,
            is_primary: isPrimary,
        });
        if (res.success) {
            this.notification.add(_t("Görsel onaylandı."), { type: "success" });
            await this.refreshGenerations();
        }
    }

    async onRejectGeneration(genId, reasonId, prompt) {
        const res = await this.rpc("/ai_studio/reject_generation", {
            generation_id: genId,
            reason_id: reasonId,
            revision_prompt: prompt,
        });
        if (res.success) {
            this.notification.add(_t("Revizyon gönderildi."), { type: "warning" });
            this.navigateTo("processing");
        } else if (res.needs_supervisor) {
            this.notification.add(res.error, { type: "danger" });
        }
    }

    async onCompleteSession() {
        const res = await this.rpc("/ai_studio/complete_session", {
            session_id: this.state.sessionId,
        });
        if (res.success) {
            this.notification.add(_t("Görseller ürüne kaydedildi!"), { type: "success", sticky: true });
            this.resetSession();
            this.navigateTo("scan");
        } else {
            this.notification.add(res.error || _t("Hata oluştu."), { type: "danger" });
        }
    }

    async refreshGenerations() {
        const res = await this.rpc("/ai_studio/generation_status/" + this.state.sessionId, {});
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
