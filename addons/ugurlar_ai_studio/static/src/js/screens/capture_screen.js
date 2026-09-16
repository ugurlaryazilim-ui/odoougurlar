/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

export class CaptureScreen extends Component {
    static template = "ugurlar_ai_studio.CaptureScreen";
    static props = {
        productInfo: { type: Object },
        onPhotosReady: { type: Function },
        onBackToScan: { type: Function },
    };

    setup() {
        this.notification = useService("notification");
        this.videoRef = useRef("cameraVideo");
        this.canvasRef = useRef("captureCanvas");

        this.state = useState({
            activeTab: "front",    // front, back, detail
            cameraActive: false,
            cameraError: null,
            detailPlacement: "front",  // Detay hangi yüze ait: front veya back
            photos: {
                front: null,
                back: null,
                details: [],
            },
            hasFront: false,
            hasBack: false,
            detailCount: 0,
            stream: null,
            facingMode: "environment", // Arka kamera
        });

        onMounted(() => this.startCamera());
        onWillUnmount(() => this.stopCamera());
    }

    async startCamera() {
        try {
            const constraints = {
                video: {
                    facingMode: { ideal: this.state.facingMode },
                    width: { ideal: 1280 },
                    height: { ideal: 720 },
                },
            };
            let stream;
            try {
                stream = await navigator.mediaDevices.getUserMedia(constraints);
            } catch(e1) {
                // iOS fallback — simpler constraints
                stream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: 'environment' },
                    audio: false
                });
            }
            this.state.stream = stream;
            this.state.cameraActive = true;
            this.state.cameraError = null;

            if (this.videoRef.el) {
                this.videoRef.el.srcObject = stream;
            }
        } catch (e) {
            this.state.cameraError = _t("Kamera erişimi reddedildi. Lütfen izin verin.");
            console.error("Kamera hatası:", e);
        }
    }

    stopCamera() {
        if (this.state.stream) {
            this.state.stream.getTracks().forEach(track => track.stop());
            this.state.stream = null;
            this.state.cameraActive = false;
        }
    }

    async toggleCamera() {
        this.stopCamera();
        this.state.facingMode = this.state.facingMode === "environment" ? "user" : "environment";
        await this.startCamera();
    }

    capturePhoto() {
        if (!this.videoRef.el || !this.canvasRef.el) return;

        const video = this.videoRef.el;
        const canvas = this.canvasRef.el;

        const videoWidth = video.videoWidth;
        const videoHeight = video.videoHeight;
        const elementWidth = video.clientWidth || window.innerWidth;
        const elementHeight = video.clientHeight || window.innerHeight;

        const elementAspectRatio = elementWidth / elementHeight;
        const streamAspectRatio = videoWidth / videoHeight;

        let sourceX = 0;
        let sourceY = 0;
        let sourceWidth = videoWidth;
        let sourceHeight = videoHeight;

        if (streamAspectRatio > elementAspectRatio) {
            // Stream is wider than element (e.g. 4:3 video inside 9:16 screen)
            sourceWidth = videoHeight * elementAspectRatio;
            sourceX = (videoWidth - sourceWidth) / 2;
        } else if (streamAspectRatio < elementAspectRatio) {
            // Stream is taller than element
            sourceHeight = videoWidth / elementAspectRatio;
            sourceY = (videoHeight - sourceHeight) / 2;
        }

        canvas.width = sourceWidth;
        canvas.height = sourceHeight;

        const ctx = canvas.getContext("2d");
        ctx.drawImage(
            video,
            sourceX, sourceY, sourceWidth, sourceHeight,
            0, 0, sourceWidth, sourceHeight
        );

        // Base64 olarak al
        const dataUrl = canvas.toDataURL("image/jpeg", 0.92);
        const base64Data = dataUrl.split(",")[1];

        const tab = this.state.activeTab;
        if (tab === "front") {
            this.state.photos.front = { data: base64Data, preview: dataUrl };
            this.state.hasFront = true;
        } else if (tab === "back") {
            this.state.photos.back = { data: base64Data, preview: dataUrl };
            this.state.hasBack = true;
        } else if (tab === "detail") {
            const placement = this.state.detailPlacement || "front";
            const existingIdx = this.state.photos.details.findIndex(d => d.placement === placement);
            const detailObj = {
                data: base64Data,
                preview: dataUrl,
                placement: placement,
            };
            if (existingIdx !== -1) {
                // Mevcut detayı güncelle (Maksimum 1 adet sınırı)
                this.state.photos.details[existingIdx] = detailObj;
                this.notification.add(
                    placement === "front"
                        ? _t("Ön yüz detayı güncellendi (1/1).")
                        : _t("Arka yüz detayı güncellendi (1/1)."),
                    { type: "info", sticky: false }
                );
            } else {
                // Yeni detay ekle (bu konum için ilk ve tek)
                this.state.photos.details.push(detailObj);
                this.notification.add(
                    placement === "front"
                        ? _t("Ön yüz detayı kaydedildi (1/1).")
                        : _t("Arka yüz detayı kaydedildi (1/1)."),
                    { type: "success", sticky: false }
                );
            }
            this.state.detailCount = this.state.photos.details.length;
        }
    }

    retakePhoto() {
        const tab = this.state.activeTab;
        if (tab === "front") {
            this.state.photos.front = null;
            this.state.hasFront = false;
        } else if (tab === "back") {
            this.state.photos.back = null;
            this.state.hasBack = false;
        } else if (tab === "detail") {
            const placement = this.state.detailPlacement || "front";
            const idx = this.state.photos.details.findIndex(d => d.placement === placement);
            if (idx !== -1) {
                this.state.photos.details.splice(idx, 1);
                this.state.detailCount = this.state.photos.details.length;
            }
        }
    }

    removeDetail(index) {
        this.state.photos.details.splice(index, 1);
        this.state.detailCount = this.state.photos.details.length;
    }

    setTab(tab) {
        this.state.activeTab = tab;
    }

    setDetailPlacement(placement) {
        this.state.detailPlacement = placement;
    }

    get canProceed() {
        return true; // Düğme her zaman açık, uyarıları proceed içinde vereceğiz
    }

    get hasDetailFront() {
        return this.state.photos.details.some(d => d.placement === "front");
    }

    get hasDetailBack() {
        return this.state.photos.details.some(d => d.placement === "back");
    }

    get currentPhoto() {
        const tab = this.state.activeTab;
        if (tab === "front") return this.state.photos.front;
        if (tab === "back") return this.state.photos.back;
        if (tab === "detail") {
            const placement = this.state.detailPlacement || "front";
            return this.state.photos.details.find(d => d.placement === placement) || null;
        }
        return null;
    }

    proceed() {
        if (!this.state.hasFront && !this.state.hasBack) {
            this.env.services.notification.add("Lütfen Ürünün Önünü ve Arkasını Çekiniz!", { type: "danger", sticky: false });
            return;
        }
        if (!this.state.hasFront) {
            this.env.services.notification.add("Lütfen Ürünün Önünü Çekiniz!", { type: "danger", sticky: false });
            return;
        }
        if (!this.state.hasBack) {
            this.env.services.notification.add("Lütfen Ürünün Arkasını Çekiniz!", { type: "danger", sticky: false });
            return;
        }

        const photos = [];
        if (this.state.photos.front) {
            photos.push({ type: "front", data: this.state.photos.front.data });
        }
        if (this.state.photos.back) {
            photos.push({ type: "back", data: this.state.photos.back.data });
        }
        for (const detail of this.state.photos.details) {
            photos.push({
                type: "detail",
                data: detail.data,
                detail_placement: detail.placement || 'front',
            });
        }

        this.stopCamera();
        this.props.onPhotosReady(photos);
    }
}
