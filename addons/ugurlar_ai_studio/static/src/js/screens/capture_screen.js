/** @odoo-module **/

import { Component, useState, useRef, onMounted, onPatched, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

// Çıktı oranı: pazaryeri standardı 2:3 dikey (Trendyol 1200x1800)
const OUTPUT_ASPECT = 2 / 3;
// Uzun kenar üst sınırı: yükleme boyutunu makul tutar, AI için fazlasıyla yeterli
const MAX_LONG_EDGE = 3000;
// iOS Safari'de ImageCapture yok; kayıt video karesinden alınır
const IS_IOS = /iP(hone|ad|od)/.test(navigator.userAgent)
    || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
// Bu çözünürlüğün altındaki çekimde kullanıcı uyarılır (iOS 1080p karesinin 2:3 kırpımı 720 px)
const MIN_SHORT_EDGE = IS_IOS ? 700 : 1000;
const JPEG_QUALITY = 0.92;
// AI ön işleme görseli bu uzun kenara indirir: video karesi bunu karşılıyorsa sensör
// fotoğrafına gerek yok ve kaydedilen alan önizlemedeki çerçeveyle birebir aynı olur
const AI_LONG_EDGE = 1600;
// Önizleme bu sürede kare üretmezse bir alt çözünürlük kademesiyle yeniden açılır
const PREVIEW_WATCHDOG_MS = 3500;
// "video": <video> doğrudan gösterilir. "canvas": kareler görünür bir canvas'a çizilir.
// iOS 27 + iPhone 16 Pro'da <video> önizlemesi siyah kalırken kareler okunabiliyor
// (çekim çalışıyor); canvas'a kendimiz çizince görüntü gelir. Teşhis panelinden değiştirilebilir.
const PREVIEW_MODE_KEY = "ais_camera_preview_mode";

function loadPreviewMode() {
    try {
        const saved = window.localStorage.getItem(PREVIEW_MODE_KEY);
        if (saved === "video" || saved === "canvas") {
            return saved;
        }
    } catch {
        // gizli sekme vb.: varsayılan kullanılır
    }
    return IS_IOS ? "canvas" : "video";
}

/** Denenecek çözünürlük kademeleri. iOS'ta 4K istemek siyah önizlemeye yol açabiliyor. */
function cameraAttempts(facingMode) {
    const simple = { video: { facingMode }, audio: false };
    if (IS_IOS) {
        return [
            { video: { facingMode: { ideal: facingMode }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false },
            { video: { facingMode: { ideal: facingMode }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false },
            simple,
        ];
    }
    return [
        // En yüksek çözünürlük: tarayıcı desteklediği en yakın değeri seçer
        { video: { facingMode: { ideal: facingMode }, width: { ideal: 3840 }, height: { ideal: 2160 } }, audio: false },
        simple,
    ];
}

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
        this.previewCanvasRef = useRef("previewCanvas");
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
            // Akış var ama video oynamıyor (iOS otomatik oynatmayı engelledi): dokunarak başlatılır
            previewBlocked: false,
            previewLive: false,
            previewMode: loadPreviewMode(),
            diagOpen: false,
            diagText: "",
        });
        this.resLevel = 0;
        this.framesDrawn = 0;
        this.lastError = "";

        // Önizleme object-fit:cover ile kırpılır; kaydedilen alan kameranın ortasındaki
        // 2:3 bölgedir. Çerçeve, o bölgenin ekrandaki yerini gösterir.
        this.updateCropFrame = () => this._updateCropFrame();
        // iOS arka plana alınınca kamera akışını durdurur; dönüşte görüntüyü geri getir
        this.onVisibilityChange = () => {
            if (document.visibilityState !== "visible") {
                this._stopPreviewLoop();
                return;
            }
            if (this.unmounted || this.state.submitting) {
                return;
            }
            const track = this.stream && this.stream.getVideoTracks()[0];
            if (!track || track.readyState === "ended") {
                this.startCamera();
            } else {
                this._playPreview();
            }
        };
        onMounted(() => {
            window.addEventListener("resize", this.updateCropFrame);
            document.addEventListener("visibilitychange", this.onVisibilityChange);
            this.startCamera();
        });
        // Hata ekranından dönüşte <video> yeniden oluşur: akışı yeni elemana bağla
        onPatched(() => {
            const video = this.videoRef.el;
            if (this.stream && video && video.srcObject !== this.stream) {
                this._attachStream();
            }
        });
        onWillUnmount(() => {
            this.unmounted = true;
            window.removeEventListener("resize", this.updateCropFrame);
            document.removeEventListener("visibilitychange", this.onVisibilityChange);
            clearInterval(this._diagTimer);
            this.stopCamera();
        });
    }

    /** @param {number} [level] çözünürlük kademesi (şablondaki "Tekrar Dene" olay nesnesi geçirir) */
    async startCamera(level) {
        // Hızlı "kamera değiştir" dokunuşlarında yalnız EN SON başlatma geçerli
        const token = (this._camSeq = (this._camSeq || 0) + 1);
        this.state.cameraError = null;
        const attempts = cameraAttempts(this.state.facingMode);
        let index = typeof level === "number" ? Math.min(level, attempts.length - 1) : 0;
        let stream = null;
        let lastError = null;
        for (; index < attempts.length; index++) {
            try {
                stream = await navigator.mediaDevices.getUserMedia(attempts[index]);
                break;
            } catch (e) {
                lastError = e;
                this.lastError = `getUserMedia[${index}]: ${e && e.name} ${e && e.message}`;
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
        this.resLevel = index;
        this.framesDrawn = 0;
        this.state.cameraActive = true;
        await this._attachStream();
        this._armWatchdog(token, attempts.length);
    }

    /** Önizleme kare üretmiyorsa bir alt kademeyle yeniden açar (iOS 4K/sanal lens siyahı). */
    _armWatchdog(token, attemptCount) {
        clearTimeout(this._watchdog);
        this._watchdog = setTimeout(() => {
            if (this.unmounted || token !== this._camSeq || !this.stream || this.state.previewBlocked
                || document.visibilityState !== "visible") {
                return;
            }
            const video = this.videoRef.el;
            const alive = video && video.videoWidth > 0 && video.readyState >= 2 && video.currentTime > 0;
            if (alive || this.resLevel + 1 >= attemptCount) {
                if (!alive) {
                    this.lastError = this.lastError || "Önizleme karesi gelmedi (tüm kademeler denendi)";
                }
                return;
            }
            this.lastError = `Kademe ${this.resLevel} kare üretmedi, alt çözünürlük deneniyor`;
            const next = this.resLevel + 1;
            this.stopCamera();
            this.startCamera(next);
        }, PREVIEW_WATCHDOG_MS);
    }

    /**
     * Akışı <video>'ya bağlar ve oynatır. iOS (özellikle 27+) yalnız muted + playsinline
     * videoyu otomatik oynatır; play() açıkça çağrılmazsa önizleme siyah kalır ama çekim
     * yine çalıştığından kullanıcı görmeden çekmiş olur.
     */
    async _attachStream() {
        const video = this.videoRef.el;
        if (!video || !this.stream) {
            return;
        }
        video.muted = true;
        video.defaultMuted = true;
        video.setAttribute("muted", "");
        video.setAttribute("playsinline", "");
        video.setAttribute("webkit-playsinline", "");
        video.onloadedmetadata = this.updateCropFrame;
        video.onplaying = () => {
            this.state.previewLive = true;
            this.state.previewBlocked = false;
            this.updateCropFrame();
            this._startPreviewLoop();
        };
        video.onpause = () => {
            this.state.previewLive = false;
        };
        if (video.srcObject !== this.stream) {
            video.srcObject = this.stream;
        }
        await this._playPreview();
    }

    async _playPreview() {
        const video = this.videoRef.el;
        if (!video || !this.stream) {
            return;
        }
        try {
            await video.play();
            this.state.previewBlocked = false;
            this._startPreviewLoop();
        } catch (e) {
            // NotAllowedError: kullanıcı dokunuşu gerekir. AbortError: yeni srcObject geldi, yok say
            if (e && e.name !== "AbortError") {
                console.warn("Kamera önizlemesi başlatılamadı:", e);
                this.lastError = `play(): ${e.name} ${e.message}`;
                this.state.previewBlocked = true;
            }
        }
    }

    // ---- Canvas önizleme -------------------------------------------------

    _startPreviewLoop() {
        this._stopPreviewLoop();
        if (this.state.previewMode !== "canvas" || this.unmounted || !this.stream) {
            return;
        }
        const step = () => {
            this._previewRaf = null;
            if (this.unmounted || !this.stream || this.state.previewMode !== "canvas") {
                return;
            }
            this._drawPreview();
            this._previewRaf = requestAnimationFrame(step);
        };
        this._previewRaf = requestAnimationFrame(step);
    }

    _stopPreviewLoop() {
        if (this._previewRaf) {
            cancelAnimationFrame(this._previewRaf);
            this._previewRaf = null;
        }
    }

    /** Video karesini önizleme canvas'ına object-fit:cover ile çizer (ekran çözünürlüğünde). */
    _drawPreview() {
        const video = this.videoRef.el;
        const canvas = this.previewCanvasRef.el;
        if (!video || !canvas || !video.videoWidth || video.readyState < 2) {
            return;
        }
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const W = Math.round(canvas.clientWidth * dpr);
        const H = Math.round(canvas.clientHeight * dpr);
        if (!W || !H) {
            return;
        }
        if (canvas.width !== W || canvas.height !== H) {
            canvas.width = W;
            canvas.height = H;
        }
        const vw = video.videoWidth, vh = video.videoHeight;
        const scale = Math.max(W / vw, H / vh);
        const sw = W / scale, sh = H / scale;
        try {
            canvas.getContext("2d").drawImage(video, (vw - sw) / 2, (vh - sh) / 2, sw, sh, 0, 0, W, H);
        } catch (e) {
            this.lastError = `drawImage: ${e.name} ${e.message}`;
            return;
        }
        this.framesDrawn++;
        if (!this.state.previewLive) {
            this.state.previewLive = true;
            this.updateCropFrame();
        }
    }

    togglePreviewMode() {
        this.state.previewMode = this.state.previewMode === "canvas" ? "video" : "canvas";
        try {
            window.localStorage.setItem(PREVIEW_MODE_KEY, this.state.previewMode);
        } catch {
            // kaydedilemezse yalnız bu oturum için geçerli
        }
        if (this.state.previewMode === "canvas") {
            this._startPreviewLoop();
        } else {
            this._stopPreviewLoop();
        }
        this._refreshDiag();
    }

    // ---- Teşhis paneli (başlığa 3 kez dokun) -----------------------------

    onTitleTap() {
        const now = Date.now();
        this._taps = (this._taps || []).filter(t => now - t < 1000);
        this._taps.push(now);
        if (this._taps.length >= 3) {
            this._taps = [];
            this.toggleDiag();
        }
    }

    toggleDiag() {
        this.state.diagOpen = !this.state.diagOpen;
        clearInterval(this._diagTimer);
        if (this.state.diagOpen) {
            this._refreshDiag();
            this._diagTimer = setInterval(() => this._refreshDiag(), 1000);
        }
    }

    _refreshDiag() {
        if (!this.state.diagOpen) {
            return;
        }
        const ua = navigator.userAgent;
        const osMatch = ua.match(/OS (\d+[_\d]*) like Mac OS X/);
        const track = this.stream && this.stream.getVideoTracks()[0];
        const st = track && track.getSettings ? track.getSettings() : {};
        const video = this.videoRef.el;
        const lines = [
            `Cihaz: ${IS_IOS ? "iOS " + (osMatch ? osMatch[1].replace(/_/g, ".") : "?") : navigator.platform}`,
            `Önizleme modu: ${this.state.previewMode} | kademe: ${this.resLevel} | çizilen kare: ${this.framesDrawn}`,
            track
                ? `Kamera: ${track.label || "-"} | ${st.width || "?"}x${st.height || "?"} @${st.frameRate ? Math.round(st.frameRate) : "?"}fps | ${track.readyState}${track.muted ? " (muted)" : ""}`
                : "Kamera: akış yok",
            video
                ? `Video: readyState=${video.readyState} paused=${video.paused} ${video.videoWidth}x${video.videoHeight} t=${video.currentTime.toFixed(1)}`
                : "Video: eleman yok",
            `Durum: active=${this.state.cameraActive} live=${this.state.previewLive} blocked=${this.state.previewBlocked}`,
            `Son hata: ${this.lastError || "-"}`,
        ];
        this.state.diagText = lines.join("\n");
    }

    /** "Önizlemeyi başlat" dokunuşu: kullanıcı hareketi içindeki play() iOS'ta izinlidir. */
    async resumePreview() {
        const track = this.stream && this.stream.getVideoTracks()[0];
        if (!track || track.readyState === "ended") {
            await this.startCamera();
            return;
        }
        await this._playPreview();
    }

    /** Önizleme gerçekten kare gösteriyor mu? Göstermiyorsa çekime izin verilmez. */
    get previewReady() {
        const video = this.videoRef.el;
        return !!(this.state.cameraActive && this.state.previewLive && video
            && !video.paused && video.readyState >= 2 && video.videoWidth);
    }

    /** Video karesinin 2:3 kırpımı yeterliyse kayıt oradan alınır (çerçeve = kayıt). */
    _useVideoFrame() {
        const video = this.videoRef.el;
        if (!video || !video.videoWidth) {
            return false;
        }
        if (typeof window.ImageCapture !== "function") {
            return true;
        }
        const vw = video.videoWidth, vh = video.videoHeight;
        const cropLong = vw / vh > OUTPUT_ASPECT ? vh : vw / OUTPUT_ASPECT;
        return cropLong >= AI_LONG_EDGE;
    }

    _updateCropFrame() {
        const video = this.videoRef.el;
        // Sensör fotoğrafı (ImageCapture) farklı en-boy/alanla çekilir; o durumda
        // yanıltıcı olmasın diye çerçeve gösterilmez
        if (!video || !video.videoWidth || !this._useVideoFrame()) {
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
        clearTimeout(this._watchdog);
        this._stopPreviewLoop();
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
        // iOS: eski akış elemanda kalırsa yeni getUserMedia önizlemesi siyah açılabilir
        if (this.videoRef.el) {
            this.videoRef.el.srcObject = null;
        }
        this.state.cameraActive = false;
        this.state.previewLive = false;
        this.state.previewBlocked = false;
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

    /** Video karesi yeterliyse o (çerçeveyle aynı alan), değilse tam sensör fotoğrafı. */
    async _grabFrame() {
        const track = this.stream && this.stream.getVideoTracks()[0];
        if (track && !this._useVideoFrame() && typeof window.ImageCapture === "function") {
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
        if (!this.previewReady) {
            // Önizleme engelliyse deklanşör dokunuşu (kullanıcı hareketi) onu başlatır
            if (this.state.previewBlocked) {
                await this.resumePreview();
                return;
            }
            this.notification.add(_t("Kamera görüntüsü henüz gelmedi; önizleme görünmeden çekim yapılmaz."),
                                  { type: "warning" });
            return;
        }
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
