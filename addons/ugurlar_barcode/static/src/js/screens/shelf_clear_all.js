/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class ShelfClearAllScreen extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title"><i class="fa fa-trash-o"></i> Toplu Raf Silme</h2>
            </div>

            <!-- UYARI -->
            <div class="ub-shelf-clear-warning">
                <i class="fa fa-exclamation-triangle"></i>
                <span>Dikkat! Raftaki <b>tüm ürünler</b> kaldırılacaktır.</span>
            </div>

            <!-- HATA -->
            <t t-if="state.error">
                <div class="ub-result-card ub-result-danger" style="margin:0 1.5rem">
                    <i class="fa fa-times-circle"></i> <t t-esc="state.error"/>
                </div>
            </t>

            <!-- SONUÇ GÖSTERİLMEDİĞİNDE -->
            <t t-if="!state.result">

                <!-- ADIM 1: RAF BARKODU -->
                <t t-if="!state.shelfInfo">
                    <div class="ub-search-form">
                        <div class="ub-search-field">
                            <label class="ub-field-label">
                                <span class="ub-step-badge">1</span> Raf Barkodu
                            </label>
                            <div class="ub-barcode-input-group">
                                <input type="text" class="form-control ub-barcode-input"
                                       placeholder="Raf barkodunu okutun..."
                                       t-att-value="state.shelfBarcode"
                                       t-on-input="(ev) => this.state.shelfBarcode = ev.target.value"
                                       t-on-keydown="(e) => e.key === 'Enter' &amp;&amp; this.loadShelf()"/>
                                <button class="ub-scan-icon-btn" t-on-click="() => this.scanCamera('shelf')" title="Kamera ile tara">
                                    <i class="fa fa-barcode"></i>
                                </button>
                            </div>
                        </div>
                        <button class="btn btn-primary ub-search-submit-btn" t-on-click="loadShelf">
                            <i class="fa fa-search"></i> Raf Bul
                        </button>
                    </div>
                </t>

                <!-- RAF SEÇİLDİ -->
                <t t-if="state.shelfInfo">
                    <div class="ub-shelf-info-section">
                        <div class="ub-shelf-detail-row">
                            <span class="ub-shelf-detail-label">Raf:</span>
                            <strong t-esc="state.shelfInfo.name"/>
                        </div>
                        <div class="ub-shelf-detail-row">
                            <span class="ub-shelf-detail-label">Raf Yolu:</span>
                            <span t-esc="state.shelfInfo.complete_name"/>
                        </div>
                        <div class="ub-shelf-detail-row">
                            <span class="ub-shelf-detail-label">Ürün Çeşidi:</span>
                            <strong style="color:#e74c3c" t-esc="state.products.length"/>
                        </div>
                        <div class="ub-shelf-detail-row">
                            <span class="ub-shelf-detail-label">Toplam Adet:</span>
                            <strong style="color:#e74c3c" t-esc="state.totalQty"/>
                        </div>
                        <button class="btn btn-sm btn-outline-secondary mt-2" t-on-click="resetForm">
                            <i class="fa fa-refresh"></i> Başka Raf Seç
                        </button>
                    </div>

                    <!-- ÜRÜN LİSTESİ -->
                    <t t-if="state.products.length > 0">
                        <div class="ub-shelf-clear-preview">
                            <div class="ub-shelf-clear-preview-header">
                                <h3><i class="fa fa-trash-o"></i> Silinecek Ürünler</h3>
                                <span class="badge"><t t-esc="state.products.length"/> ürün</span>
                            </div>
                            <table class="ub-shelf-clear-table">
                                <thead>
                                    <tr>
                                        <th>KOD</th>
                                        <th>ÜRÜN</th>
                                        <th>BARKOD</th>
                                        <th style="text-align:center">ADET</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <t t-foreach="state.products" t-as="p" t-key="p.id">
                                        <tr>
                                            <td><t t-esc="p.code || '-'"/></td>
                                            <td class="ub-shelf-clear-product" t-att-title="p.name"><t t-esc="p.name"/></td>
                                            <td><t t-esc="p.barcode || '-'"/></td>
                                            <td class="ub-shelf-clear-qty"><t t-esc="p.quantity"/></td>
                                        </tr>
                                    </t>
                                </tbody>
                            </table>
                        </div>

                        <div class="ub-search-form">
                            <button class="btn ub-search-submit-btn ub-btn-shelf-clear w-100" t-on-click="doClearAll"
                                    t-att-disabled="state.loading">
                                <t t-if="state.loading">
                                    <i class="fa fa-spinner fa-spin"></i> Siliniyor...
                                </t>
                                <t t-else="">
                                    <i class="fa fa-trash-o"></i> Tüm Ürünleri Kaldır (<t t-esc="state.products.length"/> ürün, <t t-esc="state.totalQty"/> adet)
                                </t>
                            </button>
                        </div>
                    </t>
                    <t t-else="">
                        <div class="ub-result-card ub-result-warning" style="margin:0 1.5rem">
                            <i class="fa fa-info-circle"></i> Bu rafta ürün yok.
                        </div>
                    </t>
                </t>
            </t>

            <!-- SONUÇ -->
            <t t-if="state.result">
                <div class="ub-shelf-clear-result">
                    <div class="ub-shelf-clear-result-header">
                        <i class="fa fa-check-circle"></i>
                        <h3>Raf Temizlendi!</h3>
                    </div>
                    <div class="ub-shelf-clear-result-stats">
                        <div class="ub-shelf-clear-stat">
                            <div class="ub-shelf-clear-stat-value"><t t-esc="state.result.cleared_count"/></div>
                            <div class="ub-shelf-clear-stat-label">Ürün Çeşidi</div>
                        </div>
                        <div class="ub-shelf-clear-stat">
                            <div class="ub-shelf-clear-stat-value"><t t-esc="state.result.total_quantity"/></div>
                            <div class="ub-shelf-clear-stat-label">Toplam Adet</div>
                        </div>
                    </div>
                </div>
                <div class="ub-search-form">
                    <button class="btn btn-primary ub-search-submit-btn" t-on-click="resetForm">
                        <i class="fa fa-refresh"></i> Yeni İşlem
                    </button>
                </div>
            </t>
        </div>
    `;

    setup() {
        this.state = useState({
            shelfBarcode: '',
            shelfInfo: null,
            products: [],
            totalQty: 0,
            error: null,
            loading: false,
            result: null,
        });
    }

    async loadShelf() {
        this.state.error = null;
        this.state.shelfInfo = null;
        this.state.products = [];
        this.state.totalQty = 0;

        const bc = this.state.shelfBarcode.trim();
        if (!bc) { this.state.error = 'Raf barkodu gerekli'; return; }

        try {
            const res = await BarcodeService.shelfControl(bc);
            if (res.error) { this.state.error = res.error; return; }

            this.state.shelfInfo = res.location;
            const products = (res.products || []).filter(p => p.quantity > 0);
            this.state.products = products;
            this.state.totalQty = products.reduce((s, p) => s + p.quantity, 0);
        } catch (e) {
            this.state.error = 'Bağlantı hatası: ' + (e.message || e);
        }
    }

    async doClearAll() {
        this.state.error = null;
        this.state.loading = true;

        try {
            const res = await BarcodeService.shelfClearAll(this.state.shelfBarcode.trim());
            if (res.error) {
                this.state.error = res.error;
            } else {
                this.state.result = res;
            }
        } catch (e) {
            this.state.error = 'Bağlantı hatası: ' + (e.message || e);
        }
        this.state.loading = false;
    }

    resetForm() {
        Object.assign(this.state, {
            shelfBarcode: '',
            shelfInfo: null,
            products: [],
            totalQty: 0,
            error: null,
            loading: false,
            result: null,
        });
    }

    async scanCamera(target) {
        const overlay = document.createElement('div');
        overlay.className = 'ub-camera-overlay';
        overlay.innerHTML = `
            <div class="ub-camera-controls">
                <button class="ub-camera-close">&times;</button>
                <div id="ub-camera-reader" style="width:100%"></div>
                <div class="ub-camera-status">Raf barkodunu kameraya gösterin...</div>
            </div>
        `;
        document.body.appendChild(overlay);
        overlay.querySelector('.ub-camera-close').onclick = () => { overlay.remove(); };
        const readerEl = overlay.querySelector('#ub-camera-reader');
        const statusEl = overlay.querySelector('.ub-camera-status');
        const onDetected = (code) => { this.state.shelfBarcode = code; this.loadShelf(); };
        const useBarcodeDetector = ('BarcodeDetector' in window) && !/iPhone|iPad|iPod/i.test(navigator.userAgent);

        if (useBarcodeDetector) {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
                const video = document.createElement('video');
                video.srcObject = stream;
                video.setAttribute('playsinline', 'true');
                video.setAttribute('autoplay', 'true');
                video.muted = true;
                video.style.width = '100%';
                video.style.borderRadius = '8px';
                readerEl.appendChild(video);
                await video.play();
                const detector = new BarcodeDetector({ formats: ['ean_13', 'ean_8', 'code_128', 'code_39', 'qr_code'] });
                const scan = async () => {
                    if (!document.body.contains(overlay)) { stream.getTracks().forEach(t => t.stop()); return; }
                    try {
                        const barcodes = await detector.detect(video);
                        if (barcodes.length > 0) { stream.getTracks().forEach(t => t.stop()); overlay.remove(); onDetected(barcodes[0].rawValue); return; }
                    } catch (e) {}
                    requestAnimationFrame(scan);
                };
                scan();
            } catch (e) { statusEl.textContent = 'Kamera erişim hatası'; }
        } else {
            try {
                if (!window.Html5Qrcode) {
                    statusEl.textContent = 'Tarayıcı yükleniyor...';
                    const s = document.createElement('script');
                    s.src = 'https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js';
                    document.head.appendChild(s);
                    await new Promise((r, j) => { s.onload = r; s.onerror = () => j(new Error('CDN')); setTimeout(() => j(new Error('Timeout')), 10000); });
                }
                statusEl.textContent = 'Kamera başlatılıyor...';
                const scanner = new Html5Qrcode('ub-camera-reader');
                const config = { fps: 10, qrbox: { width: 250, height: 150 }, aspectRatio: 1.0 };
                const successCb = (code) => { scanner.stop().catch(() => {}); overlay.remove(); onDetected(code); };
                await scanner.start({ facingMode: 'environment' }, config, successCb, () => {});
                overlay.querySelector('.ub-camera-close').onclick = () => { scanner.stop().catch(() => {}); overlay.remove(); };
            } catch (e) {
                console.error('Html5Qrcode hatası:', e);
                statusEl.textContent = 'Kamera başlatılamadı: ' + (e.message || e);
            }
        }
    }
}
