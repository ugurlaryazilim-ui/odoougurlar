/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

// Çıktı oranı: pazaryeri standardı 2:3 dikey (Trendyol 1200x1800)
const OUTPUT_ASPECT = 2 / 3;
// Uzun kenar üst sınırı: yükleme boyutunu makul tutar, AI için fazlasıyla yeterli
const MAX_LONG_EDGE = 3000;
// Bu çözünürlüğün altındaki çekimde kullanıcı uyarılır
const MIN_SHORT_EDGE = 1000;
const JPEG_QUALITY = 0.92;

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
        this.fileInputRef = useRef("fileInput");
        // Reaktif olmayan akış referansı: unmount sonrası gelen stream'i durdurabilmek için
        this.stream = null;
        this.unmounted = false;

        this.state = useState({
            activeTab: "front",    // front, back, side, detail
            cameraActive: false,
            cameraError: null,
            detailPlacement: "front",  // Detay hangi yüze ait: front veya back
            photos: {
                front: null,
                back: null,
                side: null,   // opsiyonel: yoksa yan görünüm ön fotoğraftan üretilir
                details: [],
            },
            hasFront: false,
            hasBack: false,
            hasSide: false,
            detailCount: 0,
            facingMode: "environment", // Arka kamera
            capturing: false,
            submitting: false,
            cropFrameStyle: "",
        });

        // Önizleme object-fit:cover ile kırpılır; kaydedilen alan kameranın ortasındaki
        // 2:3 bölgedir. Çerçeve, o bölgenin ekrandaki yerini gösterir.
        this.updateCropFrame = () => this._updateCropFrame();
        onMounted(() => {
            window.addEventListener("resize", this.updateCropFrame);
            this.startCamera();
        });
        onWillUnmount(() => {
            this.unmounted = true;
            window.removeEventListener("resize", this.updateCropFrame);
            this.stopCamera();
        });
    }

    async startCamera() {
        // Hızlı "kamera değiştir" dokunuşlarında yalnız EN SON başlatma geçerli
        const token = (this._camSeq = (this._camSeq || 0) + 1);
        this.state.cameraError = null;
        const attempts = [
            // En yüksek çözünürlük: tarayıcı desteklediği en yakın değeri seçer
            { video: { facingMode: { ideal: this.state.facingMode }, width: { ideal: 3840 }, height: { ideal: 2160 } }, audio: false },
            // iOS / eski cihaz fallback — basit kısıtlar
            { video: { facingMode: this.state.facingMode }, audio: false },
        ];
        let stream = null;
        let lastError = null;
        for (const constraints of attempts) {
            try {
                stream = await navigator.mediaDevices.getUserMedia(constraints);
                break;
            } catch (e) {
                lastError = e;
            }
        }
        if (!stream) {
            this.state.cameraError = _t("Kamera erişimi reddedildi veya kamera bulunamadı. İzin verip tekrar deneyin ya da dosyadan yükleyin.");
            console.error("Kamera hatası:", lastError);
            return;
        }
        // Ekrandan ayrıldıysa ya da bu arada yeni bir başlatma yapıldıysa ışık açık kalmasın
        if (this.unmounted || token !== this._camSeq) {
            stream.getTracks().forEach(track => track.stop());
            return;
        }
        this.stream = stream;
        this.state.cameraActive = true;
        if (this.videoRef.el) {
            this.videoRef.el.srcObject = stream;
            this.videoRef.el.onloadedmetadata = this.updateCropFrame;
        }
    }

    _updateCropFrame() {
        const video = this.videoRef.el;
        if (!video || !video.videoWidth) {
            this.state.cropFrameStyle = "";
            return;
        }
        const W = video.clientWidth, H = video.clientHeight;
        const vw = video.videoWidth, vh = video.videoHeight;
        const scale = Math.max(W / vw, H / vh);  // object-fit: cover
        const ox = (W - vw * scale) / 2, oy = (H - vh * scale) / 2;
        let cw = vw, ch = vh;
        if (vw / vh > OUTPUT_ASPECT) {
            cw = vh * OUTPUT_ASPECT;
        } else {
            ch = vw / OUTPUT_ASPECT;
        }
        const left = ox + ((vw - cw) / 2) * scale;
        const top = oy + ((vh - ch) / 2) * scale;
        this.state.cropFrameStyle =
            `left:${left}px;top:${top}px;width:${cw * scale}px;height:${ch * scale}px;`;
    }

    stopCamera() {
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
        this.state.cameraActive = false;
    }

    async toggleCamera() {
        this.stopCamera();
        this.state.facingMode = this.state.facingMode === "environment" ? "user" : "environment";
        await this.startCamera();
    }

    /**
     * Kaynağı (video karesi / bitmap / img) ortadan 2:3 kırpar, uzun kenarı
     * MAX_LONG_EDGE ile sınırlar ve JPEG dataURL döndürür.
     */
    _cropToOutput(source, srcWidth, srcHeight) {
        let cropW = srcWidth;
        let cropH = srcHeight;
        if (srcWidth / srcHeight > OUTPUT_ASPECT) {
            cropW = Math.round(srcHeight * OUTPUT_ASPECT);
        } else {
            cropH = Math.round(srcWidth / OUTPUT_ASPECT);
        }
        const sx = Math.round((srcWidth - cropW) / 2);
        const sy = Math.round((srcHeight - cropH) / 2);
        const scale = Math.min(1, MAX_LONG_EDGE / Math.max(cropW, cropH));
        const outW = Math.round(cropW * scale);
        const outH = Math.round(cropH * scale);

        const canvas = this.canvasRef.el || document.createElement("canvas");
        canvas.width = outW;
        canvas.height = outH;
        const ctx = canvas.getContext("2d");
        ctx.imageSmoothingQuality = "high";
        ctx.drawImage(source, sx, sy, cropW, cropH, 0, 0, outW, outH);
        return { dataUrl: canvas.toDataURL("image/jpeg", JPEG_QUALITY), width: outW, height: outH };
    }

    /** Mümkünse tam sensör çözünürlüğünde fotoğraf, değilse video karesi. */
    async _grabFrame() {
        const track = this.stream && this.stream.getVideoTracks()[0];
        if (track && typeof window.ImageCapture === "function") {
            try {
                const blob = await new window.ImageCapture(track).takePhoto();
                const bitmap = await createImageBitmap(blob);
                try {
                    return this._cropToOutput(bitmap, bitmap.width, bitmap.height);
                } finally {
                    bitmap.close && bitmap.close();
                }
            } catch (e) {
                console.warn("ImageCapture.takePhoto başarısız, video karesi kullanılıyor:", e);
            }
        }
        const video = this.videoRef.el;
        return this._cropToOutput(video, video.videoWidth, video.videoHeight);
    }

    async capturePhoto() {
        if (!this.videoRef.el || this.state.capturing) return;
        this.state.capturing = true;
        try {
            const shot = await this._grabFrame();
            this._storePhoto(shot);
        } catch (e) {
            console.error("Çekim hatası:", e);
            this.notification.add(_t("Fotoğraf çekilemedi, tekrar deneyin."), { type: "danger" });
        } finally {
            this.state.capturing = false;
        }
    }

    openFilePicker() {
        this.fileInputRef.el && this.fileInputRef.el.click();
    }

    /** DSLR / galeri fotoğrafı: aynı 2:3 kırpma ve boyut kuralları uygulanır. */
    async onFileSelected(ev) {
        const file = ev.target.files && ev.target.files[0];
        ev.target.value = "";  // aynı dosya tekrar seçilebilsin
        if (!file) return;
        if (!file.type.startsWith("image/")) {
            this.notification.add(_t("Lütfen bir görsel dosyası seçin."), { type: "danger" });
            return;
        }
        this.state.capturing = true;
        try {
            const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
            try {
                this._storePhoto(this._cropToOutput(bitmap, bitmap.width, bitmap.height));
            } finally {
                bitmap.close && bitmap.close();
            }
        } catch (e) {
            console.error("Dosya okuma hatası:", e);
            this.notification.add(_t("Görsel okunamadı."), { type: "danger" });
        } finally {
            this.state.capturing = false;
        }
    }

    _storePhoto({ dataUrl, width, height }) {
        const base64Data = dataUrl.split(",")[1];
        if (Math.min(width, height) < MIN_SHORT_EDGE) {
            this.notification.add(
                _t("Düşük çözünürlük (%(w)sx%(h)s). AI kalitesi düşebilir; mümkünse arka kamerayla veya dosyadan yükleyin.",
                   { w: width, h: height }),
                { type: "warning" }
            );
        }
        // Önizleme için aynı dataURL; ayrı kopya tutulmaz
        const photo = { data: base64Data, preview: dataUrl };

        const tab = this.state.activeTab;
        if (tab === "front") {
            this.state.photos.front = photo;
            this.state.hasFront = true;
        } else if (tab === "back") {
            this.state.photos.back = photo;
            this.state.hasBack = true;
        } else if (tab === "side") {
            this.state.photos.side = photo;
            this.state.hasSide = true;
        } else if (tab === "detail") {
            const placement = this.state.detailPlacement || "front";
            const existingIdx = this.state.photos.details.findIndex(d => d.placement === placement);
            const detailObj = { ...photo, placement };
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
        } else if (tab === "side") {
            this.state.photos.side = null;
            this.state.hasSide = false;
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
        if (tab === "side") return this.state.photos.side;
        if (tab === "detail") {
            const placement = this.state.detailPlacement || "front";
            return this.state.photos.details.find(d => d.placement === placement) || null;
        }
        return null;
    }

    async proceed() {
        if (this.state.submitting) return;
        if (!this.state.hasFront && !this.state.hasBack) {
            this.notification.add(_t("Lütfen ürünün önünü ve arkasını çekiniz!"), { type: "danger", sticky: false });
            return;
        }
        if (!this.state.hasFront) {
            this.notification.add(_t("Lütfen ürünün önünü çekiniz!"), { type: "danger", sticky: false });
            return;
        }
        if (!this.state.hasBack) {
            this.notification.add(_t("Lütfen ürünün arkasını çekiniz!"), { type: "danger", sticky: false });
            return;
        }

        const photos = [
            { type: "front", data: this.state.photos.front.data },
            { type: "back", data: this.state.photos.back.data },
        ];
        if (this.state.photos.side) {
            photos.push({ type: "side", data: this.state.photos.side.data });
        }
        for (const detail of this.state.photos.details) {
            photos.push({
                type: "detail",
                data: detail.data,
                detail_placement: detail.placement || "front",
            });
        }

        this.state.submitting = true;
        this.stopCamera();
        let ok = false;
        try {
            ok = await this.props.onPhotosReady(photos);
        } finally {
            if (!this.unmounted) {
                this.state.submitting = false;
                // Oturum oluşturma / yükleme başarısızsa çekimler korunur, kamera geri açılır
                if (!ok) {
                    await this.startCamera();
                }
            }
        }
    }
}
