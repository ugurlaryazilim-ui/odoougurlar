/** @odoo-module **/

/**
 * Merkezi Kamera Barkod Tarayıcı Modülü
 * 
 * Tüm ekranlarda kullanılan kamera barkod okutma fonksiyonelliğini
 * tek bir yerde toplar. iOS/Safari, PWA ve Android/Chrome uyumluluğunu sağlar.
 * 
 * iOS Sorunları ve Çözümleri:
 * - BarcodeDetector API iOS'ta YOK → html5-qrcode fallback
 * - PWA modunda navigator.mediaDevices undefined olabiliyor → file input fallback
 * - In-app browser'larda (WhatsApp, Instagram vb.) kamera API yok → file input fallback
 * - facingMode: 'environment' ultra-wide kamerayı seçebilir → getCameras() ile ana kamera seçimi
 * - aspectRatio iOS'ta sorun çıkarır → kaldırıldı
 * - Yüksek FPS iOS'ta frame drop yapar → 8 FPS
 */

// ─── iOS Algılama ─────────────────────────────────────────
function isIOS() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

// ─── Kamera API Desteği Kontrolü ──────────────────────────
function canUseCamera() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
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

// ─── Fotoğraf Çekerek Barkod Okuma Overlay'i (iOS PWA Fallback) ────
function createFileInputOverlay(headerText, onSuccess, isContinuous) {
    const overlay = document.createElement('div');
    overlay.className = 'ub-camera-overlay';
    
    // Gizli reader div (scanFile için gerekli)
    const readerDiv = document.createElement('div');
    readerDiv.id = 'ub-cam-reader-hidden';
    readerDiv.style.display = 'none';
    document.body.appendChild(readerDiv);
    
    overlay.innerHTML = `
        <div class="ub-camera-header">
            <span>${headerText || 'Barkod Okutma'}</span>
            <button class="ub-camera-close-btn" id="ub-cam-close">✕ Kapat</button>
        </div>
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:30px 20px;gap:20px;flex:1;">
            <div style="background:rgba(255,255,255,0.08);border-radius:16px;padding:30px;text-align:center;max-width:340px;width:100%;">
                <div style="font-size:48px;margin-bottom:16px;">📷</div>
                <p style="color:#fff;font-size:15px;margin-bottom:8px;font-weight:600;">
                    Kamera Modu Kullanılamıyor
                </p>
                <p style="color:rgba(255,255,255,0.6);font-size:13px;margin-bottom:24px;line-height:1.5;">
                    Bu tarayıcıda canlı kamera desteği yok.<br>
                    Barkodun fotoğrafını çekerek okutabilirsiniz.
                </p>
                <label for="ub-file-input" style="display:inline-flex;align-items:center;gap:8px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;padding:14px 28px;border-radius:12px;font-size:15px;font-weight:600;cursor:pointer;box-shadow:0 4px 15px rgba(99,102,241,0.4);transition:transform 0.15s ease;">
                    <i class="fa fa-camera" style="font-size:18px;"></i>
                    Fotoğraf Çek
                </label>
                <input type="file" id="ub-file-input" accept="image/*" capture="environment" 
                       style="position:absolute;left:-9999px;opacity:0;">
            </div>
            <div id="ub-file-status" style="color:rgba(255,255,255,0.7);font-size:13px;text-align:center;min-height:20px;"></div>
            ${isContinuous ? `
            <div id="ub-file-count" style="background:rgba(255,255,255,0.1);padding:10px 20px;border-radius:10px;color:#fff;font-size:14px;">
                Okunan: <strong id="ub-file-scan-count">0</strong> barkod
            </div>` : ''}
        </div>
    `;
    document.body.appendChild(overlay);

    let scanCount = 0;
    const statusEl = overlay.querySelector('#ub-file-status');

    const cleanup = () => {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        if (readerDiv.parentNode) readerDiv.parentNode.removeChild(readerDiv);
    };

    overlay.querySelector('#ub-cam-close').onclick = cleanup;

    const fileInput = overlay.querySelector('#ub-file-input');
    fileInput.addEventListener('change', async (e) => {
        if (e.target.files.length === 0) return;
        const imageFile = e.target.files[0];
        statusEl.textContent = 'Barkod okunuyor...';
        statusEl.style.color = 'rgba(255,255,255,0.7)';

        try {
            await ensureHtml5QrcodeLoaded();
            const html5QrCode = new Html5Qrcode('ub-cam-reader-hidden');
            const decodedText = await html5QrCode.scanFile(imageFile, /* showImage= */ false);
            
            if (navigator.vibrate) navigator.vibrate(200);
            statusEl.textContent = '✅ Barkod bulundu: ' + decodedText;
            statusEl.style.color = '#4ade80';
            
            scanCount++;
            const countEl = overlay.querySelector('#ub-file-scan-count');
            if (countEl) countEl.textContent = scanCount;

            onSuccess(decodedText);

            if (!isContinuous) {
                setTimeout(cleanup, 500);
            } else {
                // Sürekli modda input'u sıfırla — tekrar fotoğraf çekilebilsin
                fileInput.value = '';
                setTimeout(() => {
                    statusEl.textContent = 'Başka bir barkod okutmak için tekrar fotoğraf çekin.';
                    statusEl.style.color = 'rgba(255,255,255,0.7)';
                }, 2000);
            }
        } catch (err) {
            console.error('Fotoğraftan barkod okunamadı:', err);
            statusEl.textContent = '❌ Barkod bulunamadı. Lütfen tekrar deneyin.';
            statusEl.style.color = '#f87171';
            // Input'u sıfırla — tekrar denenebilsin
            fileInput.value = '';
        }
    });

    return overlay;
}

