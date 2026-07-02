/** @odoo-module **/

/**
 * Merkezi Kamera Barkod Tarayıcı Modülü
 * 
 * Tüm ekranlarda kullanılan kamera barkod okutma fonksiyonelliğini
 * tek bir yerde toplar. iOS/Safari, PWA ve Android/Chrome uyumluluğunu sağlar.
 * 
 * Akış:
 * 1. BarcodeDetector varsa (Chrome/Android) → native tarama
 * 2. Yoksa → WebRTC adapter polyfill + html5-qrcode
 * 3. Kamera API hiç yoksa (iOS PWA) → otomatik Safari'de aç
 */

// ─── iOS Algılama ─────────────────────────────────────────
function isIOS() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

// ─── iOS PWA (Standalone) Modu Algılama ───────────────────
function isStandalonePWA() {
    return window.navigator.standalone === true || 
        window.matchMedia('(display-mode: standalone)').matches;
}

// ─── MediaDevices Polyfill ────────────────────────────────
// Eski iOS sürümlerinde navigator.mediaDevices tanımsız olabilir.
// WebRTC adapter.js + manuel polyfill ile normalize ediyoruz.
let _adapterLoaded = false;
async function ensureMediaDevicesReady() {
    // 1. WebRTC adapter.js yükle (cross-browser polyfill)
    if (!_adapterLoaded) {
        try {
            await new Promise((resolve, reject) => {
                if (window.adapter) { resolve(); return; }
                const s = document.createElement('script');
                s.src = 'https://webrtc.github.io/adapter/adapter-latest.js';
                s.onload = () => { _adapterLoaded = true; resolve(); };
                s.onerror = () => resolve(); // Hata olsa bile devam et
                document.head.appendChild(s);
            });
        } catch(e) { /* devam et */ }
    }

    // 2. Manuel polyfill — adapter.js'nin yakalayamadığı durumlar için
    if (typeof navigator.mediaDevices === 'undefined') {
        navigator.mediaDevices = {};
    }
    if (typeof navigator.mediaDevices.getUserMedia === 'undefined') {
        navigator.mediaDevices.getUserMedia = function(constraints) {
            const legacy = navigator.webkitGetUserMedia || navigator.mozGetUserMedia || navigator.getUserMedia;
            if (!legacy) {
                return Promise.reject(new Error('getUserMedia desteklenmiyor'));
            }
            return new Promise((resolve, reject) => {
                legacy.call(navigator, constraints, resolve, reject);
            });
        };
    }
}

// ─── Kamera API Desteği Kontrolü (Polyfill sonrası) ──────
function canUseCamera() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

// ─── Gerçekten kamera erişilebilir mi test et ─────────────
// canUseCamera() true dönse bile getUserMedia çağrısı başarısız olabilir.
// Bu fonksiyon GERÇEKTEN kamera açabiliyor muyuz diye test eder.
async function testCameraAccess() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ 
            video: { facingMode: 'environment' } 
        });
        // Kamera açıldı! Hemen kapat (test amaçlı)
        stream.getTracks().forEach(t => t.stop());
        return true;
    } catch(e) {
        console.warn('Kamera erişim testi başarısız:', e.name, e.message);
        return false;
    }
}

