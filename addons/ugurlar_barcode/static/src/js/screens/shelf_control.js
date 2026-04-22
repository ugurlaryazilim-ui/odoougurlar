/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class ShelfControl extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-th"></i> Raf Kontrol
                </h2>
            </div>

            <!-- ARAMA FORMU -->
            <div class="ub-search-form">
                <div class="ub-search-field">
                    <label class="ub-field-label">Raf ID / Barkod</label>
                    <div class="ub-barcode-input-group">
                        <input type="text"
                               class="form-control ub-barcode-input"
                               placeholder="Raf barkodunu okutun veya yazın..."
                               t-on-keydown="onKeyDown"
                               t-att-value="state.inputValue"
                               t-on-input="onInput"/>
                        <button class="ub-scan-icon-btn" t-on-click="startCameraScan" title="Kamera ile tara">
                            <i class="fa fa-barcode"></i>
                        </button>
                    </div>
                </div>

                <button class="btn btn-primary ub-search-submit-btn" t-on-click="onSearch">
                    <i class="fa fa-search"></i> Arama
                </button>
            </div>

            <t t-if="state.loading">
                <div class="ub-loading">
                    <i class="fa fa-spinner fa-spin fa-2x"></i>
                    <p>Raf kontrol ediliyor...</p>
                </div>
            </t>

            <t t-if="state.error">
                <div class="ub-error-card">
                    <i class="fa fa-exclamation-triangle"></i>
                    <p t-esc="state.error"/>
                </div>
            </t>

            <t t-if="state.result">
                <!-- RAF BİLGİLERİ (HamurLabs tarzı) -->
                <div class="ub-shelf-info-section">
                    <div class="ub-shelf-detail-row">
                        <span class="ub-shelf-detail-label">Raf Adı:</span>
                        <strong t-esc="state.result.location.name"/>
                    </div>
                    <div class="ub-shelf-detail-row">
                        <span class="ub-shelf-detail-label">Raf Yolu:</span>
                        <span t-esc="state.result.location.complete_name"/>
                    </div>
                    <div class="ub-shelf-detail-row" t-if="state.result.location.barcode">
                        <span class="ub-shelf-detail-label">Raf Barkodu:</span>
                        <span class="ub-barcode-cell" t-esc="state.result.location.barcode"/>
                    </div>
                    <div class="ub-shelf-detail-row" t-if="state.result.location.warehouse">
                        <span class="ub-shelf-detail-label">Depo:</span>
                        <span t-esc="state.result.location.warehouse"/>
                    </div>
                </div>

                <!-- RAFLANMIŞ ÜRÜNLER TABLOSU -->
                <div class="ub-variants-section">
                    <div class="ub-section-title-dark" style="display:flex; justify-content:space-between; align-items:center;">
                        <span><i class="fa fa-cubes"></i> Raflanmış Ürünler</span>
                        <span class="ub-table-summary">
                            <t t-esc="state.result.total_products"/> ürün · Toplam: <t t-esc="state.result.total_quantity"/> adet
                        </span>
                    </div>

                    <t t-if="state.result.products.length">
                        <div class="ub-variant-table-wrap">
                            <table class="ub-variant-table ub-variant-table-striped">
                                <thead>
                                    <tr>
                                        <th>Ürün</th>
                                        <th>Barkod</th>
                                        <th>Kod</th>
                                        <th>Marka</th>
                                        <th class="text-end">Adet</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <t t-foreach="state.result.products" t-as="prod" t-key="prod.id">
                                        <tr>
                                            <td><strong t-esc="prod.name"/></td>
                                            <td class="ub-barcode-cell" t-esc="prod.barcode || '-'"/>
                                            <td t-esc="prod.code || '-'"/>
                                            <td t-esc="prod.marka || '-'"/>
                                            <td class="text-end">
                                                <span class="ub-stock-positive" t-esc="prod.quantity"/>
                                            </td>
                                        </tr>
                                    </t>
                                </tbody>
                                <tfoot>
                                    <tr class="ub-table-footer">
                                        <td colspan="4"><strong>TOPLAM</strong></td>
                                        <td class="text-end"><strong class="ub-stock-positive" t-esc="state.result.total_quantity"/></td>
                                    </tr>
                                </tfoot>
                            </table>
                        </div>
                    </t>

                    <t t-if="!state.result.products.length">
                        <div style="text-align:center; padding:2rem;">
                            <i class="fa fa-inbox fa-2x" style="color:#999;"></i>
                            <p style="color:#999; margin-top:0.5rem;">Bu raf boş</p>
                        </div>
                    </t>
                </div>
            </t>
        </div>
    `;

    static props = {
        navigate: Function,
        scanner: Object,
    };

    setup() {
        this.state = useState({
            inputValue: '',
            loading: false,
            error: null,
            result: null,
        });
        this._unsubscribe = this.props.scanner.onScan(barcode => {
            this.state.inputValue = barcode;
            this.doSearch(barcode);
        });
    }

    onInput(ev) {
        this.state.inputValue = ev.target.value;
        this._detectBarcodeScan(ev.target.value);
    }

    _detectBarcodeScan(val) {
        const now = Date.now();
        if (this._lastInputTime && (now - this._lastInputTime) < 80) {
            this._rapidCount = (this._rapidCount || 0) + 1;
        } else {
            this._rapidCount = 0;
        }
        this._lastInputTime = now;
        if (this._scanTimer) clearTimeout(this._scanTimer);
        if (this._rapidCount >= 6 && val.trim().length >= 4) {
            this._scanTimer = setTimeout(() => {
                if (this.state.inputValue.trim().length >= 4) {
                    this.doSearch(this.state.inputValue.trim());
                }
            }, 300);
        }
    }

    onKeyDown(ev) {
        if (ev.key === 'Enter' && this.state.inputValue.trim()) {
            ev.preventDefault();
            this.doSearch(this.state.inputValue.trim());
        }
    }

    onSearch() {
        if (this.state.inputValue.trim()) this.doSearch(this.state.inputValue.trim());
    }

    startCameraScan() {
        if (!('BarcodeDetector' in window)) {
            alert('Bu tarayıcı kamera ile barkod okumayı desteklemiyor.\nChrome (Android) veya Edge kullanın.');
            return;
        }
        const overlay = document.createElement('div');
        overlay.className = 'ub-camera-overlay';
        overlay.innerHTML = `
            <div class="ub-camera-header">
                <span>Raf barkodunu kameraya gösterin...</span>
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
            stream = s;
            video.srcObject = stream;
            statusEl.textContent = 'Raf barkodunu kameraya gösterin...';
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
                        this.state.inputValue = barcodes[0].rawValue;
                        this.doSearch(barcodes[0].rawValue);
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

    async doSearch(barcode) {
        this.state.loading = true;
        this.state.error = null;
        this.state.result = null;
        this.state.inputValue = barcode;
        try {
            const result = await BarcodeService.shelfControl(barcode);
            if (result.error) this.state.error = result.error;
            else this.state.result = result;
        } catch (e) {
            this.state.error = 'Bağlantı hatası: ' + (e.message || e);
        }
        this.state.loading = false;
    }

    willUnmount() {
        if (this._unsubscribe) this._unsubscribe();
        if (this._scanTimer) clearTimeout(this._scanTimer);
    }
}
