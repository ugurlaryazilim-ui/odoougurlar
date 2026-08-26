/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { markup } from "@odoo/owl";
import { ConfirmationDialog, AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

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
        this.dialog = useService("dialog");

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
            userRole: 'operator',  // operator, reviewer, manager
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
            this.state.userRole = statsRes.user_role || 'operator';
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
        if (productInfo.has_active_session) {
            const operatorStr = productInfo.active_session_operator ? ` (${productInfo.active_session_operator})` : '';
            const sessionStr = productInfo.active_session_name ? ` [${productInfo.active_session_name}]` : '';
            this.dialog.add(AlertDialog, {
                title: _t("Aktif Oturum Bulundu!"),
                body: `Bu ürün (${productInfo.name}) için halihazırda${operatorStr} tarafından açık bir oturum${sessionStr} (çekim, AI işleme veya onay süreci) bulunuyor.\n\nLütfen onayıcının veya ilgili operatörün işlemi bitirmesini bekleyin ve başka bir ürüne geçin.`,
                confirmLabel: _t("Tamam"),
                confirm: () => {},
            });
            return;
        }
        if (productInfo.has_image) {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Görsel Zaten Mevcut"),
                body: `Bu ürünün (${productInfo.name}) halihazırda bir ana görseli var!\n\nYine de yeni bir AI çekimi başlatmak istediğinize emin misiniz?`,
                confirm: () => {
                    this.state.productInfo = productInfo;
                    this.state.productId = productInfo.id;
                    this.state.productGender = productInfo.gender || '';
                    this.state.productBodyType = productInfo.body_type || 'standard';
                    this.navigateTo("capture");
                },
                cancel: () => {},
            });
            return;
        }
        this.state.productInfo = productInfo;
        this.state.productId = productInfo.id;
        this.state.productGender = productInfo.gender || '';
        this.state.productBodyType = productInfo.body_type || 'standard';
        this.navigateTo("capture");
    }

    async onPhotosReady(photos, setLines = []) {
        this.state.photos = photos;
        try {
            const res = await this._jsonRpc("/ai_studio/create_session", {
                product_id: this.state.productId,
                session_type: setLines.length > 0 ? 'set' : 'single',
                set_lines: setLines,
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger", sticky: false });
                console.error("Session create error:", res.error);
                return;
            }
            if (res.success) {
                this.state.sessionId = res.session_id;
                this.state.sessionName = res.session_name;

                for (const photo of photos) {
                    try {
                        const uploadParams = {
                            session_id: res.session_id,
                            photo_type: photo.type,
                            image_data: photo.data,
                        };
                        // Detay fotoğraflarında konum bilgisi gönder
                        if (photo.type === 'detail' && photo.detail_placement) {
                            uploadParams.detail_placement = photo.detail_placement;
                        }
                        await this._jsonRpc("/ai_studio/upload_photo", uploadParams);
                    } catch (uploadErr) {
                        console.error("Photo upload error:", uploadErr);
                    }
                }

                // Upload set piece photos
                if (setLines.length > 0 && res.set_line_map) {
                    for (const [idx, setLine] of setLines.entries()) {
                        const setLineId = res.set_line_map[idx];
                        if (setLineId && setLine.photos) {
                            for (const photo of setLine.photos) {
                                try {
                                    await this._jsonRpc("/ai_studio/upload_photo", {
                                        session_id: res.session_id,
                                        photo_type: photo.type,
                                        image_data: photo.data,
                                        set_line_id: setLineId,
                                    });
                                } catch (uploadErr) {
                                    console.error("Set piece photo upload error:", uploadErr);
                                }
                            }
                        }
                    }
                }

                // Presetleri ürün cinsiyetine ve vücut tipine göre filtreli yükle
                const gender = this.state.productGender || '';
                const bodyType = this.state.productBodyType || 'standard';
                const presetsRes = await this._jsonRpc("/ai_studio/get_presets", {
                    gender: gender || undefined,
                    body_type: bodyType,
                });
                this.state.presets = presetsRes.presets || [];

                this.navigateTo("settings");
            }
        } catch (e) {
            this.notification.add(e.message || _t("Oturum olusturulamadi."), { type: "danger", sticky: false });
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

            // Operatör: Processing ekranını hiç gösterme, direkt scan'e dön
            if (this.state.userRole === 'operator') {
                // Aynı ürünün diğer renk varyantlarını kontrol et
                const currentProductId = this.state.productId;
                await this._checkSiblingVariants(currentProductId);
                return;
            }

            this.navigateTo("processing");
        } catch (e) {
            this.notification.add(e.message || _t("Islem baslatilamadi."), { type: "danger", sticky: false });
        }
    }

    async _checkSiblingVariants(productId) {
        try {
            const res = await this._jsonRpc("/ai_studio/sibling_variants", {
                product_id: productId,
            });

            const variants = (res.variants || []).filter(v => !v.has_active_session);

            if (variants.length > 0) {
                // Varyant listesi HTML'i oluştur
                const variantLines = variants.map(v => {
                    const colorLabel = v.color || v.attributes;
                    return `<div style="padding:4px 0;">🎨 <strong>${colorLabel}</strong> <span style="color:#888;">(Stok: ${Math.floor(v.qty_available)})</span></div>`;
                }).join('');

                const bodyHtml = markup(
                    `<div style="margin-bottom:12px;">📸 AI işlemesi için gönderildi!</div>` +
                    `<div style="background:#fff8e1; border-left:4px solid #ffa000; padding:10px 14px; border-radius:6px; margin-bottom:10px;">` +
                    `<strong>⚠️ Bu ürünün görseli olmayan ${variants.length} renk varyantı daha var:</strong></div>` +
                    `<div style="padding:6px 0;">${variantLines}</div>`
                );

                // Dialog ile operatöre sor
                this.dialog.add(ConfirmationDialog, {
                    title: _t("📦 Diğer Renk Varyantları"),
                    body: bodyHtml,
                    confirmLabel: _t("🎨 İlk Varyantı Çek (" + (variants[0].color || variants[0].attributes) + ")"),
                    cancelLabel: _t("⏭️ Başka Ürüne Geç"),
                    confirm: () => {
                        // İlk görselsiz varyantı direkt çekime yönlendir
                        const nextVariant = variants[0];
                        this.resetSession();
                        this.state.productId = nextVariant.id;
                        this.state.productInfo = {
                            id: nextVariant.id,
                            name: nextVariant.name,
                            barcode: nextVariant.barcode,
                            default_code: nextVariant.default_code,
                        };
                        this.state.productGender = '';  // Aynı template, aynı cinsiyet
                        this.notification.add(
                            _t("🎨 " + (nextVariant.color || nextVariant.attributes) + " varyantı çekime hazır!"),
                            { type: "info", sticky: false }
                        );
                        this.navigateTo("capture");
                    },
                    cancel: () => {
                        this.resetSession();
                        this.navigateTo("scan");
                    },
                });
            } else {
                // Görselsiz varyant yok, direkt scan'e dön
                this.notification.add(
                    _t("📸 AI işlemesi için gönderildi. Onayıcı görselleri inceleyecek."),
                    { type: "success", sticky: false }
                );
                this.resetSession();
                this.navigateTo("scan");
            }
        } catch (e) {
            console.error("Sibling variants check error:", e);
            // Hata olsa bile scan'e dön
            this.notification.add(
                _t("📸 AI işlemesi için gönderildi. Onayıcı görselleri inceleyecek."),
                { type: "success", sticky: false }
            );
            this.resetSession();
            this.navigateTo("scan");
        }
    }

    async onProcessingComplete() {
        // Operatör review ekranına erişemez — direkt scan'e dön
        if (this.state.userRole === 'operator') {
            this.notification.add(_t("İşlem tamamlandı! Onayıcı görselleri inceleyecek."), { type: "success", sticky: false });
            this.resetSession();
            this.navigateTo("scan");
            return;
        }
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
            this.notification.add(_t("Gorsel onaylandi."), { type: "success", sticky: false });
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
            this.notification.add(_t("Revizyon gonderildi."), { type: "warning", sticky: false });
            this.navigateTo("processing");
        } else if (res.needs_supervisor) {
            this.notification.add(res.error, { type: "danger", sticky: false });
        }
    }

    async onCompleteSession() {
        const res = await this._jsonRpc("/ai_studio/complete_session", {
            session_id: this.state.sessionId,
        });
        if (res.success) {
            this.notification.add(_t("Gorseller urune kaydedildi!"), { type: "success", sticky: false });
            this.resetSession();
            this.navigateTo("scan");
        } else {
            this.notification.add(res.error || _t("Hata olustu."), { type: "danger", sticky: false });
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

// --- Global Lightbox Zoom Handler ---
document.addEventListener("click", (ev) => {
    const img = ev.target.closest(".ais-zoomable-img img");
    if (!img) return;

    // Edit modunda ise (dosya seçme/silme modunda) lightbox açma
    const form = img.closest(".o_form_view");
    if (form && form.classList.contains("o_form_editable")) {
        return;
    }

    ev.preventDefault();
    ev.stopPropagation();

    // Mevcut lightbox varsa kaldır
    const existing = document.getElementById("ais_lightbox");
    if (existing) existing.remove();

    const lightbox = document.createElement("div");
    lightbox.id = "ais_lightbox";
    lightbox.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        background: rgba(0, 0, 0, 0.85);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 999999;
        cursor: pointer;
        opacity: 0;
        transition: opacity 0.25s ease;
    `;

    const closeBtn = document.createElement("div");
    closeBtn.innerText = "✕";
    closeBtn.style.cssText = `
        position: absolute;
        top: 20px;
        right: 20px;
        color: #fff;
        font-size: 30px;
        font-weight: bold;
        cursor: pointer;
    `;
    lightbox.appendChild(closeBtn);

    const imgEl = document.createElement("img");
    imgEl.src = img.src;
    imgEl.style.cssText = `
        max-width: 90%;
        max-height: 90%;
        object-fit: contain;
        border-radius: 8px;
        box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
        transform: scale(0.95);
        transition: transform 0.25s ease;
    `;

    lightbox.appendChild(imgEl);
    document.body.appendChild(lightbox);

    // Fade in
    requestAnimationFrame(() => {
        lightbox.style.opacity = "1";
        imgEl.style.transform = "scale(1)";
    });

    // Kapatma tetikleyicileri
    const closeLightbox = () => {
        lightbox.style.opacity = "0";
        imgEl.style.transform = "scale(0.95)";
        setTimeout(() => lightbox.remove(), 250);
    };

    lightbox.addEventListener("click", closeLightbox);
});
