/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class ShelfTransferScreen extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-truck"></i> Ürün Raf Taşıma
                </h2>
            </div>

            <!-- ADIM 1: KAYNAK RAF BARKODU -->
            <div class="ub-search-form" t-if="state.step === 1">
                <div class="ub-search-field">
                    <label class="ub-field-label">
                        <span class="ub-step-badge">1</span> Kaynak Raf Barkodu
                    </label>
                    <div class="ub-barcode-input-group">
                        <input type="text" class="form-control ub-barcode-input"
                               placeholder="Kaynak raf barkodunu okutun..."
                               t-on-keydown="onSourceShelfKey"
                               t-att-value="state.sourceShelfBarcode"
                               t-on-input="(ev) => this.state.sourceShelfBarcode = ev.target.value"/>
                        <button class="ub-scan-icon-btn" t-on-click="() => this.cameraScan('source_shelf')" title="Kamera ile tara">
                            <i class="fa fa-barcode"></i>
                        </button>
                    </div>
                </div>
                <button class="btn btn-primary ub-search-submit-btn" t-on-click="onSourceShelfConfirm">
                    <i class="fa fa-check"></i> Kaynak Raf Seç
                </button>
            </div>

            <!-- ADIM 2: HEDEF RAF BARKODU -->
            <t t-if="state.step === 2">
                <!-- Kaynak raf bilgisi -->
                <div class="ub-shelf-info-section">
                    <div class="ub-shelf-detail-row">
                        <span class="ub-shelf-detail-label">Kaynak Raf:</span>
                        <strong t-esc="state.sourceShelfInfo.complete_name || state.sourceShelfBarcode"/>
                    </div>
                    <div class="ub-shelf-detail-row" t-if="state.sourceShelfInfo.warehouse">
                        <span class="ub-shelf-detail-label">Depo:</span>
                        <span t-esc="state.sourceShelfInfo.warehouse"/>
                    </div>
                    <div class="ub-shelf-detail-row">
                        <span class="ub-shelf-detail-label">Toplam Ürün:</span>
                        <strong class="ub-stock-positive" t-esc="state.sourceShelfInfo.total_quantity || 0"/>
                    </div>
                    <button class="btn btn-sm btn-outline-secondary mt-2" t-on-click="resetAll">
                        <i class="fa fa-refresh"></i> Baştan Başla
                    </button>
                </div>

                <div class="ub-search-form">
                    <div class="ub-search-field">
                        <label class="ub-field-label">
                            <span class="ub-step-badge">2</span> Hedef Raf Barkodu
                        </label>
                        <div class="ub-barcode-input-group">
                            <input type="text" class="form-control ub-barcode-input"
                                   placeholder="Hedef raf barkodunu okutun..."
                                   t-on-keydown="onTargetShelfKey"
                                   t-att-value="state.targetShelfBarcode"
                                   t-on-input="(ev) => this.state.targetShelfBarcode = ev.target.value"/>
                            <button class="ub-scan-icon-btn" t-on-click="() => this.cameraScan('target_shelf')" title="Kamera ile tara">
                                <i class="fa fa-barcode"></i>
                            </button>
                        </div>
                    </div>
                    <button class="btn btn-primary ub-search-submit-btn" t-on-click="onTargetShelfConfirm">
                        <i class="fa fa-check"></i> Hedef Raf Seç
                    </button>
                </div>
            </t>

            <!-- ADIM 3: ÜRÜN BARKODU + ADET + NEDEN -->
            <t t-if="state.step === 3">
                <!-- Kaynak → Hedef bilgi kartı -->
                <div class="ub-transfer-info">
                    <div class="ub-transfer-info-row">
                        <span class="ub-transfer-info-label"><i class="fa fa-sign-out"></i> Kaynak:</span>
                        <span class="ub-transfer-info-value" t-esc="state.sourceShelfInfo.complete_name"/>
                    </div>
                    <div class="ub-transfer-arrow">
                        <i class="fa fa-long-arrow-down"></i>
                    </div>
                    <div class="ub-transfer-info-row">
                        <span class="ub-transfer-info-label"><i class="fa fa-sign-in"></i> Hedef:</span>
                        <span class="ub-transfer-info-value ub-target" t-esc="state.targetShelfInfo.complete_name"/>
                    </div>
                    <button class="btn btn-sm btn-outline-secondary mt-2" t-on-click="resetAll">
                        <i class="fa fa-refresh"></i> Baştan Başla
                    </button>
                </div>

                <!-- Ürün barkod tara -->
                <div class="ub-search-form">
                    <div class="ub-search-field">
                        <label class="ub-field-label">
                            <span class="ub-step-badge">3</span> Ürün Barkodu
                        </label>
                        <div class="ub-barcode-input-group">
                            <input type="text" class="form-control ub-barcode-input"
                                   placeholder="Ürün barkodunu okutun..."
                                   t-on-keydown="onProductKey"
                                   t-att-value="state.productBarcode"
                                   t-on-input="(ev) => this.state.productBarcode = ev.target.value"/>
                            <button class="ub-scan-icon-btn" t-on-click="() => this.cameraScan('product')" title="Kamera ile tara">
                                <i class="fa fa-barcode"></i>
                            </button>
                        </div>
                    </div>

                    <div class="ub-search-field">
                        <label class="ub-field-label">Adet</label>
                        <input type="number" class="form-control ub-barcode-input"
                               min="1" t-att-value="state.quantity"
                               t-on-input="(ev) => this.state.quantity = parseInt(ev.target.value) || 1"/>
                    </div>

                    <div class="ub-search-field">
                        <label class="ub-field-label">Taşıma Nedeni</label>
                        <select class="form-control ub-reason-select"
                                t-on-change="(ev) => this.state.reason = ev.target.value">
                            <option value="">Yok</option>
                            <option value="reorganize">Reorganizasyon</option>
                            <option value="demand">Talep Değişimi</option>
                            <option value="damage">Hasar</option>
                            <option value="return">İade</option>
                            <option value="season">Sezon Değişimi</option>
                            <option value="other">Diğer</option>
                        </select>
                    </div>

                    <button class="btn ub-btn-transfer ub-search-submit-btn"
                            t-on-click="doTransfer"
                            t-att-disabled="state.loading || !state.productBarcode.trim()">
                        <t t-if="state.loading">
                            <i class="fa fa-spinner fa-spin"></i> İşleniyor...
                        </t>
                        <t t-else="">
                            <i class="fa fa-exchange"></i> Taşı
                        </t>
                    </button>

                    <button class="btn btn-outline-secondary ub-search-submit-btn mt-2"
                            t-on-click="clearProduct">
                        <i class="fa fa-eraser"></i> Temizle
                    </button>
                </div>
            </t>

            <!-- HATA -->
            <div class="ub-error-card" t-if="state.error">
                <i class="fa fa-exclamation-triangle"></i>
                <p t-esc="state.error"/>
            </div>

            <!-- BAŞARI -->
            <div class="ub-transfer-success" t-if="state.success">
                <i class="fa fa-check-circle"></i>
                <p t-esc="state.success"/>
            </div>

            <!-- TRANSFER GEÇMİŞİ -->
            <div class="ub-transfer-history" t-if="state.history.length > 0">
                <div class="ub-transfer-history-header">
                    <h3>
                        <i class="fa fa-history"></i> Son Taşımalar
                    </h3>
                    <span class="badge" t-esc="state.history.length + ' işlem'"/>
                </div>
                <div class="ub-transfer-history-table-wrap">
                    <table class="ub-transfer-history-table">
                        <thead>
                            <tr>
                                <th>Ürün</th>
                                <th>Rota</th>
                                <th style="text-align:center;">Adet</th>
                            </tr>
                        </thead>
                        <tbody>
                            <t t-foreach="state.history" t-as="h" t-key="h_index">
                                <tr>
                                    <td class="ub-transfer-product-cell" t-esc="h.product_name"/>
                                    <td>
                                        <div class="ub-transfer-route-cell">
                                            <span class="ub-transfer-route-from" t-esc="h.from"/>
                                            <span class="ub-transfer-route-arrow">→</span>
                                            <span class="ub-transfer-route-to" t-esc="h.to"/>
                                        </div>
                                    </td>
                                    <td class="ub-transfer-qty-cell" t-esc="h.quantity"/>
                                </tr>
                            </t>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- LOADING -->
            <div class="ub-loading" t-if="state.loading">
                <i class="fa fa-spinner fa-spin fa-2x"></i>
                <p>İşlem yapılıyor...</p>
            </div>
        </div>
    `;

    static props = { navigate: Function, scanner: { type: Object, optional: true } };

    setup() {
        this.state = useState({
            step: 1,
            sourceShelfBarcode: '',
            targetShelfBarcode: '',
            productBarcode: '',
            quantity: 1,
            reason: '',
            sourceShelfInfo: {},
            targetShelfInfo: {},
            loading: false,
            error: null,
            success: null,
            history: [],
        });
    }

    // ═══ ADIM 1: KAYNAK RAF ═══
    onSourceShelfKey(ev) {
        if (ev.key === 'Enter') this.onSourceShelfConfirm();
    }

    async onSourceShelfConfirm() {
        const bc = this.state.sourceShelfBarcode.trim();
        if (!bc) return;

        this.state.loading = true;
        this.state.error = null;

        try {
            const res = await BarcodeService.shelfControl(bc);
            if (res.error) {
                this.state.error = res.error;
            } else {
                this.state.sourceShelfInfo = res.location;
                this.state.sourceShelfInfo.total_quantity = res.total_quantity;
                this.state.step = 2;
            }
        } catch (e) {
            this.state.error = 'Bağlantı hatası: ' + (e.message || e);
        }
        this.state.loading = false;
    }

    // ═══ ADIM 2: HEDEF RAF ═══
    onTargetShelfKey(ev) {
        if (ev.key === 'Enter') this.onTargetShelfConfirm();
    }

    async onTargetShelfConfirm() {
        const bc = this.state.targetShelfBarcode.trim();
        if (!bc) return;

        if (bc === this.state.sourceShelfBarcode.trim()) {
            this.state.error = 'Kaynak ve hedef raf aynı olamaz!';
            return;
        }

        this.state.loading = true;
        this.state.error = null;

        try {
            const res = await BarcodeService.shelfControl(bc);
            if (res.error) {
                this.state.error = res.error;
            } else {
                this.state.targetShelfInfo = res.location;
                this.state.step = 3;
            }
        } catch (e) {
            this.state.error = 'Bağlantı hatası: ' + (e.message || e);
        }
        this.state.loading = false;
    }

    // ═══ ADIM 3: TAŞIMA ═══
    onProductKey(ev) {
        if (ev.key === 'Enter') this.doTransfer();
    }

    async doTransfer() {
        const productBarcode = this.state.productBarcode.trim();
        if (!productBarcode) return;

        this.state.loading = true;
        this.state.error = null;
        this.state.success = null;

        try {
            const res = await BarcodeService.shelfTransfer(
                productBarcode,
                this.state.sourceShelfBarcode.trim(),
                this.state.targetShelfBarcode.trim(),
                this.state.quantity,
                this.state.reason
            );

            if (res.error) {
                this.state.error = res.error;
            } else {
                this.state.success = res.message;
                this.state.history.unshift({
                    product_name: res.product_name,
                    from: this.state.sourceShelfInfo.complete_name,
                    to: this.state.targetShelfInfo.complete_name,
                    quantity: this.state.quantity,
                });
                // Formu temizle ama rafları koru (tekrar taşıma için)
                this.state.productBarcode = '';
                this.state.quantity = 1;
                this.state.reason = '';

                // 3 saniye sonra success mesajını kaldır
                setTimeout(() => { this.state.success = null; }, 3000);
            }
        } catch (e) {
            this.state.error = 'Bağlantı hatası: ' + (e.message || e);
        }
        this.state.loading = false;
    }

    clearProduct() {
        this.state.productBarcode = '';
        this.state.quantity = 1;
        this.state.reason = '';
        this.state.error = null;
        this.state.success = null;
    }

    resetAll() {
        Object.assign(this.state, {
            step: 1,
            sourceShelfBarcode: '',
            targetShelfBarcode: '',
            productBarcode: '',
            quantity: 1,
            reason: '',
            sourceShelfInfo: {},
            targetShelfInfo: {},
            error: null,
            success: null,
        });
    }

    // ═══ KAMERA TARAMA (iOS + Android) ═══
    async cameraScan(target) {
        const useNative = 'BarcodeDetector' in window;
        if (!useNative && !window.Html5Qrcode) {
            try {
                await new Promise((resolve, reject) => {
                    const s = document.createElement('script');
                    s.src = 'https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js';
                    s.onload = resolve;
                    s.onerror = () => reject(new Error('Kütüphane yüklenemedi'));
                    document.head.appendChild(s);
                });
            } catch (e) {
                alert('Barkod tarayıcı yüklenemedi.');
                return;
            }
        }

        const overlay = document.createElement('div');
        overlay.className = 'ub-camera-overlay';
        overlay.innerHTML = `
            <div class="ub-camera-header">
                <span>Barkod Okutma</span>
                <button class="ub-camera-close-btn" id="ub-cam-close">✕ Kapat</button>
            </div>
            ${useNative ? '<video id="ub-cam-video" autoplay playsinline muted></video>' : '<div id="ub-cam-reader" style="width:100%;"></div>'}
            <div class="ub-camera-target"></div>
            <div class="ub-camera-status" id="ub-cam-status">Kamera başlatılıyor...</div>
        `;
        document.body.appendChild(overlay);

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

        const onScanSuccess = (barcode) => {
            if (navigator.vibrate) navigator.vibrate(200);
            cleanup();
            if (target === 'source_shelf') {
                this.state.sourceShelfBarcode = barcode;
                this.onSourceShelfConfirm();
            } else if (target === 'target_shelf') {
                this.state.targetShelfBarcode = barcode;
                this.onTargetShelfConfirm();
            } else if (target === 'product') {
                this.state.productBarcode = barcode;
            }
        };

        document.getElementById('ub-cam-close').onclick = cleanup;
        overlay.onclick = (e) => { if (e.target === overlay) cleanup(); };

        if (useNative) {
            const video = document.getElementById('ub-cam-video');
            navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
            }).then(s => {
                stream = s;
                video.srcObject = stream;
                statusEl.textContent = 'Barkodu kameraya gösterin...';
                const detector = new BarcodeDetector({
                    formats: ['ean_13', 'ean_8', 'code_128', 'code_39', 'upc_a', 'upc_e', 'itf', 'qr_code']
                });
                const scanFrame = async () => {
                    if (!scanning || video.readyState < 2) { animFrame = requestAnimationFrame(scanFrame); return; }
                    try {
                        const barcodes = await detector.detect(video);
                        if (barcodes.length > 0) { onScanSuccess(barcodes[0].rawValue); return; }
                    } catch (e) {}
                    animFrame = requestAnimationFrame(scanFrame);
                };
                video.onloadedmetadata = () => scanFrame();
            }).catch(err => {
                statusEl.textContent = 'Kamera erişimi reddedildi: ' + err.message;
                setTimeout(cleanup, 3000);
            });
        } else {
            try {
                html5QrCode = new Html5Qrcode('ub-cam-reader');
                statusEl.textContent = 'Barkodu kameraya gösterin...';
                html5QrCode.start(
                    { facingMode: 'environment' },
                    { fps: 10, qrbox: { width: 280, height: 120 }, aspectRatio: 1.777 },
                    (decodedText) => onScanSuccess(decodedText),
                    () => {}
                ).catch(err => {
                    statusEl.textContent = 'Kamera başlatılamadı: ' + err;
                    setTimeout(cleanup, 3000);
                });
            } catch (err) {
                statusEl.textContent = 'Tarayıcı hatası: ' + err.message;
                setTimeout(cleanup, 3000);
            }
        }
    }

    willUnmount() {}
}
