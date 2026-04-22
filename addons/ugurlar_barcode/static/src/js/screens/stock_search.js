/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class StockSearch extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-search"></i> Ürün Stok Arama
                </h2>
            </div>

            <!-- ARAMA FORMU -->
            <div class="ub-search-form">
                <div class="ub-search-field">
                    <label class="ub-field-label">Barkod</label>
                    <div class="ub-barcode-input-group">
                        <input type="text"
                               class="form-control ub-barcode-input"
                               placeholder="Barkod okutun veya yazın..."
                               t-on-keydown="(ev) => this.onKeyDown(ev, 'barcode')"
                               t-att-value="state.barcodeValue"
                               t-on-input="(ev) => this.onFieldInput(ev, 'barcode')"/>
                        <button class="ub-scan-icon-btn" t-on-click="startCameraScan" title="Kamera ile tara">
                            <i class="fa fa-barcode"></i>
                        </button>
                    </div>
                </div>

                <div class="ub-search-field">
                    <label class="ub-field-label">Ürün Kodu</label>
                    <input type="text"
                           class="form-control ub-barcode-input"
                           placeholder="Ürün Kodu"
                           t-on-keydown="(ev) => this.onKeyDown(ev, 'code')"
                           t-att-value="state.codeValue"
                           t-on-input="(ev) => this.onFieldInput(ev, 'code')"/>
                </div>

                <div class="ub-search-field">
                    <label class="ub-field-label">Ürün Adı</label>
                    <input type="text"
                           class="form-control ub-barcode-input"
                           placeholder="Ürün Adı"
                           t-on-keydown="(ev) => this.onKeyDown(ev, 'name')"
                           t-att-value="state.nameValue"
                           t-on-input="(ev) => this.onFieldInput(ev, 'name')"/>
                </div>

                <button class="btn btn-primary ub-search-submit-btn" t-on-click="onSearch">
                    <i class="fa fa-search"></i> Arama
                </button>
            </div>

            <t t-if="state.loading">
                <div class="ub-loading">
                    <i class="fa fa-spinner fa-spin fa-2x"></i>
                    <p>Aranıyor...</p>
                </div>
            </t>

            <t t-if="state.error">
                <div class="ub-error-card">
                    <i class="fa fa-exclamation-triangle"></i>
                    <p t-esc="state.error"/>
                </div>
            </t>

            <!-- BEDENLER TABLOSU -->
            <t t-if="state.result and sortedVariants.length">
                <div class="ub-variants-section">
                    <div class="ub-section-title-dark" style="display:flex; justify-content:space-between; align-items:center;">
                        <span><i class="fa fa-th-list"></i> Bedenler</span>
                        <span class="ub-table-summary">
                            <t t-esc="sortedVariants.length"/> satır · Toplam: <t t-esc="totalStock"/> adet
                        </span>
                    </div>
                    <div class="ub-variant-table-wrap">
                        <table class="ub-variant-table ub-variant-table-striped">
                            <thead>
                                <tr>
                                    <th t-on-click="() => this.toggleSort('code')" class="ub-th-sortable">
                                        Ürün Kodu <i t-attf-class="fa fa-sort{{state.sortCol === 'code' ? (state.sortAsc ? '-asc' : '-desc') : ''}}"></i>
                                    </th>
                                    <th t-on-click="() => this.toggleSort('color')" class="ub-th-sortable">
                                        Renk <i t-attf-class="fa fa-sort{{state.sortCol === 'color' ? (state.sortAsc ? '-asc' : '-desc') : ''}}"></i>
                                    </th>
                                    <th t-on-click="() => this.toggleSort('size')" class="ub-th-sortable">
                                        Beden <i t-attf-class="fa fa-sort{{state.sortCol === 'size' ? (state.sortAsc ? '-asc' : '-desc') : ''}}"></i>
                                    </th>
                                    <th t-on-click="() => this.toggleSort('stock')" class="ub-th-sortable text-end">
                                        Adet <i t-attf-class="fa fa-sort{{state.sortCol === 'stock' ? (state.sortAsc ? '-asc' : '-desc') : ''}}"></i>
                                    </th>
                                    <th t-on-click="() => this.toggleSort('price')" class="ub-th-sortable text-end">
                                        Fiyat <i t-attf-class="fa fa-sort{{state.sortCol === 'price' ? (state.sortAsc ? '-asc' : '-desc') : ''}}"></i>
                                    </th>
                                    <th>Marka</th>
                                    <th>Barkod</th>
                                </tr>
                            </thead>
                            <tbody>
                                <t t-foreach="sortedVariants" t-as="v" t-key="v.id">
                                    <tr t-attf-class="{{v.stock === 0 ? 'ub-no-stock-row' : ''}}">
                                        <td t-esc="v.code || '-'"/>
                                        <td t-esc="v.color || '-'"/>
                                        <td t-esc="v.size || '-'"/>
                                        <td class="text-end">
                                            <span t-attf-class="{{v.stock > 0 ? 'ub-stock-positive' : 'ub-stock-zero'}}"
                                                  t-esc="v.stock"/>
                                        </td>
                                        <td class="text-end" t-esc="formatPrice(v.price)"/>
                                        <td t-esc="v.marka || '-'"/>
                                        <td class="ub-barcode-cell" t-esc="v.barcode || '-'"/>
                                    </tr>
                                </t>
                            </tbody>
                            <tfoot>
                                <tr class="ub-table-footer">
                                    <td colspan="3"><strong>TOPLAM</strong></td>
                                    <td class="text-end"><strong class="ub-stock-positive" t-esc="totalStock"/></td>
                                    <td colspan="3"></td>
                                </tr>
                            </tfoot>
                        </table>
                    </div>
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
            barcodeValue: '',
            codeValue: '',
            nameValue: '',
            loading: false,
            error: null,
            result: null,
            sortCol: '',
            sortAsc: true,
        });

        this._unsubscribe = this.props.scanner.onScan(barcode => {
            this.state.barcodeValue = barcode;
            this.state.codeValue = '';
            this.state.nameValue = '';
            this.doSearch(barcode, 'barcode');
        });
    }

    // ─── Türk para formatı ₺2.799,99 ──────────────────
    formatPrice(price) {
        if (price == null) return '-';
        return '₺' + Number(price).toLocaleString('tr-TR', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    // ─── Toplam stok hesapla ───────────────────────────
    get totalStock() {
        if (!this.state.result || !this.state.result.variants) return 0;
        return this.state.result.variants.reduce((sum, v) => sum + (v.stock || 0), 0);
    }

    // ─── Sıralama toggle ──────────────────────────────
    toggleSort(col) {
        if (this.state.sortCol === col) {
            this.state.sortAsc = !this.state.sortAsc;
        } else {
            this.state.sortCol = col;
            this.state.sortAsc = true;
        }
    }

    // ─── Sıralanmış varyant listesi ──────────────────
    get sortedVariants() {
        if (!this.state.result || !this.state.result.variants) return [];
        const list = [...this.state.result.variants];
        const col = this.state.sortCol;
        if (!col) return list;

        const dir = this.state.sortAsc ? 1 : -1;
        list.sort((a, b) => {
            let va = a[col], vb = b[col];
            // Sayısal sıralama
            if (col === 'stock' || col === 'price') {
                return (Number(va) - Number(vb)) * dir;
            }
            // Beden sıralama — sayısal denenmeli
            if (col === 'size') {
                const na = parseInt(va), nb = parseInt(vb);
                if (!isNaN(na) && !isNaN(nb)) return (na - nb) * dir;
            }
            // String sıralama
            va = (va || '').toString().toLowerCase();
            vb = (vb || '').toString().toLowerCase();
            return va.localeCompare(vb, 'tr') * dir;
        });
        return list;
    }

    onFieldInput(ev, field) {
        const val = ev.target.value;
        if (field === 'barcode') {
            this.state.barcodeValue = val;
            if (val) { this.state.codeValue = ''; this.state.nameValue = ''; }
            this._detectBarcodeScan(val);
        } else if (field === 'code') {
            this.state.codeValue = val;
            if (val) { this.state.barcodeValue = ''; this.state.nameValue = ''; }
        } else if (field === 'name') {
            this.state.nameValue = val;
            if (val) { this.state.barcodeValue = ''; this.state.codeValue = ''; }
        }
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

        if (this._rapidCount >= 6 && val.trim().length >= 8) {
            this._scanTimer = setTimeout(() => {
                if (this.state.barcodeValue.trim().length >= 8) {
                    this.doSearch(this.state.barcodeValue.trim(), 'barcode');
                }
            }, 300);
        }
    }

    onKeyDown(ev, searchType) {
        if (ev.key === 'Enter') {
            ev.preventDefault();
            const value = ev.target.value.trim();
            if (value) {
                this.doSearch(value, searchType);
            }
        }
    }

    onSearch() {
        if (this.state.barcodeValue.trim()) {
            this.doSearch(this.state.barcodeValue.trim(), 'barcode');
        } else if (this.state.codeValue.trim()) {
            this.doSearch(this.state.codeValue.trim(), 'code');
        } else if (this.state.nameValue.trim()) {
            this.doSearch(this.state.nameValue.trim(), 'name');
        }
    }

    async startCameraScan() {
        const useNative = 'BarcodeDetector' in window;
        // iOS/Safari fallback: html5-qrcode CDN yükle
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
                alert('Barkod tarayıcı yüklenemedi. Lütfen barkodu manuel girin.');
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
            this.state.barcodeValue = barcode;
            this.state.codeValue = '';
            this.state.nameValue = '';
            this.doSearch(barcode, 'barcode');
        };

        document.getElementById('ub-cam-close').onclick = cleanup;
        overlay.onclick = (e) => { if (e.target === overlay) cleanup(); };

        if (useNative) {
            // ─── Chrome/Android: Native BarcodeDetector ─────
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
                    if (!scanning || video.readyState < 2) {
                        animFrame = requestAnimationFrame(scanFrame);
                        return;
                    }
                    try {
                        const barcodes = await detector.detect(video);
                        if (barcodes.length > 0) {
                            onScanSuccess(barcodes[0].rawValue);
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
        } else {
            // ─── iOS/Safari: html5-qrcode fallback ─────
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

    async doSearch(query, searchType) {
        this.state.loading = true;
        this.state.error = null;
        this.state.result = null;
        this.state.sortCol = '';
        this.state.sortAsc = true;

        try {
            const result = await BarcodeService.productSearch(query, searchType);
            if (result.error) {
                this.state.error = result.error;
            } else {
                this.state.result = result;
            }
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
