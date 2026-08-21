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
     * Barkod callback kaldır
     */
    offScan(callback) {
        this._listeners = this._listeners.filter(cb => cb !== callback);
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
                const barcode = this._buffer.trim();
                this._buffer = '';
                // Input alanını temizle — scanner tarafından yazılan çöp
                if (isBarcodeInput) {
                    ev.target.value = '';
                }
                this._emit(barcode);
                return;
            }
            // Barkod input alanında Enter → stock_search.js onKeyDown'a bırak
            this._buffer = '';
            return;
        }

        // Kontrol tuşlarını yoksay
        if (ev.key.length === 1 && !ev.ctrlKey && !ev.altKey && !ev.metaKey) {
            this._buffer += ev.key;
            // Hızlı tuş basımı (scanner) → input'a yazma, sadece buffer'a ekle
            if (!isBarcodeInput || timeDiff < 200) {
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

    _emit(barcode) {
        // Senkron emit — callback'leri beklemeden çağır
        // Bu sayede _isScanning kilidi sonraki barkodları bloklamaz
        for (const cb of this._listeners) {
            try {
                cb(barcode);
            } catch (e) { console.error(e); }
        }
    }
}
