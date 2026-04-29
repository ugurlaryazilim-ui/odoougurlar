/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class ShelfValidateScreen extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title"><i class="fa fa-check-square-o"></i> Raf Ürün Doğrulama</h2>
            </div>

            <!-- HATA -->
            <t t-if="state.error">
                <div class="ub-result-card ub-result-danger" style="margin:0 1.5rem">
                    <i class="fa fa-times-circle"></i> <t t-esc="state.error"/>
                </div>
            </t>

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

            <!-- ADIM 2: DOĞRULAMA EKRANI -->
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

                <!-- STATS -->
                <div class="ub-validate-stats">
                    <div class="ub-validate-stat">
                        <div class="ub-validate-stat-value"><t t-esc="state.products.length"/></div>
                        <div class="ub-validate-stat-label">Toplam Ürün</div>
                    </div>
                    <div class="ub-validate-stat">
                        <div class="ub-validate-stat-value ub-stat-done"><t t-esc="state.validatedCount"/></div>
                        <div class="ub-validate-stat-label">Sayılan</div>
                    </div>
                    <div class="ub-validate-stat">
                        <div class="ub-validate-stat-value ub-stat-remain"><t t-esc="state.products.length - state.validatedCount"/></div>
                        <div class="ub-validate-stat-label">Kalan</div>
                    </div>
                </div>

                <!-- İLERLEME BARI -->
                <div class="ub-validate-progress">
                    <div class="ub-validate-progress-bar" t-attf-style="width: {{ state.products.length ? Math.round(state.validatedCount / state.products.length * 100) : 0 }}%"></div>
                </div>

                <!-- TÜM DOĞRULANDI -->
                <t t-if="state.validatedCount > 0 &amp;&amp; state.validatedCount >= state.products.length">
                    <div class="ub-validate-complete">
                        <i class="fa fa-check-circle"></i>
                        <h3>Tüm Ürünler Doğrulandı!</h3>
                    </div>
                </t>

                <!-- ÜRÜN BARKOD OKUT -->
                <div class="ub-search-form">
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

                <!-- BULUNAMADI BANNER -->
                <t t-if="state.notFoundBarcode">
                    <div class="ub-validate-notfound-banner">
                        <i class="fa fa-exclamation-triangle"></i>
                        Ürün Bu Rafta Bulunamadı!
                        <div class="ub-notfound-barcode"><t t-esc="state.notFoundBarcode"/></div>
                    </div>
                </t>

                <!-- ÜRÜN TABLOSU -->
                <div class="ub-validate-table-wrap">
                    <div class="ub-validate-table-header">
                        <h3><i class="fa fa-list"></i> Raftaki Ürünler</h3>
                        <span class="badge"><t t-esc="state.validatedCount"/>/<t t-esc="state.products.length"/></span>
                    </div>
                    <table class="ub-validate-table">
                        <thead>
                            <tr>
                                <th>ÜRÜN</th>
                                <th>KOD</th>
                                <th>BARKOD</th>
                                <th style="text-align:center">ADET</th>
                                <th style="text-align:center">SAYILMIŞ</th>
                            </tr>
                        </thead>
                        <tbody>
                            <t t-foreach="state.products" t-as="p" t-key="p.id">
                                <tr t-attf-class="{{ p.counted > 0 ? 'ub-validated' : '' }}">
                                    <td class="ub-validate-product-name" t-att-title="p.name"><t t-esc="p.name"/></td>
                                    <td><t t-esc="p.code || '-'"/></td>
                                    <td><t t-esc="p.barcode || '-'"/></td>
                                    <td class="ub-validate-qty"><t t-esc="p.quantity"/></td>
                                    <td t-attf-class="ub-validate-counted {{ p.counted > 0 ? 'ub-counted-done' : 'ub-counted-zero' }}">
                                        <t t-esc="p.counted"/>
                                    </td>
                                </tr>
                            </t>
                        </tbody>
                    </table>
                </div>
            </t>
        </div>
    `;

    setup() {
        this.state = useState({
            shelfBarcode: '',
            shelfInfo: null,
            products: [],
            productBarcode: '',
            validatedCount: 0,
            notFoundBarcode: null,
            error: null,
        });
    }

    async loadShelf() {
        this.state.error = null;
        this.state.shelfInfo = null;
        this.state.products = [];
        this.state.validatedCount = 0;

        const bc = this.state.shelfBarcode.trim();
        if (!bc) { this.state.error = 'Raf barkodu gerekli'; return; }

        try {
            const res = await BarcodeService.shelfControl(bc);
            if (res.error) { this.state.error = res.error; return; }

            // API: res.location = {id, name, complete_name, barcode, warehouse}
            this.state.shelfInfo = res.location;
            // API: res.products = [{id, name, barcode, code, marka, quantity}]
            this.state.products = (res.products || []).filter(p => p.quantity > 0).map(p => ({
                ...p,
                counted: 0,
            }));
        } catch (e) {
            this.state.error = 'Bağlantı hatası: ' + (e.message || e);
        }
    }

    onProductKey(ev) {
        if (ev.key === 'Enter') {
            this.validateProduct();
        }
    }

    validateProduct() {
        const bc = this.state.productBarcode.trim();
        if (!bc) return;

        this.state.notFoundBarcode = null;
        this.state.error = null;

        // Ürünü tabloda bul — barkod veya referans koduyla
        let found = false;
        for (const p of this.state.products) {
            if (p.barcode === bc || p.code === bc) {
                p.counted += 1;
                found = true;
                this.state.validatedCount = this.state.products.filter(x => x.counted > 0).length;
                if (navigator.vibrate) navigator.vibrate(100);
                break;
            }
        }

        if (!found) {
            this.state.notFoundBarcode = bc;
            if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
        }

        this.state.productBarcode = '';
    }

    resetForm() {
        Object.assign(this.state, {
            shelfBarcode: '',
            shelfInfo: null,
            products: [],
            productBarcode: '',
            validatedCount: 0,
            notFoundBarcode: null,
            error: null,
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
            if (target === 'shelf') {
                this.state.shelfBarcode = code;
                this.loadShelf();
            } else {
                this.state.productBarcode = code;
                this.validateProduct();
            }
        };

        // iOS Safari'de BarcodeDetector YOK veya düzgün çalışmıyor
        const useBarcodeDetector = ('BarcodeDetector' in window) && !/iPhone|iPad|iPod/i.test(navigator.userAgent);

        if (useBarcodeDetector) {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: 'environment' }
                });
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
                    if (!document.body.contains(overlay)) {
                        stream.getTracks().forEach(t => t.stop());
                        return;
                    }
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
            } catch (e) {
                statusEl.textContent = 'Kamera erişim hatası';
            }
        } else {
            // Html5Qrcode — iOS + tüm tarayıcılarda çalışır
            try {
                if (!window.Html5Qrcode) {
                    statusEl.textContent = 'Tarayıcı yükleniyor...';
                    const s = document.createElement('script');
                    s.src = 'https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js';
                    document.head.appendChild(s);
                    await new Promise((resolve, reject) => {
                        s.onload = resolve;
                        s.onerror = () => reject(new Error('CDN yüklenemedi'));
                        setTimeout(() => reject(new Error('Zaman aşımı')), 10000);
                    });
                }

                let cameraId = null;
                try {
                    const cameras = await Html5Qrcode.getCameras();
                    if (cameras && cameras.length > 0) {
                        const backCam = cameras.find(c => /back|rear|environment/i.test(c.label));
                        cameraId = backCam ? backCam.id : cameras[cameras.length - 1].id;
                    }
                } catch (e) {}

                const scanner = new Html5Qrcode('ub-camera-reader');
                const config = { fps: 10, qrbox: { width: 250, height: 150 } };
                const successCb = (code) => {
                    scanner.stop().catch(() => {});
                    overlay.remove();
                    onDetected(code);
                };

                if (cameraId) {
                    await scanner.start(cameraId, config, successCb, () => {});
                } else {
                    await scanner.start({ facingMode: 'environment' }, config, successCb, () => {});
                }

                overlay.querySelector('.ub-camera-close').onclick = () => {
                    scanner.stop().catch(() => {});
                    overlay.remove();
                };
            } catch (e) {
                console.error('Html5Qrcode hatası:', e);
                statusEl.textContent = 'Kamera başlatılamadı. Lütfen kamera izni verin ve tekrar deneyin.';
            }
        }
    }
}
