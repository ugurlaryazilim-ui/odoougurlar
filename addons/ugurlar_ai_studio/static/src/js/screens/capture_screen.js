/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";

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
            setPieces: [],
            showSetBarcodeInput: false,
            setBarcodeQuery: '',
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

    toggleSetBarcodeInput() {
        this.state.showSetBarcodeInput = !this.state.showSetBarcodeInput;
        this.state.setBarcodeQuery = '';
        if (this.state.showSetBarcodeInput) {
            // Otomatik olarak kamera barkod okuyucuyu (veya gizli input yakalayıcıyı) başlat
            openCameraScanner(async (barcode) => {
                this.state.setBarcodeQuery = barcode;
                await this.addSetPiece();
            });
        }
    }

    onBarcodeKeyDown(ev) {
        if (ev.key === 'Enter') {
            this.addSetPiece();
        }
    }

    async addSetPiece() {
        const query = this.state.setBarcodeQuery.trim();
        if (!query) return;
        
        try {
            const res = await this.env.services.rpc('/ai_studio/find_product', {
                query: query,
            });
            if (res.found && res.products && res.products.length > 0) {
                const product = res.products[0];
                this.state.setPieces.push({
                    product_id: product.id,
                    product_name: product.name,
                    barcode: product.barcode,
                    photos: { front: null, back: null },
                    hasFront: false,
                    hasBack: false,
                });
                this.state.showSetBarcodeInput = false;
                this.state.setBarcodeQuery = '';
                this.state.activeTab = `set_${this.state.setPieces.length - 1}_front`;
            } else {
                this.env.services.notification.add('Ürün bulunamadı!', { type: 'danger' });
            }
        } catch (e) {
            this.env.services.notification.add('Arama hatası: ' + e.message, { type: 'danger' });
        }
    }

    removeSetPiece(index) {
        this.state.setPieces.splice(index, 1);
        this.state.activeTab = 'front';
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
            this.state.photos.details.push({
                data: base64Data,
                preview: dataUrl,
                placement: this.state.detailPlacement,
            });
            this.state.detailCount = this.state.photos.details.length;
        } else {
            const setMatch = tab.match(/^set_(\d+)_(front|back)$/);
            if (setMatch) {
                const idx = parseInt(setMatch[1]);
                const side = setMatch[2];
                if (this.state.setPieces[idx]) {
                    this.state.setPieces[idx].photos[side] = { data: base64Data, preview: dataUrl };
                    if (side === 'front') this.state.setPieces[idx].hasFront = true;
                    if (side === 'back') this.state.setPieces[idx].hasBack = true;
                }
            }
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
        } else {
            const setMatch = tab.match(/^set_(\d+)_(front|back)$/);
            if (setMatch) {
                const idx = parseInt(setMatch[1]);
                const side = setMatch[2];
                if (this.state.setPieces[idx]) {
                    this.state.setPieces[idx].photos[side] = null;
                    if (side === 'front') this.state.setPieces[idx].hasFront = false;
                    if (side === 'back') this.state.setPieces[idx].hasBack = false;
                }
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

    get currentPhoto() {
        const tab = this.state.activeTab;
        if (tab === "front") return this.state.photos.front;
        if (tab === "back") return this.state.photos.back;
        const setMatch = tab.match(/^set_(\d+)_(front|back)$/);
        if (setMatch) {
            const idx = parseInt(setMatch[1]);
            const side = setMatch[2];
            if (this.state.setPieces[idx]) {
                return this.state.setPieces[idx].photos[side];
            }
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

        for (let i = 0; i < this.state.setPieces.length; i++) {
            if (!this.state.setPieces[i].hasFront) {
                this.env.services.notification.add(`Lütfen ${this.state.setPieces[i].product_name} için Ön Yüzü Çekiniz!`, { type: "danger", sticky: false });
                return;
            }
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

        const setLines = this.state.setPieces.map((piece, idx) => ({
            product_id: piece.product_id,
            product_name: piece.product_name,
            barcode: piece.barcode,
            photos: [
                piece.photos.front ? { type: 'front', data: piece.photos.front.data } : null,
                piece.photos.back ? { type: 'back', data: piece.photos.back.data } : null,
            ].filter(Boolean),
        }));

        this.stopCamera();
        this.props.onPhotosReady(photos, setLines);
    }
}
