/** @odoo-module **/

/**
 * Terzi Barkod Tarama Servisi
 * Kaynak: ugurlar_barcode/barcode_scanner.js ile ayni mantik
 * Kamera + El Terminali (keyboard wedge) + Manuel giris destegi
 */
// Bekleyen okutma ust siniri (dinleyici yavassa dizi kuyrugu bu kadar tutar)
const MAX_QUEUE = 100;

export class TailorBarcodeScanner {
    constructor() {
        this._buffer = '';
        this._lastKeyTime = 0;
        this._listeners = [];
        this._keyHandler = this._onKeyDown.bind(this);
        this._isActive = false;
        this._queue = [];
        this._draining = false;
    }

    start() {
        if (this._isActive) return;
        document.addEventListener('keydown', this._keyHandler, true);
        this._isActive = true;
    }

    stop() {
        document.removeEventListener('keydown', this._keyHandler, true);
        this._isActive = false;
        this._buffer = '';
        // Ekran kapanirken bekleyen okutmalar yeni ekrana tasinmasin
        this._queue = [];
    }

    onScan(callback) {
        this._listeners.push(callback);
        return () => {
            this._listeners = this._listeners.filter(cb => cb !== callback);
        };
    }

    _onKeyDown(ev) {
        const tag = ev.target.tagName;
        const isBarcodeInput = ev.target.classList.contains('tailor-barcode-input');
        if ((tag === 'INPUT' || tag === 'TEXTAREA') && !isBarcodeInput) {
            return;
        }

        const now = Date.now();
        const timeDiff = now - this._lastKeyTime;

        if (timeDiff > 200) {
            this._buffer = '';
        }
        this._lastKeyTime = now;

        if (ev.key === 'Enter') {
            if (this._buffer.length >= 3) {
                ev.preventDefault();
                ev.stopPropagation();
                this._emit(this._buffer.trim());
            }
            this._buffer = '';
            return;
        }

        if (ev.key.length === 1 && !ev.ctrlKey && !ev.altKey && !ev.metaKey) {
            this._buffer += ev.key;
            if (!isBarcodeInput) {
                ev.preventDefault();
                ev.stopPropagation();
            }
        }
    }

    manualScan(barcode) {
        if (barcode && barcode.trim().length >= 1) {
            this._emit(barcode.trim());
        }
    }

    /**
     * Okutmayi kuyruga alir; onceki okutma suruyorsa kaybolmaz, sirayla islenir.
     * Kuyruk dolarsa (MAX_QUEUE) yeni okutma atilir ve uyari yazilir.
     */
    _emit(barcode) {
        if (this._queue.length >= MAX_QUEUE) {
            console.warn('TailorBarcodeScanner: okutma kuyrugu dolu, okutma atildi:', barcode);
            return;
        }
        this._queue.push(barcode);
        if (!this._draining) {
            this._drain();
        }
    }

    async _drain() {
        this._draining = true;
        try {
            while (this._queue.length) {
                const barcode = this._queue.shift();
                // Dinleyici listesi her okutmada guncel alinir (ekran degisince abonelik iptali)
                for (const cb of [...this._listeners]) {
                    try {
                        await cb(barcode);
                    } catch (e) { console.error(e); }
                }
            }
        } finally {
            this._draining = false;
        }
    }
}
