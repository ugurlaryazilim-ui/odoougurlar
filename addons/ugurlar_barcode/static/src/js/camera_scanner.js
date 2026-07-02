/** @odoo-module **/

/**
 * Merkezi Kamera Barkod Tarayıcı Modülü
 * 
 * Tüm ekranlarda kullanılan kamera barkod okutma fonksiyonelliğini
 * tek bir yerde toplar. iOS/Safari ve Android/Chrome uyumluluğunu sağlar.
 * 
 * iOS Sorunları ve Çözümleri:
 * - BarcodeDetector API iOS'ta YOK → html5-qrcode fallback
 * - facingMode: 'environment' ultra-wide kamerayı seçebilir → getCameras() ile ana kamera seçimi
 * - aspectRatio iOS'ta sorun çıkarır → kaldırıldı
 * - Yüksek FPS iOS'ta frame drop yapar → 8 FPS
 */

// ─── iOS Algılama ─────────────────────────────────────────
function isIOS() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

// ─── html5-qrcode CDN Yükleme ────────────────────────────
let _cdnLoaded = false;
async function ensureHtml5QrcodeLoaded() {
    if (window.Html5Qrcode || _cdnLoaded) return;
    await new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = 'https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js';
        s.onload = () => { _cdnLoaded = true; resolve(); };
        s.onerror = () => reject(new Error('Kütüphane yüklenemedi'));
        document.head.appendChild(s);
    });
}

// ─── iOS için En İyi Arka Kamerayı Seç ───────────────────
async function getBestBackCameraId() {
    try {
        const cameras = await Html5Qrcode.getCameras();
        if (!cameras || cameras.length === 0) return null;

        // 1. "Back Camera" (ana arka kamera) etiketini ara
        const mainBack = cameras.find(c =>
            c.label === 'Back Camera' ||
            /^back camera$/i.test(c.label)
        );
        if (mainBack) return mainBack.id;

        // 2. "back" içerip "ultra"/"wide"/"telephoto" İÇERMEYEN kamerayı bul
        const filteredBack = cameras.find(c =>
            /back/i.test(c.label) &&
            !/ultra|wide|telephoto|tele/i.test(c.label)
        );
        if (filteredBack) return filteredBack.id;

        // 3. "back" veya "rear" veya "environment" içeren herhangi bir kamera
        const anyBack = cameras.find(c =>
            /back|rear|environment|arka/i.test(c.label)
        );
        if (anyBack) return anyBack.id;

        // 4. Fallback: son kamera (genellikle arka kamera)
        return cameras[cameras.length - 1].id;
    } catch (e) {
        console.warn('Kamera listesi alınamadı:', e);
        return null;
    }
}

// ─── Overlay DOM Oluştur ─────────────────────────────────
function createScannerOverlay(useNative, headerText, extraHtml) {
    const overlay = document.createElement('div');
    overlay.className = 'ub-camera-overlay';
    overlay.innerHTML = `
        <div class="ub-camera-header">
            <span>${headerText || 'Barkod Okutma'}</span>
            <button class="ub-camera-close-btn" id="ub-cam-close">✕ Kapat</button>
        </div>
        ${useNative
            ? '<video id="ub-cam-video" autoplay playsinline muted></video>'
            : '<div id="ub-cam-reader" style="width:100%;"></div>'
        }
        <div class="ub-camera-target"></div>
        <div class="ub-camera-status" id="ub-cam-status">Kamera başlatılıyor...</div>
        ${extraHtml || ''}
    `;
    document.body.appendChild(overlay);
    return overlay;
}

// ─── BARKOD FORMATLARI ───────────────────────────────────
const BARCODE_FORMATS_NATIVE = ['ean_13', 'ean_8', 'code_128', 'code_39', 'upc_a', 'upc_e', 'itf', 'qr_code'];

// ─── ANA FONKSİYON: Tek Okuma Modu ──────────────────────
/**
 * Kamerayı açıp tek bir barkod okur ve callback ile döner.
 * Okuma başarılı olunca kamerayı kapatır.
 * 
 * @param {Function} onSuccess - (barcode: string) => void
 * @param {Object} [options]
 * @param {string} [options.headerText] - Overlay başlık metni
 */
