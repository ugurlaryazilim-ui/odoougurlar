/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class ShelfMoveAll extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title"><i class="fa fa-truck"></i> Tüm Rafı Taşı</h2>
            </div>

            <!-- UYARI BANNER -->
            <div class="ub-shelf-move-warning">
                <i class="fa fa-exclamation-triangle"></i>
                <span>Dikkat! Raftaki <b>tüm ürünler</b> yeni rafa taşınacaktır.</span>
            </div>

            <!-- HATA -->
            <t t-if="state.error">
                <div class="ub-result-card ub-result-danger" style="margin:0 1.5rem">
                    <i class="fa fa-times-circle"></i> <t t-esc="state.error"/>
                </div>
            </t>

            <!-- SONUÇ GÖSTERİLMEDİĞİNDE FORM -->
            <t t-if="!state.result">

                <!-- ADIM 1: KAYNAK RAF -->
                <div class="ub-search-form">
                    <div class="ub-search-field">
                        <label class="ub-field-label">
                            <span class="ub-step-badge">1</span> Kaynak Raf Barkodu
                        </label>
                        <div class="ub-barcode-input-group">
                            <input type="text" class="form-control ub-barcode-input"
                                   placeholder="Kaynak raf barkodunu okutun..."
                                   t-att-value="state.sourceBarcode"
                                   t-on-input="(ev) => this.state.sourceBarcode = ev.target.value"
                                   t-on-keydown="(e) => e.key === 'Enter' &amp;&amp; this.loadSourceShelf()"/>
                            <button class="ub-scan-icon-btn" t-on-click="() => this.scanCamera('source')" title="Kamera ile tara">
                                <i class="fa fa-barcode"></i>
                            </button>
                        </div>
                    </div>
                    <t t-if="!state.sourceInfo">
                        <button class="btn btn-primary ub-search-submit-btn" t-on-click="loadSourceShelf">
                            <i class="fa fa-search"></i> Raf Bul
                        </button>
                    </t>
                </div>

                <!-- KAYNAK RAF BİLGİSİ -->
                <t t-if="state.sourceInfo">
                    <div class="ub-shelf-info-section">
                        <div class="ub-shelf-detail-row">
                            <span class="ub-shelf-detail-label">Kaynak Raf:</span>
                            <strong t-esc="state.sourceInfo.complete_name"/>
                        </div>
                        <div class="ub-shelf-detail-row">
                            <span class="ub-shelf-detail-label">Ürün Çeşidi:</span>
                            <strong class="ub-stock-positive" t-esc="state.sourceProducts.length"/>
                        </div>
                        <div class="ub-shelf-detail-row">
                            <span class="ub-shelf-detail-label">Toplam Adet:</span>
                            <strong class="ub-stock-positive" t-esc="state.totalQty"/>
                        </div>
                        <button class="btn btn-sm btn-outline-secondary mt-2" t-on-click="resetForm">
                            <i class="fa fa-refresh"></i> Baştan Başla
                        </button>
                    </div>

                    <!-- Ürün Listesi Ön İzleme -->
                    <t t-if="state.sourceProducts.length > 0">
                        <div class="ub-shelf-move-preview">
                            <div class="ub-shelf-move-preview-header">
                                <h3><i class="fa fa-cubes"></i> Taşınacak Ürünler</h3>
                                <span class="badge"><t t-esc="state.sourceProducts.length"/> ürün</span>
                            </div>
                            <table class="ub-shelf-move-preview-table">
                                <thead>
                                    <tr>
                                        <th>ÜRÜN</th>
                                        <th>BARKOD</th>
                                        <th style="text-align:center">ADET</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <t t-foreach="state.sourceProducts" t-as="p" t-key="p.product_id">
                                        <tr>
                                            <td class="ub-shelf-move-product" t-att-title="p.product_name"><t t-esc="p.product_name"/></td>
                                            <td><t t-esc="p.barcode || '-'"/></td>
                                            <td class="ub-shelf-move-qty"><t t-esc="p.quantity"/></td>
                                        </tr>
                                    </t>
                                </tbody>
                            </table>
                        </div>
                    </t>
                    <t t-else="">
                        <div class="ub-result-card ub-result-warning" style="margin:0 1.5rem">
                            <i class="fa fa-info-circle"></i> Bu rafta ürün yok.
                        </div>
                    </t>

                    <!-- ADIM 2: HEDEF RAF -->
                    <t t-if="state.sourceProducts.length > 0">
                        <div class="ub-search-form">
                            <div class="ub-search-field">
                                <label class="ub-field-label">
                                    <span class="ub-step-badge">2</span> Hedef Raf Barkodu
                                </label>
                                <div class="ub-barcode-input-group">
                                    <input type="text" class="form-control ub-barcode-input"
                                           placeholder="Hedef raf barkodunu okutun..."
                                           t-att-value="state.targetBarcode"
                                           t-on-input="(ev) => this.state.targetBarcode = ev.target.value"
                                           t-on-keydown="(e) => e.key === 'Enter' &amp;&amp; this.loadTargetShelf()"/>
                                    <button class="ub-scan-icon-btn" t-on-click="() => this.scanCamera('target')" title="Kamera ile tara">
                                        <i class="fa fa-barcode"></i>
                                    </button>
                                </div>
                            </div>
                            <t t-if="!state.targetInfo">
                                <button class="btn btn-primary ub-search-submit-btn" t-on-click="loadTargetShelf">
                                    <i class="fa fa-search"></i> Hedef Raf Bul
                                </button>
                            </t>
                        </div>

                        <!-- HEDEF RAF SEÇİLDİ -->
                        <t t-if="state.targetInfo">
                            <div class="ub-transfer-info">
                                <div class="ub-transfer-info-row">
                                    <span class="ub-transfer-info-label"><i class="fa fa-sign-out"></i> Kaynak:</span>
                                    <span class="ub-transfer-info-value" t-esc="state.sourceInfo.complete_name"/>
                                </div>
                                <div class="ub-transfer-arrow">
                                    <i class="fa fa-long-arrow-down"></i>
                                </div>
                                <div class="ub-transfer-info-row">
                                    <span class="ub-transfer-info-label"><i class="fa fa-sign-in"></i> Hedef:</span>
                                    <span class="ub-transfer-info-value ub-target" t-esc="state.targetInfo.complete_name"/>
                                </div>
                            </div>

                            <!-- ADIM 3: NEDEN + TAŞI -->
                            <div class="ub-search-form">
                                <div class="ub-search-field">
                                    <label class="ub-field-label">
                                        <span class="ub-step-badge">3</span> Taşıma Nedeni
                                    </label>
                                    <select class="form-control ub-barcode-input" t-model="state.reason">
                                        <option value="">Yok</option>
                                        <option value="reorganize">Reorganizasyon</option>
                                        <option value="demand">Talep Değişimi</option>
                                        <option value="damage">Hasar</option>
                                        <option value="return">İade</option>
                                        <option value="season">Sezon Değişimi</option>
                                        <option value="other">Diğer</option>
                                    </select>
                                </div>
                                <button class="btn ub-search-submit-btn ub-btn-shelf-move" t-on-click="doMoveAll"
                                        t-att-disabled="state.loading">
                                    <t t-if="state.loading">
                                        <i class="fa fa-spinner fa-spin"></i> Taşınıyor...
                                    </t>
                                    <t t-else="">
                                        <i class="fa fa-truck"></i> Tüm Rafı Taşı (<t t-esc="state.sourceProducts.length"/> ürün, <t t-esc="state.totalQty"/> adet)
                                    </t>
                                </button>
                            </div>
                        </t>
                    </t>
                </t>
            </t>

            <!-- SONUÇ -->
            <t t-if="state.result">
                <div class="ub-result-card ub-result-success" style="margin:0 1.5rem;text-align:center;padding:2rem">
                    <div style="font-size:2.5rem;margin-bottom:0.5rem"><i class="fa fa-check-circle"></i></div>
                    <div style="font-size:1.1rem;font-weight:700;margin-bottom:1rem">Taşıma Tamamlandı!</div>
                    <div style="display:flex;justify-content:center;gap:2rem;margin-bottom:1rem">
                        <div style="text-align:center">
                            <div style="font-size:1.8rem;font-weight:700;color:#27AE60"><t t-esc="state.result.moved_count"/></div>
                            <div style="font-size:0.75rem;color:#666;text-transform:uppercase">Ürün Çeşidi</div>
                        </div>
                        <div style="text-align:center">
                            <div style="font-size:1.8rem;font-weight:700;color:#27AE60"><t t-esc="state.result.total_quantity"/></div>
                            <div style="font-size:0.75rem;color:#666;text-transform:uppercase">Toplam Adet</div>
                        </div>
                    </div>
                </div>
                <div class="ub-transfer-info" style="margin-top:1rem">
                    <div class="ub-transfer-info-row">
                        <span class="ub-transfer-info-label"><i class="fa fa-sign-out"></i> Kaynak:</span>
                        <span class="ub-transfer-info-value" t-esc="state.result.source"/>
                    </div>
                    <div class="ub-transfer-arrow">
                        <i class="fa fa-long-arrow-down"></i>
                    </div>
                    <div class="ub-transfer-info-row">
                        <span class="ub-transfer-info-label"><i class="fa fa-sign-in"></i> Hedef:</span>
                        <span class="ub-transfer-info-value ub-target" t-esc="state.result.target"/>
                    </div>
                </div>
                <div class="ub-search-form">
                    <button class="btn btn-primary ub-search-submit-btn" t-on-click="resetForm">
                        <i class="fa fa-refresh"></i> Yeni Taşıma
                    </button>
                </div>
            </t>
        </div>
    `;

    setup() {
        this.state = useState({
            sourceBarcode: '',
            targetBarcode: '',
            sourceInfo: null,
            targetInfo: null,
            sourceProducts: [],
            totalQty: 0,
            reason: '',
            error: null,
            loading: false,
            result: null,
        });
    }

    async loadSourceShelf() {
        this.state.error = null;
        this.state.sourceInfo = null;
        this.state.sourceProducts = [];
        this.state.totalQty = 0;
        this.state.targetInfo = null;

        const bc = this.state.sourceBarcode.trim();
        if (!bc) { this.state.error = 'Kaynak raf barkodu gerekli'; return; }

        try {
            const res = await BarcodeService.shelfControl(bc);
            if (res.error) { this.state.error = res.error; return; }
            this.state.sourceInfo = res;
            const products = (res.products || []).filter(p => p.quantity > 0);
            this.state.sourceProducts = products;
            this.state.totalQty = products.reduce((s, p) => s + p.quantity, 0);
        } catch (e) {
            this.state.error = 'Bağlantı hatası: ' + (e.message || e);
        }
    }

    async loadTargetShelf() {
        this.state.error = null;
        this.state.targetInfo = null;

        const bc = this.state.targetBarcode.trim();
        if (!bc) { this.state.error = 'Hedef raf barkodu gerekli'; return; }

        if (bc === this.state.sourceBarcode.trim()) {
            this.state.error = 'Kaynak ve hedef raf aynı olamaz!';
            return;
        }

        try {
            const res = await BarcodeService.shelfControl(bc);
            if (res.error) { this.state.error = res.error; return; }
            this.state.targetInfo = res;
        } catch (e) {
            this.state.error = 'Bağlantı hatası: ' + (e.message || e);
        }
    }

    async doMoveAll() {
        this.state.error = null;
        this.state.loading = true;

        try {
            const res = await BarcodeService.shelfMoveAll(
                this.state.sourceBarcode.trim(),
                this.state.targetBarcode.trim(),
                this.state.reason
            );

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
            sourceBarcode: '',
            targetBarcode: '',
            sourceInfo: null,
            targetInfo: null,
            sourceProducts: [],
            totalQty: 0,
            reason: '',
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

        const onDetected = (code) => {
            if (target === 'source') {
                this.state.sourceBarcode = code;
                this.loadSourceShelf();
            } else {
                this.state.targetBarcode = code;
                this.loadTargetShelf();
            }
        };

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
                        if (barcodes.length > 0) {
                            stream.getTracks().forEach(t => t.stop());
                            overlay.remove();
                            onDetected(barcodes[0].rawValue);
                            return;
                        }
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
