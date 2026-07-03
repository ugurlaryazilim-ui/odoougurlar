/** @odoo-module **/

/**
 * Merkezi Kamera Barkod Tarayıcı Modülü v3
 * 
 * ÖNEMLİ DEĞİŞİKLİK: html5-qrcode'un kamera yönetimi KULLANILMIYOR.
 * Kamerayı doğrudan getUserMedia ile yönetiyoruz.
 * html5-qrcode sadece "fotoğraftan decode" için kullanılıyor.
 * 
 * Mimari (3 katmanlı):
 * 1. BarcodeDetector varsa (Chrome/Android) → getUserMedia + detect(video)
 * 2. BarcodeDetector yoksa (iOS/Safari) → getUserMedia + canvas capture + html5-qrcode scanFile
 * 3. Kamera API yoksa (iOS PWA standalone) → otomatik Safari'de aç
 * 
 * iOS Optimizasyonları:
 * - Düşük çözünürlük: 1280x720 (1920x1080 DEĞİL)
 * - Düşük FPS: 4-5 FPS decode
 * - playsinline + muted + autoplay
 * - Her okumadan sonra stream durdurulur
 * - visibilitychange ile stream yönetimi
 * - html5-qrcode'un kamera yönetimi BYPASS edildi
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
async function ensureMediaDevicesReady() {
    // WebRTC adapter.js yükle
    if (!window._adapterLoaded) {
        try {
            await new Promise((resolve) => {
                if (window.adapter) { resolve(); return; }
                const s = document.createElement('script');
                s.src = 'https://webrtc.github.io/adapter/adapter-latest.js';
                s.onload = () => { window._adapterLoaded = true; resolve(); };
                s.onerror = () => resolve();
                document.head.appendChild(s);
            });
        } catch(e) { /* devam */ }
    }

    // Manuel polyfill
    if (typeof navigator.mediaDevices === 'undefined') {
        navigator.mediaDevices = {};
    }
    if (typeof navigator.mediaDevices.getUserMedia === 'undefined') {
        navigator.mediaDevices.getUserMedia = function(c) {
            const legacy = navigator.webkitGetUserMedia || navigator.mozGetUserMedia || navigator.getUserMedia;
            if (!legacy) return Promise.reject(new Error('getUserMedia yok'));
            return new Promise((res, rej) => { legacy.call(navigator, c, res, rej); });
        };
    }
}

// ─── html5-qrcode CDN (sadece decode için) ────────────────
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

// ─── Kamera API Kontrolü ─────────────────────────────────
function canUseCamera() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

// ─── Safari'de Otomatik Aç ───────────────────────────────
function openInSafari() {
    window.open(window.location.href, '_blank');
}

// ─── Ana Arka Kamerayı Bul ────────────────────────────────
// iPhone'da birden fazla arka kamera var: Wide, Ultra Wide, Telephoto, Macro
// Bu fonksiyon ana "Wide" kamerayı seçer.
async function findMainBackCameraId() {
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices.filter(d => d.kind === 'videoinput');
        
        if (videoDevices.length === 0) return null;
        
        console.info('Bulunan kameralar:', videoDevices.map(d => d.label || d.deviceId).join(', '));
        
        // 1. Tam olarak "Back Camera" etiketli (Apple'ın ana arka kamerası)
        const mainBack = videoDevices.find(d => 
            d.label === 'Back Camera' || /^back camera$/i.test(d.label)
        );
        if (mainBack) { console.info('Ana kamera bulundu:', mainBack.label); return mainBack.deviceId; }
        
        // 2. "back" içerip "ultra"/"wide"/"telephoto"/"macro" İÇERMEYEN
        const filtered = videoDevices.find(d => 
            /back/i.test(d.label) && 
            !/ultra|wide|telephoto|tele|macro/i.test(d.label)
        );
        if (filtered) { console.info('Filtrelenmiş kamera:', filtered.label); return filtered.deviceId; }
        
        // 3. "back" veya "rear" içeren herhangi biri (ilk bulunan)
        const anyBack = videoDevices.find(d => /back|rear|arka/i.test(d.label));
        if (anyBack) { console.info('Arka kamera:', anyBack.label); return anyBack.deviceId; }
        
        // 4. Label boşsa (izin verilmemişse) → son kamera genelde arka kameradır
        return videoDevices[videoDevices.length - 1].deviceId;
    } catch(e) {
        console.warn('Kamera listesi alınamadı:', e);
        return null;
    }
}