export async function openCameraScanner(onSuccess, options = {}) {
    const useNative = 'BarcodeDetector' in window;
    const headerText = options.headerText || 'Barkod Okutma';

    // html5-qrcode yükle (iOS/Safari için)
    if (!useNative) {
        try {
            await ensureHtml5QrcodeLoaded();
        } catch (e) {
            alert('Barkod tarayıcı yüklenemedi. Lütfen barkodu manuel girin.');
            return;
        }
    }

    const overlay = createScannerOverlay(useNative, headerText);
    const statusEl = document.getElementById('ub-cam-status');
    let stream = null;
    let animFrame = null;
    let html5QrCode = null;
    let scanning = true;

    const cleanup = () => {
        scanning = false;
        if (animFrame) cancelAnimationFrame(animFrame);
        if (stream) stream.getTracks().forEach(t => t.stop());
        if (html5QrCode) { try { html5QrCode.stop(); } catch(e) {} }
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    };

    const handleScanResult = (barcode) => {
        if (navigator.vibrate) navigator.vibrate(200);
        cleanup();
        onSuccess(barcode);
    };

    document.getElementById('ub-cam-close').onclick = cleanup;
    overlay.onclick = (e) => { if (e.target === overlay) cleanup(); };

    if (useNative) {
        // ─── Chrome/Android: Native BarcodeDetector ─────
        _startNativeScanner(statusEl, handleScanResult, cleanup, (s, af) => {
            stream = s;
            animFrame = af;
        }, () => scanning);
    } else {
        // ─── iOS/Safari: html5-qrcode ile ─────
        html5QrCode = await _startHtml5QrcodeScanner(
            statusEl, handleScanResult, cleanup, headerText
        );
    }
}

// ─── ANA FONKSİYON: Seri (Continuous) Okuma Modu ────────
/**
 * Kamerayı açıp sürekli barkod okur. Her okumada callback çağırılır.
 * Kamera açık kalır, kullanıcı Kapat butonuna basana kadar.
 * 
 * @param {Function} onSuccess - (barcode: string) => void — her okumada çağırılır
 * @param {Object} [options]
 * @param {string} [options.headerText] - Overlay başlık metni
 * @param {string} [options.extraHtml] - Overlay'e eklenecek ek HTML (sayaç vb.)
 * @param {number} [options.cooldownMs] - Aynı barkod için bekleme süresi (ms), default: 1500
 */
export async function openContinuousCameraScanner(onSuccess, options = {}) {
    const useNative = 'BarcodeDetector' in window;
    const headerText = options.headerText || 'Seri Barkod Okutma';
    const extraHtml = options.extraHtml || '';
    const cooldownMs = options.cooldownMs || 1500;

    if (!useNative) {
        try {
            await ensureHtml5QrcodeLoaded();
        } catch (e) {
            alert('Barkod tarayıcı yüklenemedi. Lütfen barkodu manuel girin.');
            return;
        }
    }

    const overlay = createScannerOverlay(useNative, headerText, extraHtml);
    const statusEl = document.getElementById('ub-cam-status');
    let stream = null;
    let animFrame = null;
    let html5QrCode = null;
    let scanning = true;
    let lastScannedCode = '';
    let cooldownUntil = 0;

    const cleanup = () => {
        scanning = false;
        if (animFrame) cancelAnimationFrame(animFrame);
        if (stream) stream.getTracks().forEach(t => t.stop());
        if (html5QrCode) { try { html5QrCode.stop(); } catch(e) {} }
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    };

    const handleScanResult = (barcode) => {
        const now = Date.now();
        if (now < cooldownUntil) return;
        if (barcode === lastScannedCode && now - cooldownUntil < 500) return;
        lastScannedCode = barcode;
        cooldownUntil = now + cooldownMs;

        if (navigator.vibrate) navigator.vibrate(150);
        onSuccess(barcode);
    };

    document.getElementById('ub-cam-close').onclick = cleanup;

    if (useNative) {
        _startNativeContinuousScanner(statusEl, handleScanResult, cleanup, (s, af) => {
            stream = s;
            animFrame = af;
        }, () => scanning, () => cooldownUntil);
    } else {
        html5QrCode = await _startHtml5QrcodeScanner(
            statusEl, handleScanResult, null, headerText
        );
    }
}

