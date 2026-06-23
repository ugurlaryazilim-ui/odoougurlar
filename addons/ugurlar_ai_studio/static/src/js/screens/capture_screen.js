/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

export class CaptureScreen extends Component {
    static template = "ugurlar_ai_studio.CaptureScreen";
    static props = {
        productInfo: { type: Object },
        onPhotosReady: { type: Function },
        onBackToScan: { type: Function },
    };

    setup() {
        this.videoRef = useRef("cameraVideo");
        this.canvasRef = useRef("captureCanvas");

        this.state = useState({
            activeTab: "front",    // front, back, detail
            cameraActive: false,
            cameraError: null,
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
                    facingMode: this.state.facingMode,
                    width: { ideal: 1920 },
                    height: { ideal: 1440 },
                },
            };
            const stream = await navigator.mediaDevices.getUserMedia(constraints);
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

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;

        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0);

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
            this.state.photos.details.push({ data: base64Data, preview: dataUrl });
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
        }
    }

    removeDetail(index) {
        this.state.photos.details.splice(index, 1);
        this.state.detailCount = this.state.photos.details.length;
    }

    setTab(tab) {
        this.state.activeTab = tab;
    }

    get canProceed() {
        return this.state.hasFront; // En az ön fotoğraf gerekli
    }

    get currentPhoto() {
        const tab = this.state.activeTab;
        if (tab === "front") return this.state.photos.front;
        if (tab === "back") return this.state.photos.back;
        return null;
    }

    proceed() {
        if (!this.canProceed) return;

        const photos = [];
        if (this.state.photos.front) {
            photos.push({ type: "front", data: this.state.photos.front.data });
        }
        if (this.state.photos.back) {
            photos.push({ type: "back", data: this.state.photos.back.data });
        }
        for (const detail of this.state.photos.details) {
            photos.push({ type: "detail", data: detail.data });
        }

        this.stopCamera();
        this.props.onPhotosReady(photos);
    }
}