// ─── Safari'de Otomatik Aç ───────────────────────────────
// iOS PWA'da kamera çalışmıyorsa, aynı sayfayı Safari'de açar.
// window.open() iOS PWA'da Safari sekmesinde açar.
function openInSafari() {
    const url = window.location.href;
    // iOS PWA'da window.open Safari'de açar
    window.open(url, '_blank');
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

        const mainBack = cameras.find(c =>
            c.label === 'Back Camera' || /^back camera$/i.test(c.label)
        );
        if (mainBack) return mainBack.id;

        const filteredBack = cameras.find(c =>
            /back/i.test(c.label) && !/ultra|wide|telephoto|tele/i.test(c.label)
        );
        if (filteredBack) return filteredBack.id;

        const anyBack = cameras.find(c =>
            /back|rear|environment|arka/i.test(c.label)
        );
        if (anyBack) return anyBack.id;

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
export async function openCameraScanner(onSuccess, options = {}) {
    const headerText = options.headerText || 'Barkod Okutma';

    // ─── ADIM 1: Polyfill'leri yükle ─────────────────
    await ensureMediaDevicesReady();

    // ─── ADIM 2: Kamera API'si var mı? ───────────────
    if (!canUseCamera()) {
        // API yok — iOS PWA mı?
        if (isIOS() && isStandalonePWA()) {
            // Safari'de otomatik aç
            openInSafari();
            return;
        }
        // Diğer durumlarda bilgi ver
        alert('Bu tarayıcıda kamera desteği yok. Safari veya Chrome kullanın.');
        return;
    }

    // ─── ADIM 3: Kamera GERÇEKTEN açılabiliyor mu? ───
    const cameraWorks = await testCameraAccess();
    if (!cameraWorks) {
        if (isIOS() && isStandalonePWA()) {
            openInSafari();
            return;
        }
        alert('Kamera erişimi reddedildi. Tarayıcı ayarlarından kamera iznini kontrol edin.');
        return;
    }

    // ─── ADIM 4: Kamera çalışıyor — tarayıcıyı başlat ─
    const useNative = 'BarcodeDetector' in window;

    if (!useNative) {
        try {
            await ensureHtml5QrcodeLoaded();
        } catch (e) {
            alert('Barkod tarayıcı yüklenemedi. Lütfen sayfayı yenileyin.');
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
        _startNativeScanner(statusEl, handleScanResult, cleanup, (s, af) => {
            stream = s;
            animFrame = af;
        }, () => scanning);
    } else {
        try {
            html5QrCode = await _startHtml5QrcodeScanner(
                statusEl, handleScanResult, cleanup, headerText
            );
            if (!html5QrCode) {
                // html5-qrcode başarısız — doğrudan kamera ile dene
                const manualOk = await _startManualScanner(
                    overlay, statusEl, handleScanResult, cleanup
                );
                if (!manualOk) {
                    cleanup();
                    if (isIOS() && isStandalonePWA()) {
                        openInSafari();
                    }
                }
            }
        } catch (err) {
            console.error('Tarayıcı başlatma hatası:', err);
            // Son çare: doğrudan kamera ile dene
            const manualOk = await _startManualScanner(
                overlay, statusEl, handleScanResult, cleanup
            );
            if (!manualOk) {
                cleanup();
                if (isIOS() && isStandalonePWA()) {
                    openInSafari();
                }
            }
        }
    }
}

// ─── ANA FONKSİYON: Seri (Continuous) Okuma Modu ────────
export async function openContinuousCameraScanner(onSuccess, options = {}) {
    const headerText = options.headerText || 'Seri Barkod Okutma';
    const extraHtml = options.extraHtml || '';
    const cooldownMs = options.cooldownMs || 1500;

    await ensureMediaDevicesReady();

    if (!canUseCamera()) {
        if (isIOS() && isStandalonePWA()) {
            openInSafari();
            return;
        }
        alert('Bu tarayıcıda kamera desteği yok. Safari veya Chrome kullanın.');
        return;
    }

    const cameraWorks = await testCameraAccess();
    if (!cameraWorks) {
        if (isIOS() && isStandalonePWA()) {
            openInSafari();
            return;
        }
        alert('Kamera erişimi reddedildi.');
        return;
    }

    const useNative = 'BarcodeDetector' in window;

    if (!useNative) {
        try {
            await ensureHtml5QrcodeLoaded();
        } catch (e) {
            alert('Barkod tarayıcı yüklenemedi.');
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
        try {
            html5QrCode = await _startHtml5QrcodeScanner(
                statusEl, handleScanResult, null, headerText
            );
            if (!html5QrCode) {
                await _startManualScanner(overlay, statusEl, handleScanResult, null);
            }
        } catch (err) {
            await _startManualScanner(overlay, statusEl, handleScanResult, null);
        }
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

// ─── DOĞRUDAN KAMERA (html5-qrcode bypass) ──────────────
// html5-qrcode başarısız olursa, getUserMedia'yı doğrudan çağırıp
// canvas üzerinden html5-qrcode'un scanFile metoduyla decode eder.
async function _startManualScanner(overlay, statusEl, onScanResult, cleanup) {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'environment' }
        });

        // Video elementini bul veya oluştur
        let video = overlay.querySelector('video');
        if (!video) {
            video = document.createElement('video');
            video.style.cssText = 'width:100%;max-height:60vh;object-fit:cover;border-radius:8px;';
            const readerDiv = overlay.querySelector('#ub-cam-reader');
            if (readerDiv) {
                readerDiv.innerHTML = '';
                readerDiv.appendChild(video);
            } else {
                const statusDiv = overlay.querySelector('#ub-cam-status');
                if (statusDiv) statusDiv.parentNode.insertBefore(video, statusDiv);
            }
        }

        video.setAttribute('playsinline', '');
        video.setAttribute('autoplay', '');
        video.muted = true;
        video.srcObject = stream;
        await video.play();

        statusEl.textContent = 'Barkodu kameraya gösterin...';

        // Canvas + decode döngüsü
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        let scanning = true;

        // Gizli reader div (scanFile için)
        let hiddenReader = document.getElementById('ub-manual-reader');
        if (!hiddenReader) {
            hiddenReader = document.createElement('div');
            hiddenReader.id = 'ub-manual-reader';
            hiddenReader.style.display = 'none';
            document.body.appendChild(hiddenReader);
        }

        await ensureHtml5QrcodeLoaded();
        const decoder = new Html5Qrcode('ub-manual-reader');

        const scanLoop = async () => {
            if (!scanning || video.readyState < 2) {
                if (scanning) setTimeout(scanLoop, 250);
                return;
            }

            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            ctx.drawImage(video, 0, 0);

            try {
                const blob = await new Promise(r => canvas.toBlob(r, 'image/jpeg', 0.85));
                if (blob) {
                    const file = new File([blob], 'frame.jpg', { type: 'image/jpeg' });
                    const result = await decoder.scanFile(file, false);
                    if (result) {
                        scanning = false;
                        stream.getTracks().forEach(t => t.stop());
                        if (hiddenReader.parentNode) hiddenReader.parentNode.removeChild(hiddenReader);
                        onScanResult(result);
                        return;
                    }
                }
            } catch(e) {
                // Bu framede barkod bulunamadı — devam
            }

            if (scanning) setTimeout(scanLoop, 200); // 5 FPS
        };

        scanLoop();

        // Cleanup'a stream kapatmayı ekle
        if (cleanup) {
            const origCleanup = overlay.querySelector('#ub-cam-close').onclick;
            overlay.querySelector('#ub-cam-close').onclick = () => {
                scanning = false;
                stream.getTracks().forEach(t => t.stop());
                if (hiddenReader.parentNode) hiddenReader.parentNode.removeChild(hiddenReader);
                if (origCleanup) origCleanup();
                else if (cleanup) cleanup();
            };
        }

        return true;
    } catch(e) {
        console.error('Manuel kamera başlatma başarısız:', e);
        return false;
    }
}

// ─── html5-qrcode (iOS/Safari) — İkisi İçin Ortak ──────
async function _startHtml5QrcodeScanner(statusEl, onScanResult, cleanup, headerText) {
    if (!canUseCamera()) {
        return null;
    }

    const html5QrCode = new Html5Qrcode('ub-cam-reader');
    statusEl.textContent = headerText || 'Barkodu kameraya gösterin...';

    const config = {
        fps: 8,
        qrbox: { width: 280, height: 150 },
    };

    let started = false;

    // Deneme 1: facingMode: 'environment'
    if (!started) {
        try {
            await html5QrCode.start(
                { facingMode: 'environment' },
                config,
                (decodedText) => onScanResult(decodedText),
                () => {}
            );
            started = true;
        } catch (err1) {
            console.warn('facingMode environment başarısız:', err1);
        }
    }

    // Deneme 2: facingMode: { exact: 'environment' }
    if (!started) {
        try {
            await html5QrCode.start(
                { facingMode: { exact: 'environment' } },
                config,
                (decodedText) => onScanResult(decodedText),
                () => {}
            );
            started = true;
        } catch (err2) {
            console.warn('facingMode exact environment başarısız:', err2);
        }
    }

    // Deneme 3: Kamera listesinden seç
    if (!started) {
        try {
            const bestCameraId = await getBestBackCameraId();
            if (bestCameraId) {
                await html5QrCode.start(
                    bestCameraId,
                    config,
                    (decodedText) => onScanResult(decodedText),
                    () => {}
                );
                started = true;
            }
        } catch (err3) {
            console.warn('getCameras fallback başarısız:', err3);
        }
    }

    // Deneme 4: Ön kamera (son çare)
    if (!started) {
        try {
            await html5QrCode.start(
                { facingMode: 'user' },
                config,
                (decodedText) => onScanResult(decodedText),
                () => {}
            );
            started = true;
        } catch (err4) {
            console.error('html5-qrcode tamamen başarısız:', err4);
            return null;
        }
    }

    // Arka planda daha iyi kameraya geçiş (iOS)
    if (started && isIOS()) {
        setTimeout(async () => {
            try {
                const bestId = await getBestBackCameraId();
                if (bestId) {
                    const runningCameraId = html5QrCode.getRunningTrackCameraCapabilities &&
                        html5QrCode.getRunningTrackSettings &&
                        html5QrCode.getRunningTrackSettings().deviceId;
                    
                    if (runningCameraId && runningCameraId !== bestId) {
                        await html5QrCode.stop();
                        await html5QrCode.start(
                            bestId,
                            config,
                            (decodedText) => onScanResult(decodedText),
                            () => {}
                        );
                    }
                }
            } catch (e) {
                console.warn('Kamera geçişi başarısız:', e);
            }
        }, 1500);
    }

    return html5QrCode;
}