// ─── Native BarcodeDetector (Android/Chrome) — Tek Okuma ─
function _startNativeScanner(statusEl, onScanResult, cleanup, setRefs, isScanning) {
    const video = document.getElementById('ub-cam-video');
    navigator.mediaDevices.getUserMedia({
        video: {
            facingMode: { ideal: 'environment' },
            width: { ideal: 1920 },
            height: { ideal: 1080 }
        }
    }).then(s => {
        setRefs(s, null);
        video.srcObject = s;
        statusEl.textContent = 'Barkodu kameraya gösterin...';

        const detector = new BarcodeDetector({ formats: BARCODE_FORMATS_NATIVE });

        const scanFrame = async () => {
            if (!isScanning() || video.readyState < 2) {
                const af = requestAnimationFrame(scanFrame);
                setRefs(s, af);
                return;
            }
            try {
                const barcodes = await detector.detect(video);
                if (barcodes.length > 0) {
                    onScanResult(barcodes[0].rawValue);
                    return;
                }
            } catch (e) {}
            const af = requestAnimationFrame(scanFrame);
            setRefs(s, af);
        };
        video.onloadedmetadata = () => scanFrame();
    }).catch(err => {
        statusEl.textContent = 'Kamera erişimi reddedildi: ' + err.message;
        setTimeout(cleanup, 3000);
    });
}

// ─── Native BarcodeDetector (Android/Chrome) — Sürekli Okuma ─
function _startNativeContinuousScanner(statusEl, onScanResult, cleanup, setRefs, isScanning, getCooldownUntil) {
    const video = document.getElementById('ub-cam-video');
    navigator.mediaDevices.getUserMedia({
        video: {
            facingMode: { ideal: 'environment' },
            width: { ideal: 1920 },
            height: { ideal: 1080 }
        }
    }).then(s => {
        setRefs(s, null);
        video.srcObject = s;
        statusEl.textContent = 'Barkodları sırayla kameraya gösterin...';

        const detector = new BarcodeDetector({ formats: BARCODE_FORMATS_NATIVE });

        const scanFrame = async () => {
            if (!isScanning() || video.readyState < 2) {
                const af = requestAnimationFrame(scanFrame);
                setRefs(s, af);
                return;
            }
            try {
                const now = Date.now();
                if (now >= getCooldownUntil()) {
                    const barcodes = await detector.detect(video);
                    if (barcodes.length > 0) {
                        onScanResult(barcodes[0].rawValue);
                    }
                }
            } catch (e) {}
            const af = requestAnimationFrame(scanFrame);
            setRefs(s, af);
        };
        video.onloadedmetadata = () => scanFrame();
    }).catch(err => {
        statusEl.textContent = 'Kamera erişimi reddedildi: ' + err.message;
        setTimeout(cleanup, 3000);
    });
}

// ─── html5-qrcode (iOS/Safari) — İkisi İçin Ortak ──────
async function _startHtml5QrcodeScanner(statusEl, onScanResult, cleanup, headerText) {
    const html5QrCode = new Html5Qrcode('ub-cam-reader');
    statusEl.textContent = headerText || 'Barkodu kameraya gösterin...';

    // iOS için en iyi arka kamerayı seç
    const bestCameraId = await getBestBackCameraId();

    // Kamera ayarları
    const config = {
        fps: 8,
        qrbox: { width: 280, height: 150 },
        // aspectRatio kaldırıldı — iOS'ta sorun çıkarıyor
    };

    // Kamera kaynağı: deviceId veya facingMode
    const cameraIdOrConfig = bestCameraId || { facingMode: { exact: 'environment' } };

    try {
        await html5QrCode.start(
            cameraIdOrConfig,
            config,
            (decodedText) => onScanResult(decodedText),
            () => {} // hata — sessiz devam
        );
    } catch (err1) {
        console.warn('Kamera başlatma denemesi 1 başarısız, fallback deneniyor:', err1);
        // Fallback: facingMode ideal ile dene
        try {
            await html5QrCode.start(
                { facingMode: 'environment' },
                config,
                (decodedText) => onScanResult(decodedText),
                () => {}
            );
        } catch (err2) {
            console.error('Kamera başlatma tamamen başarısız:', err2);
            statusEl.textContent = 'Kamera başlatılamadı: ' + (err2.message || err2);
            if (cleanup) setTimeout(cleanup, 3000);
        }
    }

    return html5QrCode;
}