// ─── BARKOD FORMATLARI ───────────────────────────────────
const BARCODE_FORMATS_NATIVE = ['ean_13', 'ean_8', 'code_128', 'code_39', 'upc_a', 'upc_e', 'itf', 'qr_code'];

// ─── ANA FONKSİYON: Tek Okuma Modu ──────────────────────
/**
 * Kamerayı açıp tek bir barkod okur ve callback ile döner.
 * Okuma başarılı olunca kamerayı kapatır.
 * 
 * iOS PWA veya in-app browser'da kamera API yoksa,
 * otomatik olarak "fotoğraf çek" moduna düşer.
 * 
 * @param {Function} onSuccess - (barcode: string) => void
 * @param {Object} [options]
 * @param {string} [options.headerText] - Overlay başlık metni
 */
export async function openCameraScanner(onSuccess, options = {}) {
    const headerText = options.headerText || 'Barkod Okutma';

    // ─── ADIM 1: Kamera API kontrolü ─────────────────
    if (!canUseCamera()) {
        console.warn('navigator.mediaDevices yok — fotoğraf fallback gösteriliyor');
        createFileInputOverlay(headerText, onSuccess, false);
        return;
    }

    const useNative = 'BarcodeDetector' in window;

    // html5-qrcode yükle (iOS/Safari için)
    if (!useNative) {
        try {
            await ensureHtml5QrcodeLoaded();
        } catch (e) {
            // CDN yüklenemedi — fotoğraf fallback'e düş
            createFileInputOverlay(headerText, onSuccess, false);
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

    // ─── Kamera başlatma başarısız olursa fotoğraf fallback'e düş ───
    const fallbackToFileInput = () => {
        cleanup();
        createFileInputOverlay(headerText, onSuccess, false);
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
        try {
            html5QrCode = await _startHtml5QrcodeScanner(
                statusEl, handleScanResult, cleanup, headerText
            );
            // html5QrCode null ise tüm denemeler başarısız olmuştur
            if (!html5QrCode) {
                fallbackToFileInput();
            }
        } catch (err) {
            console.error('html5-qrcode başlatma hatası:', err);
            fallbackToFileInput();
        }
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
    const headerText = options.headerText || 'Seri Barkod Okutma';
    const extraHtml = options.extraHtml || '';
    const cooldownMs = options.cooldownMs || 1500;

    // ─── ADIM 1: Kamera API kontrolü ─────────────────
    if (!canUseCamera()) {
        console.warn('navigator.mediaDevices yok — fotoğraf fallback gösteriliyor');
        createFileInputOverlay(headerText, onSuccess, true);
        return;
    }

    const useNative = 'BarcodeDetector' in window;

    if (!useNative) {
        try {
            await ensureHtml5QrcodeLoaded();
        } catch (e) {
            createFileInputOverlay(headerText, onSuccess, true);
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

    const fallbackToFileInput = () => {
        cleanup();
        createFileInputOverlay(headerText, onSuccess, true);
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
                fallbackToFileInput();
            }
        } catch (err) {
            console.error('html5-qrcode başlatma hatası:', err);
            fallbackToFileInput();
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

// ─── html5-qrcode (iOS/Safari) — İkisi İçin Ortak ──────
async function _startHtml5QrcodeScanner(statusEl, onScanResult, cleanup, headerText) {
    // Güvenlik kontrolü — html5-qrcode başlatılmadan önce API var mı?
    if (!canUseCamera()) {
        console.warn('_startHtml5QrcodeScanner: navigator.mediaDevices yok');
        return null;
    }

    const html5QrCode = new Html5Qrcode('ub-cam-reader');
    statusEl.textContent = headerText || 'Barkodu kameraya gösterin...';

    // Kamera ayarları
    const config = {
        fps: 8,
        qrbox: { width: 280, height: 150 },
        // aspectRatio kaldırıldı — iOS'ta sorun çıkarıyor
    };

    // ─── STRATEJI ─────────────────────────────────────
    // iOS'ta getCameras() izin almadan çalışmaz.
    // Bu yüzden önce facingMode ile başlatıyoruz (izin alıyor),
    // sonra arka planda daha iyi kamerayı bulup geçiş yapıyoruz.

    let started = false;

    // Deneme 1: facingMode: 'environment' (en güvenli)
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

    // Deneme 3: Kamera listesinden seç (izin artık alınmış olmalı)
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

    // Deneme 4: Herhangi bir kamera (son çare)
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
            console.error('Kamera başlatma tamamen başarısız:', err4);
            // null döndür — çağıran fonksiyon file input fallback'e düşecek
            return null;
        }
    }

    // İzin artık alındı — arka planda daha iyi kameraya geçmeyi dene
    if (started && isIOS()) {
        setTimeout(async () => {
            try {
                const bestId = await getBestBackCameraId();
                if (bestId) {
                    // Mevcut kameranın ID'sini al
                    const runningCameraId = html5QrCode.getRunningTrackCameraCapabilities &&
                        html5QrCode.getRunningTrackSettings &&
                        html5QrCode.getRunningTrackSettings().deviceId;
                    
                    // Eğer farklı bir kamera bulduysak, geçiş yap
                    if (runningCameraId && runningCameraId !== bestId) {
                        await html5QrCode.stop();
                        await html5QrCode.start(
                            bestId,
                            config,
                            (decodedText) => onScanResult(decodedText),
                            () => {}
                        );
                        console.info('iOS: Ana arka kameraya geçildi:', bestId);
                    }
                }
            } catch (e) {
                // Geçiş başarısız — mevcut kamerada devam et
                console.warn('iOS kamera geçişi başarısız (sorun yok, mevcut devam ediyor):', e);
            }
        }, 1500);
    }

    return html5QrCode;
}
