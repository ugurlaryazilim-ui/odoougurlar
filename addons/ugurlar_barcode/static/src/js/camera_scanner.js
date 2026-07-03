/** @odoo-module **/

/**
 * Merkezi Kamera Barkod Tarayıcı Modülü v4 (FINAL)
 * 
 * SORUNLAR ve ÇÖZÜMLER:
 * 1. adapter.js → iOS native API'yi bozuyor → KALDIRILDI
 * 2. applyConstraints() → iOS'ta stream'i öldürüyor → KULLANILMIYOR
 * 3. html5-qrcode scanFile() → iOS'ta pure JS decoder barkod çözemez → WASM polyfill
 * 4. visibilitychange stream.stop() → kalıcı kapatıyor → KALDIRILDI
 * 
 * Mimari:
 * - getUserMedia ile kamerayı AÇ (basit constraint, applyConstraints YOK)
 * - @undecaf/barcode-detector-polyfill (ZBar WASM) ile decode
 * - BarcodeDetector.detect(video) döngüsü ile tarama
 * - iOS PWA'da kamera yoksa → otomatik Safari'de aç
 */

// ─── iOS Algılama ─────────────────────────────────────────
function isIOS() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

function isStandalonePWA() {
    return window.navigator.standalone === true || 
        window.matchMedia('(display-mode: standalone)').matches;
}

// ─── Kamera API Kontrolü ─────────────────────────────────
// NOT: adapter.js KULLANILMIYOR — iOS Safari'de native API'yi bozuyor
// NOT: applyConstraints KULLANILMIYOR — iOS'ta stream'i öldürüyor
function canUseCamera() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

// ─── Safari'de Otomatik Aç ───────────────────────────────
function openInSafari() {
    window.open(window.location.href, '_blank');
}

// ─── BarcodeDetector Polyfill (ZBar WASM) ────────────────
// iOS/Safari'de native BarcodeDetector YOK.
// @undecaf/barcode-detector-polyfill ZBar WASM ile decode eder.
// Bu, pure JS html5-qrcode'dan ÇOK DAHA HIZLI ve güvenilirdir.
let _polyfillLoaded = false;
async function ensureBarcodeDetector() {
    // Native varsa kullan (Chrome/Android)
    if (window.BarcodeDetector) {
        try {
            await window.BarcodeDetector.getSupportedFormats();
            return true;
        } catch(e) {}
    }
    
    // Polyfill yükle (iOS/Safari)
    if (!_polyfillLoaded) {
        try {
            // ES module olarak yükle
            const module = await import(
                'https://cdn.jsdelivr.net/npm/@undecaf/barcode-detector-polyfill@0.9.23/dist/main.js'
            );
            window.BarcodeDetector = module.BarcodeDetectorPolyfill;
            _polyfillLoaded = true;
            console.info('BarcodeDetector polyfill (ZBar WASM) yüklendi');
            return true;
        } catch(e) {
            console.error('BarcodeDetector polyfill yüklenemedi:', e);
            return false;
        }
    }
    
    return !!window.BarcodeDetector;
}

// ─── html5-qrcode CDN (yedek decoder) ────────────────────
let _cdnLoaded = false;
async function ensureHtml5QrcodeLoaded() {
    if (window.Html5Qrcode || _cdnLoaded) return;
    await new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = 'https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js';
        s.onload = () => { _cdnLoaded = true; resolve(); };
        s.onerror = () => reject(new Error('html5-qrcode yüklenemedi'));
        document.head.appendChild(s);
    });
}

// ─── Kamera Aç ──────────────────────────────────────────
// iPhone'da ÇALIŞAN yaklaşım:
// - 4 farklı constraint dener (en iyisinden en basite)
// - applyConstraints KULLANMAZ
// - Stream'i asla kapatıp yeniden açmaz
// - facingMode: {ideal:'environment'} kullanır (exact DEĞİL)
async function getCamera() {
    const attempts = [
        {
            video: {
                facingMode: { ideal: 'environment' },
                width: { ideal: 1280 },
                height: { ideal: 720 }
            },
            audio: false
        },
        {
            video: {
                facingMode: 'environment',
                width: { ideal: 640 },
                height: { ideal: 480 }
            },
            audio: false
        },
        {
            video: {
                facingMode: 'environment'
            },
            audio: false
        },
        {
            video: true,
            audio: false
        }
    ];

    for (const constraints of attempts) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia(constraints);
            const track = stream.getVideoTracks()[0];
            if (track) {
                const s = track.getSettings();
                console.info('Kamera açıldı:', s.width + 'x' + s.height, 'label:', track.label);
            }
            return stream;
        } catch(e) {
            console.warn('Kamera denemesi:', e.name, e.message);
        }
    }
    return null;
}

