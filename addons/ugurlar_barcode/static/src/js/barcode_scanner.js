/** @odoo-module **/

/**
 * Barkod Tarama Servisi
 * Kamera + El Terminali (keyboard wedge) + Manuel giriş desteği
 */
export class BarcodeScanner {
    constructor() {
        this._buffer = '';
        this._lastKeyTime = 0;
        this._listeners = [];
        this._keyHandler = this._onKeyDown.bind(this);
        this._isActive = false;
        this._isScanning = false; // Mükerrer okutma kilidi
    }

    /**
     * Tarayıcıyı başlat (keyboard wedge dinlemeye başla)
     */
    start() {
        if (this._isActive) return;
        document.addEventListener('keydown', this._keyHandler, true);
        this._isActive = true;
    }

    /**
     * Tarayıcıyı durdur
     */
    stop() {
        document.removeEventListener('keydown', this._keyHandler, true);
        this._isActive = false;
        this._buffer = '';
    }

    /**
     * Barkod algılandığında çağrılacak callback ekle
     */
    onScan(callback) {
        this._listeners.push(callback);
        return () => {
            this._listeners = this._listeners.filter(cb => cb !== callback);
        };
    }

    /**
     * El terminali keyboard wedge handler
     * Hızlı ardışık tuş basımlarını algılar + Enter ile tamamlar
     */
    _onKeyDown(ev) {
        // Eğer bir input/textarea'da yazıyorsa ve barcode-input değilse atla
        const tag = ev.target.tagName;
        const isBarcodeInput = ev.target.classList.contains('ub-barcode-input');
        if ((tag === 'INPUT' || tag === 'TEXTAREA') && !isBarcodeInput) {
            return;
        }

        const now = Date.now();
        const timeDiff = now - this._lastKeyTime;

        // 200ms'den uzun süre geçtiyse buffer sıfırla (elle yazım)
        if (timeDiff > 200) {
            this._buffer = '';
        }
        this._lastKeyTime = now;

        if (ev.key === 'Enter') {
            if (this._buffer.length >= 3) {
                // Hızlı giriş algılandı (terminal/okuyucu) → emit et
                ev.preventDefault();
                ev.stopPropagation();
                this._emit(this._buffer.trim());
            }
            // Barkod input alanında Enter → stock_search.js onKeyDown'a bırak
            this._buffer = '';
            return;
        }

        // Kontrol tuşlarını yoksay
        if (ev.key.length === 1 && !ev.ctrlKey && !ev.altKey && !ev.metaKey) {
            this._buffer += ev.key;
            // Eğer input alanında değilse tuşu yut
            if (!isBarcodeInput) {
                ev.preventDefault();
                ev.stopPropagation();
            }
        }
    }

    /**
     * Manuel barkod girişi (input alanından)
     */
    manualScan(barcode) {
        if (barcode && barcode.trim().length >= 1) {
            this._emit(barcode.trim());
        }
    }

    async _emit(barcode) {
        if (this._isScanning) {
            console.warn("Scanner locked, ignoring double scan:", barcode);
            return;
        }
        
        this._isScanning = true;
        try {
            for (const cb of this._listeners) {
                try { 
                    const res = cb(barcode); 
                    if (res instanceof Promise) {
                        await res;
                    }
                } catch (e) { console.error(e); }
            }
        } finally {
            // Küçük bir bekleme süresi koyarak art arda (spagetti) tuş basımlarını engelle
            setTimeout(() => {
                this._isScanning = false;
            }, 150);
        }
    }
}
