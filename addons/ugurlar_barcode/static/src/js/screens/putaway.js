/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class PutawayScreen extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-arrow-down"></i> Raflama
                </h2>
                <div class="ub-mode-toggle">
                    <button t-attf-class="btn btn-sm {{state.mode === 'putaway' ? 'ub-mode-active-green' : 'btn-outline-secondary'}}"
                            t-on-click="() => this.setMode('putaway')">
                        <i class="fa fa-arrow-down"></i> Rafla
                    </button>
                    <button t-attf-class="btn btn-sm {{state.mode === 'remove' ? 'ub-mode-active-red' : 'btn-outline-secondary'}}"
                            t-on-click="() => this.setMode('remove')">
                        <i class="fa fa-arrow-up"></i> Kaldır
                    </button>
                </div>
            </div>

            <!-- ADIM 1: RAF BARKODU -->
            <div class="ub-search-form" t-if="state.step === 1">
                <div class="ub-search-field">
                    <label class="ub-field-label">
                        <span class="ub-step-badge">1</span> Raf Barkodu
                    </label>
                    <div class="ub-barcode-input-group">
                        <input type="text" class="form-control ub-barcode-input"
                               placeholder="Raf barkodunu okutun..."
                               t-on-keydown="onShelfKey"
                               t-att-value="state.shelfBarcode"
                               t-on-input="(ev) => this.onShelfInput(ev)"/>
                        <button class="ub-scan-icon-btn" t-on-click="() => this.cameraScan('shelf')" title="Kamera ile tara">
                            <i class="fa fa-barcode"></i>
                        </button>
                    </div>
                </div>
                <button class="btn btn-primary ub-search-submit-btn" t-on-click="onShelfConfirm">
                    <i class="fa fa-check"></i> Raf Seç
                </button>
            </div>

            <!-- ADIM 2: ÜRÜN BARKODU + RAF BİLGİSİ -->
            <t t-if="state.step === 2">
                <!-- Seçilen raf bilgisi -->
                <div class="ub-shelf-info-section">
                    <div class="ub-shelf-detail-row">
                        <span class="ub-shelf-detail-label">Raf Yolu:</span>
                        <strong t-esc="state.shelfInfo.complete_name || state.shelfBarcode"/>
                    </div>
                    <div class="ub-shelf-detail-row" t-if="state.shelfInfo.warehouse">
                        <span class="ub-shelf-detail-label">Depo:</span>
                        <span t-esc="state.shelfInfo.warehouse"/>
                    </div>
                    <div class="ub-shelf-detail-row">
                        <span class="ub-shelf-detail-label">Toplam Adet:</span>
                        <strong class="ub-stock-positive" t-esc="state.shelfInfo.total_quantity || 0"/>
                    </div>
                    <button class="btn btn-sm btn-outline-secondary mt-2" t-on-click="changeShelf">
                        <i class="fa fa-refresh"></i> Raf Değiştir
                    </button>
                </div>

                <!-- Ürün barkod tara -->
                <div class="ub-search-form">
                    <div class="ub-search-field">
                        <label class="ub-field-label">
                            <span class="ub-step-badge">2</span> Ürün Barkodu
                        </label>
                        <div class="ub-barcode-input-group">
                            <input type="text" class="form-control ub-barcode-input"
                                   placeholder="Ürün barkodunu okutun..."
                                   t-on-keydown="onProductKey"
                                   t-att-value="state.productBarcode"
                                   t-on-input="(ev) => this.onProductInput(ev)"/>
                            <button class="ub-scan-icon-btn" t-on-click="() => this.cameraScan('product')" title="Kamera ile tara">
                                <i class="fa fa-barcode"></i>
                            </button>
                        </div>
                    </div>
                    <div class="ub-qty-section">
                        <label class="ub-field-label">Adet</label>
                        <input type="number" class="form-control ub-qty-input-wide"
                               t-att-value="state.quantity" min="1"
                               t-on-input="(ev) => this.state.quantity = parseInt(ev.target.value) || 1"/>
                    </div>
                    <button t-attf-class="btn ub-search-submit-btn {{state.mode === 'putaway' ? 'ub-action-putaway' : 'ub-action-remove'}}"
                            t-on-click="onExecute">
                        <i t-attf-class="fa {{state.mode === 'putaway' ? 'fa-arrow-down' : 'fa-arrow-up'}}"></i>
                        <t t-if="state.mode === 'putaway'"> Rafla</t>
                        <t t-else=""> Raftan Kaldır</t>
                    </button>
                </div>

                <!-- Raftaki ürünler tablosu -->
                <t t-if="state.shelfProducts.length">
                    <div class="ub-variants-section">
                        <div class="ub-section-title-dark" style="display:flex; justify-content:space-between; align-items:center;">
                            <span><i class="fa fa-cubes"></i> Raftaki Ürünler</span>
                            <span class="ub-table-summary">
                                <t t-esc="state.shelfProducts.length"/> ürün
                            </span>
                        </div>
                        <div class="ub-variant-table-wrap">
                            <table class="ub-variant-table ub-variant-table-striped">
                                <thead>
                                    <tr>
                                        <th>Kod</th>
                                        <th>Adı</th>
                                        <th>Barkod</th>
                                        <th class="text-end">Adet</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <t t-foreach="state.shelfProducts" t-as="p" t-key="p.id">
                                        <tr>
                                            <td t-esc="p.code || '-'"/>
                                            <td><strong t-esc="p.name"/></td>
                                            <td class="ub-barcode-cell" t-esc="p.barcode || '-'"/>
                                            <td class="text-end">
                                                <span class="ub-stock-positive" t-esc="p.quantity"/>
                                            </td>
                                        </tr>
                                    </t>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </t>
            </t>

            <t t-if="state.loading">
                <div class="ub-loading"><i class="fa fa-spinner fa-spin fa-2x"></i><p>İşleniyor...</p></div>
            </t>

            <t t-if="state.error">
                <div class="ub-error-card"><i class="fa fa-exclamation-triangle"></i><p t-esc="state.error"/></div>
            </t>

            <t t-if="state.success">
                <div class="ub-success-card">
                    <i class="fa fa-check-circle"></i>
                    <p t-esc="state.success"/>
                    <button class="btn btn-primary mt-2" t-on-click="resetProduct">
                        <i class="fa fa-plus"></i> Yeni Ürün Okut
                    </button>
                </div>
            </t>

            <!-- SON İŞLEMLER -->
            <div class="ub-variants-section" t-if="state.history.length" style="margin-top:0.5rem;">
                <div class="ub-section-title-dark">
                    <i class="fa fa-history"></i> Son İşlemler
                </div>
                <div class="ub-variant-table-wrap">
                    <table class="ub-variant-table ub-variant-table-striped">
                        <thead>
                            <tr>
                                <th>İşlem</th>
                                <th>Detay</th>
                            </tr>
                        </thead>
                        <tbody>
                            <t t-foreach="state.history" t-as="h" t-key="h.time">
                                <tr>
                                    <td>
                                        <i t-attf-class="fa {{h.type === 'putaway' ? 'fa-arrow-down' : 'fa-arrow-up'}}"
                                           t-attf-style="color: {{h.type === 'putaway' ? '#27ae60' : '#e74c3c'}}"></i>
                                        <t t-if="h.type === 'putaway'"> Raflama</t>
                                        <t t-else=""> Kaldırma</t>
                                    </td>
                                    <td t-esc="h.message"/>
                                </tr>
                            </t>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;

    static props = { navigate: Function, scanner: Object };

    setup() {
        this.state = useState({
            mode: 'putaway',
            step: 1,
            shelfBarcode: '',
            shelfInfo: {},
            shelfProducts: [],
            productBarcode: '',
            quantity: 1,
            loading: false,
            error: null,
            success: null,
            history: [],
        });
        this._unsub = this.props.scanner.onScan(bc => this.onScanDetected(bc));
    }

    setMode(mode) {
        this.state.mode = mode;
        this.state.error = null;
        this.state.success = null;
    }

    onScanDetected(bc) {
        if (this.state.step === 1) {
            this.state.shelfBarcode = bc;
            this.onShelfConfirm();
        } else if (this.state.step === 2) {
            this.state.productBarcode = bc;
            this.onExecute();
        }
    }

    // ─── ADIM 1: RAF TARA ─────────────────────────
    onShelfInput(ev) {
        this.state.shelfBarcode = ev.target.value;
        this._detectScan(ev.target.value, 'shelf');
    }

    onShelfKey(ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); this.onShelfConfirm(); }
    }

    async onShelfConfirm() {
        if (!this.state.shelfBarcode.trim()) return;
        this.state.loading = true;
        this.state.error = null;
        try {
            const result = await BarcodeService.shelfControl(this.state.shelfBarcode.trim());
            if (result.error) {
                this.state.error = result.error;
            } else {
                this.state.shelfInfo = {
                    ...result.location,
                    total_quantity: result.total_quantity,
                };
                this.state.shelfProducts = result.products || [];
                this.state.step = 2;
            }
        } catch (e) {
            this.state.error = 'Bağlantı hatası: ' + (e.message || e);
        }
        this.state.loading = false;
    }

    changeShelf() {
        this.state.step = 1;
        this.state.shelfBarcode = '';
        this.state.shelfInfo = {};
        this.state.shelfProducts = [];
        this.state.productBarcode = '';
        this.state.error = null;
        this.state.success = null;
    }

    // ─── ADIM 2: ÜRÜN TARA + İŞLEM ───────────────
    onProductInput(ev) {
        this.state.productBarcode = ev.target.value;
        this._detectScan(ev.target.value, 'product');
    }

    onProductKey(ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); this.onExecute(); }
    }

    async onExecute() {
        if (!this.state.productBarcode.trim()) return;
        this.state.loading = true;
        this.state.error = null;
        this.state.success = null;
        try {
            const fn = this.state.mode === 'putaway'
                ? BarcodeService.putaway(this.state.productBarcode.trim(), this.state.shelfBarcode.trim(), this.state.quantity)
                : BarcodeService.removeFromShelf(this.state.productBarcode.trim(), this.state.shelfBarcode.trim(), this.state.quantity);
            const res = await fn;
            if (res.error) {
                this.state.error = res.error;
            } else {
                this.state.success = res.message;
                this.state.history.unshift({ type: this.state.mode, message: res.message, time: Date.now() });
                if (this.state.history.length > 10) this.state.history.pop();
                // Raf bilgisini güncelle
                this._refreshShelf();
            }
        } catch (e) {
            this.state.error = 'Hata: ' + (e.message || e);
        }
        this.state.loading = false;
    }

    async _refreshShelf() {
        try {
            const result = await BarcodeService.shelfControl(this.state.shelfBarcode.trim());
            if (!result.error) {
                this.state.shelfInfo.total_quantity = result.total_quantity;
                this.state.shelfProducts = result.products || [];
            }
        } catch (e) {}
    }

    resetProduct() {
        this.state.productBarcode = '';
        this.state.quantity = 1;
        this.state.error = null;
        this.state.success = null;
    }

    // ─── AUTO-SCAN DETECTION ──────────────────────
    _detectScan(val, target) {
        const now = Date.now();
        const key = '_rapid_' + target;
        if (this[key + '_time'] && (now - this[key + '_time']) < 80) {
            this[key + '_count'] = (this[key + '_count'] || 0) + 1;
        } else {
            this[key + '_count'] = 0;
        }
        this[key + '_time'] = now;
        if (this[key + '_timer']) clearTimeout(this[key + '_timer']);
        if (this[key + '_count'] >= 6 && val.trim().length >= 4) {
            this[key + '_timer'] = setTimeout(() => {
                if (target === 'shelf') this.onShelfConfirm();
                else this.onExecute();
            }, 300);
        }
    }

    // ─── KAMERA TARAYICI ──────────────────────────
    cameraScan(target) {
        if (!('BarcodeDetector' in window)) {
            alert('Bu tarayıcı kamera ile barkod okumayı desteklemiyor.\nChrome (Android) veya Edge kullanın.');
            return;
        }
        const overlay = document.createElement('div');
        overlay.className = 'ub-camera-overlay';
        overlay.innerHTML = `
            <div class="ub-camera-header">
                <span>${target === 'shelf' ? 'Raf' : 'Ürün'} barkodunu gösterin...</span>
                <button class="ub-camera-close-btn" id="ub-cam-close">✕</button>
            </div>
            <video id="ub-cam-video" autoplay playsinline muted></video>
            <div class="ub-camera-target"></div>
            <div class="ub-camera-status" id="ub-cam-status">Kamera başlatılıyor...</div>
        `;
        document.body.appendChild(overlay);
        const video = document.getElementById('ub-cam-video');
        const statusEl = document.getElementById('ub-cam-status');
        let stream = null, animFrame = null, scanning = true;
        const cleanup = () => {
            scanning = false;
            if (animFrame) cancelAnimationFrame(animFrame);
            if (stream) stream.getTracks().forEach(t => t.stop());
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        };
        document.getElementById('ub-cam-close').onclick = cleanup;
        overlay.onclick = (e) => { if (e.target === overlay) cleanup(); };
        navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
        }).then(s => {
            stream = s; video.srcObject = stream;
            statusEl.textContent = `${target === 'shelf' ? 'Raf' : 'Ürün'} barkodunu kameraya gösterin...`;
            const detector = new BarcodeDetector({
                formats: ['ean_13', 'ean_8', 'code_128', 'code_39', 'upc_a', 'upc_e', 'itf', 'qr_code']
            });
            const scanFrame = async () => {
                if (!scanning || video.readyState < 2) { animFrame = requestAnimationFrame(scanFrame); return; }
                try {
                    const barcodes = await detector.detect(video);
                    if (barcodes.length > 0) {
                        if (navigator.vibrate) navigator.vibrate(200);
                        cleanup();
                        if (target === 'shelf') {
                            this.state.shelfBarcode = barcodes[0].rawValue;
                            this.onShelfConfirm();
                        } else {
                            this.state.productBarcode = barcodes[0].rawValue;
                            this.onExecute();
                        }
                        return;
                    }
                } catch (e) {}
                animFrame = requestAnimationFrame(scanFrame);
            };
            video.onloadedmetadata = () => scanFrame();
        }).catch(err => {
            statusEl.textContent = 'Kamera erişimi reddedildi: ' + err.message;
            setTimeout(cleanup, 3000);
        });
    }

    willUnmount() {
        if (this._unsub) this._unsub();
    }
}
