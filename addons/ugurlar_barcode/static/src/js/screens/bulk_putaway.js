/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class BulkPutawayScreen extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title"><i class="fa fa-cubes"></i> Toplu Ürün Raflama</h2>
            </div>

            <!-- HATA -->
            <t t-if="state.error">
                <div class="ub-result-card ub-result-danger" style="margin:0 1.5rem">
                    <i class="fa fa-times-circle"></i> <t t-esc="state.error"/>
                </div>
            </t>

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
                        <i class="fa fa-check"></i> Raf Seç
                    </button>
                </div>
            </t>

            <!-- ADIM 2: ÜRÜN TARAMA EKRANI -->
            <t t-if="state.shelfInfo">

                <!-- RAF BİLGİ KARTI -->
                <div class="ub-shelf-info-section">
                    <div class="ub-shelf-detail-row">
                        <span class="ub-shelf-detail-label">Raf:</span>
                        <strong t-esc="state.shelfInfo.name"/>
                    </div>
                    <div class="ub-shelf-detail-row">
                        <span class="ub-shelf-detail-label">Raf Yolu:</span>
                        <span t-esc="state.shelfInfo.complete_name"/>
                    </div>
                    <button class="btn btn-sm btn-outline-secondary mt-2" t-on-click="resetForm">
                        <i class="fa fa-refresh"></i> Başka Raf Seç
                    </button>
                </div>

                <!-- SON İŞLEM TOAST -->
                <t t-if="state.lastSuccess">
                    <div class="ub-bulk-putaway-toast">
                        <i class="fa fa-check-circle"></i>
                        <span><t t-esc="state.lastSuccess"/></span>
                    </div>
                </t>

                <!-- OTURUM STATS -->
                <div class="ub-bulk-putaway-stats">
                    <div class="ub-bulk-putaway-stat">
                        <div class="ub-bulk-putaway-stat-value"><t t-esc="state.sessionItems.length"/></div>
                        <div class="ub-bulk-putaway-stat-label">Ürün Çeşidi</div>
                    </div>
                    <div class="ub-bulk-putaway-stat">
                        <div class="ub-bulk-putaway-stat-value"><t t-esc="state.totalPutaway"/></div>
                        <div class="ub-bulk-putaway-stat-label">Toplam Adet</div>
                    </div>
                </div>

                <!-- ÜRÜN BARKOD OKUT -->
                <div class="ub-search-form">
                    <div class="ub-search-field">
                        <label class="ub-field-label">Adet</label>
                        <input type="number" class="form-control ub-barcode-input"
                               min="1" t-att-value="state.quantity"
                               t-on-input="onQtyInput"
                               style="text-align:center;font-size:1.1rem;font-weight:700"/>
                    </div>
                    <div class="ub-search-field">
                        <label class="ub-field-label">
                            <span class="ub-step-badge">2</span> Ürün Barkodu
                        </label>
                        <div class="ub-barcode-input-group">
                            <input type="text" class="form-control ub-barcode-input"
                                   placeholder="Ürün barkodunu okutun..."
                                   t-att-value="state.productBarcode"
                                   t-on-input="(ev) => this.state.productBarcode = ev.target.value"
                                   t-on-keydown="onProductKey"/>
                            <button class="ub-scan-icon-btn" t-on-click="() => this.scanCamera('product')" title="Kamera ile tara">
                                <i class="fa fa-barcode"></i>
                            </button>
                        </div>
                    </div>
                </div>

                <!-- RAF İÇERİĞİ + OTURUM TABLOSU -->
                <t t-if="state.shelfProducts.length > 0 || state.sessionItems.length > 0">
                    <div class="ub-bulk-putaway-table-wrap">
                        <div class="ub-bulk-putaway-table-header">
                            <h3><i class="fa fa-th-list"></i> Raftaki Ürünler</h3>
                            <span class="badge"><t t-esc="state.shelfProducts.length"/> ürün</span>
                        </div>
                        <table class="ub-bulk-putaway-table">
                            <thead>
                                <tr>
                                    <th>KOD</th>
                                    <th>ÜRÜN</th>
                                    <th>BARKOD</th>
                                    <th style="text-align:center">ADET</th>
                                </tr>
                            </thead>
                            <tbody>
                                <t t-foreach="state.shelfProducts" t-as="p" t-key="p.id">
                                    <tr t-attf-class="{{ p.justAdded ? 'ub-just-added' : '' }}">
                                        <td><t t-esc="p.code || '-'"/></td>
                                        <td class="ub-bulk-putaway-product" t-att-title="p.name"><t t-esc="p.name"/></td>
                                        <td><t t-esc="p.barcode || '-'"/></td>
                                        <td class="ub-bulk-putaway-qty"><t t-esc="p.quantity"/></td>
                                    </tr>
                                </t>
                            </tbody>
                        </table>
                    </div>
                </t>
            </t>
        </div>
    `;

    setup() {
        this.state = useState({
            shelfBarcode: '',
            shelfInfo: null,
            shelfProducts: [],
            quantity: 1,
            productBarcode: '',
            sessionItems: [],
            totalPutaway: 0,
            lastSuccess: null,
            error: null,
            loading: false,
        });
    }

    onQtyInput(ev) {
        const val = Number(ev.target.value);
        this.state.quantity = val > 0 ? val : 1;
    }

    async loadShelf() {
        this.state.error = null;
        this.state.shelfInfo = null;
        this.state.shelfProducts = [];

        const bc = this.state.shelfBarcode.trim();
        if (!bc) { this.state.error = 'Raf barkodu gerekli'; return; }

        try {
            const res = await BarcodeService.shelfControl(bc);
            if (res.error) { this.state.error = res.error; return; }

            this.state.shelfInfo = res.location;
            this.state.shelfProducts = (res.products || []).filter(p => p.quantity > 0).map(p => ({
                ...p,
                justAdded: false,
            }));
        } catch (e) {
            this.state.error = 'Bağlantı hatası: ' + (e.message || e);
        }
    }

    onProductKey(ev) {
        if (ev.key === 'Enter') {
            this.doPutaway();
        }
    }

    async doPutaway() {
        const bc = this.state.productBarcode.trim();
        if (!bc || this.state.loading) return;

        this.state.error = null;
        this.state.lastSuccess = null;
        this.state.loading = true;

        try {
            const res = await BarcodeService.putaway(bc, this.state.shelfBarcode.trim(), this.state.quantity);

            if (res.error) {
                this.state.error = res.error;
            } else {
                // Başarılı — toast mesajı
                this.state.lastSuccess = `${res.product_name}: ${this.state.quantity} adet raflandı`;

                // Oturum geçmişine ekle
                this.state.sessionItems.unshift({
                    barcode: bc,
                    product_name: res.product_name,
                    quantity: this.state.quantity,
                    time: new Date().toLocaleTimeString('tr-TR', {hour:'2-digit', minute:'2-digit'}),
                });
                this.state.totalPutaway += this.state.quantity;

                // Raf stok listesini güncelle
                await this._refreshShelf();

                // Titreşim feedback
                if (navigator.vibrate) navigator.vibrate(100);
            }
        } catch (e) {
            this.state.error = 'Bağlantı hatası: ' + (e.message || e);
        }

        this.state.productBarcode = '';
        this.state.loading = false;
    }

    async _refreshShelf() {
        try {
            const res = await BarcodeService.shelfControl(this.state.shelfBarcode.trim());
            if (!res.error) {
                // Son eklenen ürünü bul ve vurgula
                const lastBarcode = this.state.sessionItems.length > 0 ? this.state.sessionItems[0].barcode : '';
                this.state.shelfProducts = (res.products || []).filter(p => p.quantity > 0).map(p => ({
                    ...p,
                    justAdded: p.barcode === lastBarcode,
                }));
            }
        } catch (e) {}
    }

    resetForm() {
        Object.assign(this.state, {
            shelfBarcode: '',
            shelfInfo: null,
            shelfProducts: [],
            productBarcode: '',
            sessionItems: [],
            totalPutaway: 0,
            lastSuccess: null,
            error: null,
            loading: false,
        });
    }

    async scanCamera(target) {
        const overlay = document.createElement('div');
        overlay.className = 'ub-camera-overlay';
        overlay.innerHTML = `
            <div class="ub-camera-controls">
                <button class="ub-camera-close">&times;</button>
                <div id="ub-camera-reader" style="width:100%"></div>
                <div class="ub-camera-status">${target === 'shelf' ? 'Raf' : 'Ürün'} barkodunu kameraya gösterin...</div>
            </div>
        `;
        document.body.appendChild(overlay);
        overlay.querySelector('.ub-camera-close').onclick = () => { overlay.remove(); };
        const readerEl = overlay.querySelector('#ub-camera-reader');
        const statusEl = overlay.querySelector('.ub-camera-status');
        const onDetected = (code) => {
            if (target === 'shelf') { this.state.shelfBarcode = code; this.loadShelf(); }
            else { this.state.productBarcode = code; this.doPutaway(); }
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
