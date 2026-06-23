/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class ScanScreen extends Component {
    static template = "ugurlar_ai_studio.ScanScreen";
    static props = {
        dashboardStats: { type: Object },
        onProductFound: { type: Function },
        onGoToHistory: { type: Function },
        onGoToBatchReview: { type: Function },
    };

    setup() {
        this.notification = useService("notification");

        this.state = useState({
            query: "",
            searching: false,
            results: [],
            showResults: false,
        });
    }

    async _jsonRpc(url, params = {}) {
        const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ jsonrpc: "2.0", method: "call", params }),
        });
        const data = await response.json();
        if (data.error) {
            throw new Error(data.error.data?.message || data.error.message || "RPC Error");
        }
        return data.result;
    }

    async onInputChange(ev) {
        this.state.query = ev.target.value;
    }

    async onKeyDown(ev) {
        if (ev.key === "Enter") {
            await this.searchProduct();
        }
    }

    async searchProduct() {
        const query = this.state.query.trim();
        if (!query) return;

        this.state.searching = true;
        this.state.showResults = false;

        try {
            const res = await this._jsonRpc("/ai_studio/find_product", { query });
            if (res.found && res.products.length === 1) {
                this.props.onProductFound(res.products[0]);
            } else if (res.found && res.products.length > 1) {
                this.state.results = res.products;
                this.state.showResults = true;
            } else {
                this.notification.add(_t("Urun bulunamadi."), { type: "warning" });
            }
        } catch (e) {
            this.notification.add(_t("Arama hatasi."), { type: "danger" });
        } finally {
            this.state.searching = false;
        }
    }

    selectProduct(product) {
        this.props.onProductFound(product);
    }

    clearSearch() {
        this.state.query = "";
        this.state.results = [];
        this.state.showResults = false;
    }

    /**
     * Kamera ile barkod okuma — ugurlar_barcode modulu ile ayni pattern.
     * Chrome/Android'de native BarcodeDetector API kullanir.
     */
    startCameraScan() {
        if (!('BarcodeDetector' in window)) {
            alert('Bu tarayici kamera ile barkod okumayi desteklemiyor.\nChrome (Android) veya Edge kullanin.');
            return;
        }
        const overlay = document.createElement('div');
        overlay.className = 'ub-camera-overlay';
        overlay.innerHTML = `
            <div class="ub-camera-header">
                <span>Barkodu kameraya gosterin...</span>
                <button class="ub-camera-close-btn" id="ais-cam-close">&#10005;</button>
            </div>
            <video id="ais-cam-video" autoplay playsinline muted></video>
            <div class="ub-camera-target"></div>
            <div class="ub-camera-status" id="ais-cam-status">Kamera baslatiliyor...</div>
        `;
        document.body.appendChild(overlay);
        const video = document.getElementById('ais-cam-video');
        const statusEl = document.getElementById('ais-cam-status');
        let stream = null, animFrame = null, scanning = true;

        const cleanup = () => {
            scanning = false;
            if (animFrame) cancelAnimationFrame(animFrame);
            if (stream) stream.getTracks().forEach(t => t.stop());
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        };

        document.getElementById('ais-cam-close').onclick = cleanup;
        overlay.onclick = (e) => { if (e.target === overlay) cleanup(); };

        navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
        }).then(s => {
            stream = s;
            video.srcObject = stream;
            statusEl.textContent = 'Barkodu kameraya gosterin...';
            const detector = new BarcodeDetector({
                formats: ['ean_13', 'ean_8', 'code_128', 'code_39', 'upc_a', 'upc_e', 'itf', 'qr_code']
            });
            const scanFrame = async () => {
                if (!scanning || video.readyState < 2) {
                    animFrame = requestAnimationFrame(scanFrame);
                    return;
                }
                try {
                    const barcodes = await detector.detect(video);
                    if (barcodes.length > 0) {
                        if (navigator.vibrate) navigator.vibrate(200);
                        cleanup();
                        // Okunan barkodu arama kutusuna yaz ve ara
                        this.state.query = barcodes[0].rawValue;
                        await this.searchProduct();
                        return;
                    }
                } catch (e) {}
                animFrame = requestAnimationFrame(scanFrame);
            };
            video.onloadedmetadata = () => scanFrame();
        }).catch(err => {
            statusEl.textContent = 'Kamera erisimi reddedildi: ' + err.message;
            setTimeout(cleanup, 3000);
        });
    }
}