// ─── Kamera Aç (iPhone Ana Kamera Öncelikli) ────────────
async function getCamera() {
    // ADIM 1: Önce facingMode ile izin al + stream başlat
    let stream = null;
    const initialConstraints = [
        { video: { facingMode: 'environment' }, audio: false },
        { video: true, audio: false }
    ];
    
    for (const c of initialConstraints) {
        try {
            stream = await navigator.mediaDevices.getUserMedia(c);
            console.info('İlk kamera açıldı:', JSON.stringify(c.video));
            break;
        } catch(e) {
            console.warn('İlk kamera denemesi:', e.name, e.message);
        }
    }
    
    if (!stream) return null;
    
    // ADIM 2: İzin alındı — şimdi ana arka kamerayı bul ve yüksek çözünürlükle geç
    try {
        const mainCameraId = await findMainBackCameraId();
        
        if (mainCameraId) {
            // Mevcut stream'in kamerasını kontrol et
            const currentTrack = stream.getVideoTracks()[0];
            const currentSettings = currentTrack.getSettings();
            
            // Farklı bir kameraysa VEYA çözünürlük düşükse → geçiş yap
            if (currentSettings.deviceId !== mainCameraId || 
                (currentSettings.width && currentSettings.width < 1280)) {
                
                // Eski stream'i kapat
                stream.getTracks().forEach(t => t.stop());
                
                // Ana kamerayı yüksek çözünürlükle aç
                stream = await navigator.mediaDevices.getUserMedia({
                    video: {
                        deviceId: { exact: mainCameraId },
                        width: { ideal: 1920 },
                        height: { ideal: 1080 }
                    },
                    audio: false
                });
                console.info('Ana kameraya geçildi, çözünürlük:', 
                    stream.getVideoTracks()[0].getSettings().width + 'x' + 
                    stream.getVideoTracks()[0].getSettings().height);
            }
        }
    } catch(e) {
        // Geçiş başarısız — mevcut stream ile devam et (sorun yok)
        console.warn('Kamera geçişi başarısız, mevcut kamerada devam:', e.message);
    }
    
    // ADIM 3: Mevcut stream'in çözünürlüğünü yükseltmeyi dene
    try {
        const track = stream.getVideoTracks()[0];
        const capabilities = track.getCapabilities ? track.getCapabilities() : null;
        if (capabilities && capabilities.width && capabilities.width.max >= 1920) {
            await track.applyConstraints({
                width: { ideal: 1920 },
                height: { ideal: 1080 }
            });
            console.info('Çözünürlük yükseltildi:', 
                track.getSettings().width + 'x' + track.getSettings().height);
        }
        
        // Sürekli otomatik odaklama (barkod için önemli)
        if (capabilities && capabilities.focusMode && 
            capabilities.focusMode.includes('continuous')) {
            await track.applyConstraints({ focusMode: 'continuous' });
            console.info('Sürekli odaklama aktif');
        }
    } catch(e) {
        console.warn('Constraint ayarlanamadı:', e.message);
    }
    
    return stream;
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

    // 1. Polyfill yükle
    await ensureMediaDevicesReady();

    // 2. Kamera API var mı?
    if (!canUseCamera()) {
        if (isIOS()) { openInSafari(); return; }
        alert('Bu tarayıcıda kamera desteği yok. Safari veya Chrome kullanın.');
        return;
    }

    // 3. Overlay oluştur
    const overlay = createScannerOverlay(headerText);
    const video = document.getElementById('ub-cam-video');
    const statusEl = document.getElementById('ub-cam-status');
    let stream = null;
    let scanning = true;
    let scanTimer = null;

    const cleanup = () => {
        scanning = false;
        if (scanTimer) clearTimeout(scanTimer);
        if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    };

    document.getElementById('ub-cam-close').onclick = cleanup;
    overlay.onclick = (e) => { if (e.target === overlay) cleanup(); };

    // 4. Kamerayı aç
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

    // 5. Video'ya bağla
    video.srcObject = stream;
    try {
        await video.play();
    } catch(e) {
        console.warn('video.play() hatası:', e);
    }

    // 6. visibilitychange — iOS'ta arka plana atılınca stream donmasını engelle
    const onVisibilityChange = () => {
        if (document.hidden && stream) {
            stream.getTracks().forEach(t => t.stop());
        }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    
    // cleanup'a visibility handler temizliğini ekle
    const origCleanup = cleanup;
    const fullCleanup = () => {
        document.removeEventListener('visibilitychange', onVisibilityChange);
        origCleanup();
    };
    document.getElementById('ub-cam-close').onclick = fullCleanup;
    overlay.onclick = (e) => { if (e.target === overlay) fullCleanup(); };

    statusEl.textContent = 'Barkodu kameraya gösterin...';

    // 7. Decode stratejisi seç
    const hasBarcodeDetector = 'BarcodeDetector' in window;

    if (hasBarcodeDetector) {
        // ─── YOL A: Native BarcodeDetector ─────
        _scanWithNativeDetector(video, statusEl, (barcode) => {
            if (navigator.vibrate) navigator.vibrate(200);
            fullCleanup();
            onSuccess(barcode);
        }, () => scanning);
    } else {
        // ─── YOL B: Canvas + html5-qrcode decode ─────
        try {
            await ensureHtml5QrcodeLoaded();
        } catch(e) {
            statusEl.textContent = 'Barkod kütüphanesi yüklenemedi.';
            setTimeout(fullCleanup, 3000);
            return;
        }
        _scanWithCanvasDecode(video, statusEl, (barcode) => {
            if (navigator.vibrate) navigator.vibrate(200);
            fullCleanup();
            onSuccess(barcode);
        }, () => scanning);
    }
}

// ─── ANA FONKSİYON: Seri (Continuous) Okuma Modu ────────
export async function openContinuousCameraScanner(onSuccess, options = {}) {
    const headerText = options.headerText || 'Seri Barkod Okutma';
    const extraHtml = options.extraHtml || '';
    const cooldownMs = options.cooldownMs || 1500;

    await ensureMediaDevicesReady();

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

    const onVisibilityChange = () => {
        if (document.hidden && stream) {
            stream.getTracks().forEach(t => t.stop());
        }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    statusEl.textContent = 'Barkodları sırayla kameraya gösterin...';

    const handleResult = (barcode) => {
        const now = Date.now();
        if (now < cooldownUntil) return;
        if (barcode === lastScannedCode && now - cooldownUntil < 500) return;
        lastScannedCode = barcode;
        cooldownUntil = now + cooldownMs;
        if (navigator.vibrate) navigator.vibrate(150);
        onSuccess(barcode);
    };

    const hasBarcodeDetector = 'BarcodeDetector' in window;

    if (hasBarcodeDetector) {
        _scanWithNativeDetector(video, statusEl, handleResult, () => scanning);
    } else {
        try { await ensureHtml5QrcodeLoaded(); } catch(e) { cleanup(); return; }
        _scanWithCanvasDecode(video, statusEl, handleResult, () => scanning);
    }
}

// ─── YOL A: Native BarcodeDetector ile Tarama ────────────
// Chrome/Android'de ve Safari 17.2+'da çalışır.
function _scanWithNativeDetector(video, statusEl, onResult, isScanning) {
    const detector = new BarcodeDetector({ formats: BARCODE_FORMATS });
    
    const scanFrame = async () => {
        if (!isScanning() || video.readyState < 2) {
            if (isScanning()) requestAnimationFrame(scanFrame);
            return;
        }
        try {
            const barcodes = await detector.detect(video);
            if (barcodes.length > 0) {
                onResult(barcodes[0].rawValue);
                return; // Tek okuma modunda burada durur
            }
        } catch (e) {}
        if (isScanning()) requestAnimationFrame(scanFrame);
    };
    
    if (video.readyState >= 2) {
        scanFrame();
    } else {
        video.onloadedmetadata = () => scanFrame();
    }
}

// ─── YOL B: Canvas + html5-qrcode scanFile ile Tarama ───
// iOS/Safari'de kullanılır. html5-qrcode'un KAMERA YÖNETİMİ
// kullanılmıyor, sadece DECODE fonksiyonu kullanılıyor.
function _scanWithCanvasDecode(video, statusEl, onResult, isScanning) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    
    // Gizli reader div (scanFile için gerekli)
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
            // Video frame'i canvas'a çiz — TAM FRAME (crop yok)
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
            
            // Canvas → Blob → File → scanFile (yüksek kalite)
            const blob = await new Promise(resolve => 
                canvas.toBlob(resolve, 'image/jpeg', 0.92)
            );
            
            if (blob && isScanning()) {
                const file = new File([blob], 'f.jpg', { type: 'image/jpeg' });
                try {
                    const result = await decoder.scanFile(file, false);
                    if (result) {
                        // Temizlik
                        if (hiddenReader.parentNode) hiddenReader.parentNode.removeChild(hiddenReader);
                        onResult(result);
                        decoding = false;
                        return;
                    }
                } catch(e) {
                    // Bu frame'de barkod yok — devam
                }
            }
        } catch(e) {
            // Canvas/blob hatası — devam
        }
        
        decoding = false;
        if (isScanning()) setTimeout(scanFrame, 200); // ~5 FPS
    };
    
    if (video.readyState >= 2) {
        scanFrame();
    } else {
        video.onloadedmetadata = () => scanFrame();
    }
}