// ─── BARKOD FORMATLARI ───────────────────────────────────
const BARCODE_FORMATS = ['ean_13', 'ean_8', 'code_128', 'code_39', 'upc_a', 'upc_e', 'itf', 'qr_code'];

// ─── Overlay DOM Oluştur ─────────────────────────────────
function createScannerOverlay(headerText, extraHtml) {
    const overlay = document.createElement('div');
    overlay.className = 'ub-camera-overlay';
    overlay.innerHTML = `
        <div class="ub-camera-header">
            <span>${headerText || 'Barkod Okutma'}</span>
            <button class="ub-camera-close-btn" id="ub-cam-close">✕ Kapat</button>
        </div>
        <video id="ub-cam-video" autoplay playsinline muted 
               style="width:100%;max-height:65vh;object-fit:cover;background:#000;"></video>
        <div class="ub-camera-target"></div>
        <div class="ub-camera-status" id="ub-cam-status">Kamera başlatılıyor...</div>
        ${extraHtml || ''}
    `;
    document.body.appendChild(overlay);
    return overlay;
}

// ─── ANA FONKSİYON: Tek Okuma Modu ──────────────────────
export async function openCameraScanner(onSuccess, options = {}) {
    const headerText = options.headerText || 'Barkod Okutma';

    // 1. Kamera API var mı?
    if (!canUseCamera()) {
        if (isIOS()) { openInSafari(); return; }
        alert('Bu tarayıcıda kamera desteği yok. Safari veya Chrome kullanın.');
        return;
    }

    // 2. Overlay oluştur
    const overlay = createScannerOverlay(headerText);
    const video = document.getElementById('ub-cam-video');
    const statusEl = document.getElementById('ub-cam-status');
    let stream = null;
    let scanning = true;

    const cleanup = () => {
        scanning = false;
        if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    };

    document.getElementById('ub-cam-close').onclick = cleanup;
    overlay.onclick = (e) => { if (e.target === overlay) cleanup(); };

    // 3. Kamerayı aç
    statusEl.textContent = 'Kamera açılıyor...';
    stream = await getCamera();
    
    if (!stream) {
        statusEl.textContent = 'Kamera açılamadı.';
        if (isIOS() && isStandalonePWA()) {
            setTimeout(() => { cleanup(); openInSafari(); }, 500);
        } else {
            setTimeout(cleanup, 3000);
        }
        return;
    }

    // 4. Video'ya bağla
    video.srcObject = stream;
    try {
        await video.play();
    } catch(e) {
        console.warn('video.play() hatası:', e);
    }

    statusEl.textContent = 'Barkod tarayıcı yükleniyor...';

    // 5. BarcodeDetector polyfill yükle (WASM — iOS için kritik)
    const detectorReady = await ensureBarcodeDetector();
    
    if (detectorReady) {
        // ─── ANA YOL: BarcodeDetector (native veya WASM polyfill) ─────
        statusEl.textContent = 'Barkodu kameraya gösterin...';
        _scanWithDetector(video, statusEl, (barcode) => {
            if (navigator.vibrate) navigator.vibrate(200);
            cleanup();
            onSuccess(barcode);
        }, () => scanning);
    } else {
        // ─── YEDEK YOL: html5-qrcode scanFile (son çare) ─────
        statusEl.textContent = 'Yedek tarayıcı yükleniyor...';
        try {
            await ensureHtml5QrcodeLoaded();
        } catch(e) {
            statusEl.textContent = 'Barkod kütüphanesi yüklenemedi.';
            setTimeout(cleanup, 3000);
            return;
        }
        statusEl.textContent = 'Barkodu kameraya gösterin...';
        _scanWithCanvasDecode(video, statusEl, (barcode) => {
            if (navigator.vibrate) navigator.vibrate(200);
            cleanup();
            onSuccess(barcode);
        }, () => scanning);
    }
}

// ─── ANA FONKSİYON: Seri (Continuous) Okuma Modu ────────
export async function openContinuousCameraScanner(onSuccess, options = {}) {
    const headerText = options.headerText || 'Seri Barkod Okutma';
    const extraHtml = options.extraHtml || '';
    const cooldownMs = options.cooldownMs || 1500;

    if (!canUseCamera()) {
        if (isIOS()) { openInSafari(); return; }
        alert('Bu tarayıcıda kamera desteği yok.');
        return;
    }

    const overlay = createScannerOverlay(headerText, extraHtml);
    const video = document.getElementById('ub-cam-video');
    const statusEl = document.getElementById('ub-cam-status');
    let stream = null;
    let scanning = true;
    let lastScannedCode = '';
    let cooldownUntil = 0;

    const cleanup = () => {
        scanning = false;
        if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    };

    document.getElementById('ub-cam-close').onclick = cleanup;

    statusEl.textContent = 'Kamera açılıyor...';
    stream = await getCamera();

    if (!stream) {
        if (isIOS() && isStandalonePWA()) {
            cleanup(); openInSafari();
        } else {
            statusEl.textContent = 'Kamera açılamadı.';
            setTimeout(cleanup, 3000);
        }
        return;
    }

    video.srcObject = stream;
    try { await video.play(); } catch(e) {}

    const handleResult = (barcode) => {
        const now = Date.now();
        if (now < cooldownUntil) return;
        if (barcode === lastScannedCode && now - cooldownUntil < 500) return;
        lastScannedCode = barcode;
        cooldownUntil = now + cooldownMs;
        if (navigator.vibrate) navigator.vibrate(150);
        onSuccess(barcode);
    };

    const detectorReady = await ensureBarcodeDetector();

    if (detectorReady) {
        statusEl.textContent = 'Barkodları sırayla kameraya gösterin...';
        _scanWithDetector(video, statusEl, handleResult, () => scanning);
    } else {
        try { await ensureHtml5QrcodeLoaded(); } catch(e) { cleanup(); return; }
        statusEl.textContent = 'Barkodları sırayla kameraya gösterin...';
        _scanWithCanvasDecode(video, statusEl, handleResult, () => scanning);
    }
}

// ─── BarcodeDetector ile Tarama (ANA YOL) ────────────────
// Native BarcodeDetector (Chrome) veya WASM polyfill (iOS) ile çalışır.
// Doğrudan video elementinden detect eder — canvas/blob GEREKMEZ.
function _scanWithDetector(video, statusEl, onResult, isScanning) {
    const detector = new BarcodeDetector({ formats: BARCODE_FORMATS });
    
    const scanFrame = async () => {
        if (!isScanning() || video.readyState < 2) {
            if (isScanning()) setTimeout(scanFrame, 200);
            return;
        }
        try {
            const barcodes = await detector.detect(video);
            if (barcodes.length > 0) {
                onResult(barcodes[0].rawValue);
                return;
            }
        } catch (e) {
            // Frame decode hatası — devam
        }
        if (isScanning()) setTimeout(scanFrame, 200); // ~5 FPS
    };
    
    if (video.readyState >= 2) {
        scanFrame();
    } else {
        video.onloadedmetadata = () => scanFrame();
    }
}

// ─── Canvas + html5-qrcode scanFile ile Tarama (YEDEK) ──
// Sadece BarcodeDetector polyfill yüklenemezse kullanılır.
function _scanWithCanvasDecode(video, statusEl, onResult, isScanning) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    
    let hiddenReader = document.getElementById('ub-hidden-reader');
    if (!hiddenReader) {
        hiddenReader = document.createElement('div');
        hiddenReader.id = 'ub-hidden-reader';
        hiddenReader.style.display = 'none';
        document.body.appendChild(hiddenReader);
    }
    
    const decoder = new Html5Qrcode('ub-hidden-reader');
    let decoding = false;
    
    const scanFrame = async () => {
        if (!isScanning() || video.readyState < 2 || decoding) {
            if (isScanning()) setTimeout(scanFrame, 250);
            return;
        }
        
        decoding = true;
        
        try {
            const vw = video.videoWidth;
            const vh = video.videoHeight;
            
            if (vw === 0 || vh === 0) {
                decoding = false;
                if (isScanning()) setTimeout(scanFrame, 300);
                return;
            }
            
            canvas.width = vw;
            canvas.height = vh;
            ctx.drawImage(video, 0, 0, vw, vh);
            
            const blob = await new Promise(resolve => 
                canvas.toBlob(resolve, 'image/jpeg', 0.92)
            );
            
            if (blob && isScanning()) {
                const file = new File([blob], 'f.jpg', { type: 'image/jpeg' });
                try {
                    const result = await decoder.scanFile(file, false);
                    if (result) {
                        if (hiddenReader.parentNode) hiddenReader.parentNode.removeChild(hiddenReader);
                        onResult(result);
                        decoding = false;
                        return;
                    }
                } catch(e) {}
            }
        } catch(e) {}
        
        decoding = false;
        if (isScanning()) setTimeout(scanFrame, 200);
    };
    
    if (video.readyState >= 2) {
        scanFrame();
    } else {
        video.onloadedmetadata = () => scanFrame();
    }
}
