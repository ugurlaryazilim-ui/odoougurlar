/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class CountingScreen extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="goBack">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-calculator"></i> Sayım
                </h2>
                <div class="ub-mode-toggle" t-if="state.view !== 'menu'">
                    <button t-attf-class="btn btn-sm {{state.view === 'count' ? 'ub-mode-active-green' : 'btn-outline-secondary'}}"
                            t-on-click="() => this.state.view = 'count'">
                        Sayım
                    </button>
                    <button t-attf-class="btn btn-sm {{state.view === 'history' ? 'ub-mode-active-green' : 'btn-outline-secondary'}}"
                            t-on-click="showHistory">
                        Sayım Listesi
                    </button>
                </div>
            </div>

            <!-- SAYIM MENÜSÜ -->
            <t t-if="state.view === 'menu'">
                <div class="ub-menu-grid" style="padding:1.5rem;">
                    <div class="ub-menu-card ub-card-counting" t-on-click="() => this.state.view = 'count'">
                        <div class="ub-card-icon"><i class="fa fa-barcode"></i></div>
                        <div class="ub-card-title">Sayım</div>
                        <div class="ub-card-desc">Raf sayımı yap</div>
                    </div>
                    <div class="ub-menu-card ub-card-counting" t-on-click="showHistory">
                        <div class="ub-card-icon"><i class="fa fa-list"></i></div>
                        <div class="ub-card-title">Sayım Listesi</div>
                        <div class="ub-card-desc">Geçmiş sayımlar</div>
                    </div>
                </div>
            </t>

            <!-- SAYIM LİSTESİ (HamurLabs tarzı geçmiş) -->
            <t t-if="state.view === 'history'">
                <t t-if="state.historyLoading">
                    <div class="ub-loading"><i class="fa fa-spinner fa-spin fa-2x"></i><p>Yükleniyor...</p></div>
                </t>
                <t t-if="!state.historyLoading and state.historyItems.length">
                    <div class="ub-variants-section" style="margin-top:1rem;">
                        <div class="ub-section-title-dark" style="display:flex; justify-content:space-between; align-items:center;">
                            <span><i class="fa fa-list"></i> Sayım Listesi</span>
                            <span class="ub-table-summary"><t t-esc="state.historyItems.length"/> sayım</span>
                        </div>
                        <div class="ub-variant-table-wrap">
                            <table class="ub-variant-table ub-variant-table-striped">
                                <thead>
                                    <tr>
                                        <th>Raf</th>
                                        <th>Depo</th>
                                        <th>Kullanıcı</th>
                                        <th class="text-center">Ürün</th>
                                        <th class="text-center">Adet</th>
                                        <th>Tarih</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <t t-foreach="state.historyItems" t-as="h" t-key="h.id">
                                        <tr style="cursor:pointer;" t-on-click="() => this.showHistoryDetail(h)">
                                            <td><strong t-esc="h.location_name"/></td>
                                            <td t-esc="h.warehouse || '-'"/>
                                            <td t-esc="h.user_name"/>
                                            <td class="text-center"><span class="badge" style="background:#714B67;color:#fff;" t-esc="h.product_count"/></td>
                                            <td class="text-center"><span class="ub-stock-positive" t-esc="h.total_quantity"/></td>
                                            <td t-esc="h.create_date"/>
                                        </tr>
                                    </t>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </t>
                <t t-if="!state.historyLoading and !state.historyItems.length">
                    <div style="text-align:center; padding:3rem; color:#999;">
                        <i class="fa fa-inbox fa-2x"></i>
                        <p>Henüz sayım kaydı yok</p>
                    </div>
                </t>

                <!-- Sayım detayı modal -->
                <t t-if="state.historyDetail">
                    <div class="ub-shelf-info-section" style="margin-top:0.5rem;">
                        <div class="ub-shelf-detail-row">
                            <span class="ub-shelf-detail-label">Raf:</span>
                            <strong t-esc="state.historyDetail.location_name"/>
                        </div>
                        <div class="ub-shelf-detail-row">
                            <span class="ub-shelf-detail-label">Tarih:</span>
                            <span t-esc="state.historyDetail.create_date"/>
                        </div>
                        <div class="ub-shelf-detail-row">
                            <span class="ub-shelf-detail-label">Kullanıcı:</span>
                            <span t-esc="state.historyDetail.user_name"/>
                        </div>
                        <button class="btn btn-sm btn-outline-secondary mt-2" t-on-click="() => this.state.historyDetail = null">
                            <i class="fa fa-times"></i> Kapat
                        </button>
                    </div>
                    <div class="ub-variants-section" style="margin-top:0.5rem;">
                        <div class="ub-section-title-dark">
                            <i class="fa fa-cubes"></i> Sayılan Ürünler
                        </div>
                        <div class="ub-variant-table-wrap">
                            <table class="ub-variant-table ub-variant-table-striped">
                                <thead>
                                    <tr>
                                        <th>Barkod</th>
                                        <th>Ürün</th>
                                        <th class="text-end">Adet</th>
                                        <th>Not</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <t t-foreach="state.historyDetail.items" t-as="item" t-key="item.barcode">
                                        <tr>
                                            <td class="ub-barcode-cell" t-esc="item.barcode"/>
                                            <td t-esc="item.product_name"/>
                                            <td class="text-end"><strong t-esc="item.quantity"/></td>
                                            <td style="font-size:0.8rem;color:#888;" t-esc="item.notes"/>
                                        </tr>
                                    </t>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </t>
            </t>

            <!-- SAYIM MODU — ADIM 1: RAF BARKODU -->
            <t t-if="state.view === 'count' and state.step === 1">
                <div class="ub-search-form">
                    <div class="ub-search-field">
                        <label class="ub-field-label">
                            <span class="ub-step-badge">1</span> Raf Barkodu
                        </label>
                        <div class="ub-barcode-input-group">
                            <input type="text" class="form-control ub-barcode-input"
                                   placeholder="Sayım yapılacak raf barkodunu okutun..."
                                   t-on-keydown="onShelfKey"
                                   t-att-value="state.shelfBarcode"
                                   t-on-input="(ev) => this.onShelfInput(ev)"/>
                            <button class="ub-scan-icon-btn" t-on-click="() => this.cameraScan('shelf')" title="Kamera ile tara">
                                <i class="fa fa-barcode"></i>
                            </button>
                        </div>
                    </div>
                    <button class="btn btn-primary ub-search-submit-btn" t-on-click="onShelfScan">
                        <i class="fa fa-search"></i> Sayıma Başla
                    </button>
                </div>
            </t>

            <!-- SAYIM MODU — ADIM 2: ÜRÜN SAYIMI -->
            <t t-if="state.view === 'count' and state.step === 2">
                <!-- Raf bilgisi -->
                <div class="ub-shelf-info-section">
                    <div class="ub-shelf-detail-row">
                        <span class="ub-shelf-detail-label">Raf Yolu:</span>
                        <strong t-esc="state.shelfInfo.complete_name || state.shelfBarcode"/>
                    </div>
                    <div class="ub-shelf-detail-row" t-if="state.shelfInfo.warehouse">
                        <span class="ub-shelf-detail-label">Depo:</span>
                        <span t-esc="state.shelfInfo.warehouse"/>
                    </div>
                    <div class="ub-count-stats">
                        <div class="ub-count-stat-item">
                            <span class="ub-count-stat-num" t-esc="state.shelfInfo.total_products || 0"/>
                            <span class="ub-count-stat-lbl">Raf Adeti</span>
                        </div>
                        <div class="ub-count-stat-item">
                            <span class="ub-count-stat-num ub-count-done" t-esc="countedCount"/>
                            <span class="ub-count-stat-lbl">Sayılan</span>
                        </div>
                        <div class="ub-count-stat-item">
                            <span class="ub-count-stat-num" t-esc="state.items.length"/>
                            <span class="ub-count-stat-lbl">Toplam SKU</span>
                        </div>
                    </div>
                    <button class="btn btn-sm btn-outline-secondary mt-2" t-on-click="changeShelf">
                        <i class="fa fa-refresh"></i> Raf Değiştir
                    </button>
                </div>

                <!-- Ürün barkod tara -->
                <div class="ub-search-form" style="margin-top:0.5rem;">
                    <div class="ub-search-field">
                        <label class="ub-field-label">
                            <span class="ub-step-badge">2</span> Ürün Barkodu
                        </label>
                        <div class="ub-barcode-input-group">
                            <input type="text" class="form-control ub-barcode-input"
                                   placeholder="Ürün barkodunu okutun..."
                                   t-on-keydown="onProductKey"
                                   t-att-value="state.productInput"
                                   t-on-input="(ev) => this.onProductInput(ev)"/>
                            <button class="ub-scan-icon-btn" t-on-click="() => this.cameraScan('product')" title="Kamera ile tara">
                                <i class="fa fa-barcode"></i>
                            </button>
                        </div>
                    </div>
                </div>

                <!-- SAYIM TABLOSU -->
                <div class="ub-variants-section" t-if="state.items.length">
                    <div class="ub-section-title-dark" style="display:flex; justify-content:space-between; align-items:center;">
                        <span><i class="fa fa-list-ol"></i> Sayım Listesi</span>
                        <span class="ub-table-summary"><t t-esc="state.items.length"/> ürün</span>
                    </div>
                    <div class="ub-variant-table-wrap">
                        <table class="ub-variant-table ub-variant-table-striped">
                            <thead>
                                <tr>
                                    <th>Barkod</th>
                                    <th>Ürün Adı</th>
                                    <th>Eski Adet</th>
                                    <th class="text-center">Sayılmış</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                <t t-foreach="state.items" t-as="item" t-key="item.barcode">
                                    <tr t-attf-class="{{item.counted ? 'ub-row-counted' : ''}} {{item.isNew ? 'ub-row-new-product' : ''}}">
                                        <td class="ub-barcode-cell" t-esc="item.barcode"/>
                                        <td>
                                            <span t-esc="item.name || '-'"/>
                                            <span t-if="item.isNew" class="badge" style="background:#e74c3c;color:#fff;font-size:0.65rem;margin-left:4px;">YENİ</span>
                                        </td>
                                        <td class="text-muted" t-esc="item.old_qty"/>
                                        <td class="text-center">
                                            <div class="ub-count-input-group">
                                                <input type="number" min="0"
                                                       class="form-control ub-count-input"
                                                       t-att-value="item.quantity"
                                                       t-on-change="(ev) => this.updateQty(item.barcode, ev.target.value)"/>
                                                <button class="btn btn-sm ub-count-ok-btn"
                                                        t-attf-class="btn btn-sm {{item.counted ? 'btn-success' : 'btn-primary'}}"
                                                        t-on-click="() => this.confirmItem(item.barcode)">
                                                    Tamam
                                                </button>
                                            </div>
                                        </td>
                                        <td>
                                            <button class="btn btn-sm btn-outline-danger" t-on-click="() => this.removeItem(item.barcode)">
                                                <i class="fa fa-trash"></i>
                                            </button>
                                        </td>
                                    </tr>
                                </t>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- KAYDET BUTONU -->
                <div class="ub-action-buttons" t-if="state.items.length">
                    <button class="btn ub-action-btn ub-action-putaway" t-on-click="onSave"
                            t-att-disabled="state.loading || !countedCount">
                        <i class="fa fa-save"></i> Tümünü Tamamla (<t t-esc="countedCount"/> ürün)
                    </button>
                </div>
            </t>

            <!-- SONUÇ -->
            <t t-if="state.view === 'count' and state.step === 3">
                <div class="ub-success-card">
                    <i class="fa fa-check-circle"></i>
                    <p>Sayım kaydedildi!</p>
                    <p t-esc="state.resultMsg"/>
                    <button class="btn btn-primary mt-2" t-on-click="reset">
                        <i class="fa fa-plus"></i> Yeni Sayım
                    </button>
                </div>

                <div class="ub-variants-section" t-if="state.results.length">
                    <div class="ub-section-title-dark"><i class="fa fa-list"></i> Sayım Sonuçları</div>
                    <div class="ub-variant-table-wrap">
                        <table class="ub-variant-table ub-variant-table-striped">
                            <thead>
                                <tr>
                                    <th>Ürün</th>
                                    <th>Barkod</th>
                                    <th class="text-center">Eski</th>
                                    <th class="text-center">→</th>
                                    <th class="text-center">Yeni</th>
                                    <th>Durum</th>
                                </tr>
                            </thead>
                            <tbody>
                                <t t-foreach="state.results" t-as="r" t-key="r.barcode">
                                    <tr>
                                        <td t-esc="r.product_name || '-'"/>
                                        <td class="ub-barcode-cell" t-esc="r.barcode"/>
                                        <td class="text-center text-muted" t-esc="r.old_qty"/>
                                        <td class="text-center">→</td>
                                        <td class="text-center"><strong t-esc="r.new_qty"/></td>
                                        <td>
                                            <span t-if="r.status === 'updated'" class="badge" style="background:#27ae60;color:#fff;">✓</span>
                                            <span t-if="r.status === 'not_found'" class="badge" style="background:#e74c3c;color:#fff;">Bulunamadı</span>
                                        </td>
                                    </tr>
                                </t>
                            </tbody>
                        </table>
                    </div>
                </div>
            </t>

            <t t-if="state.loading">
                <div class="ub-loading"><i class="fa fa-spinner fa-spin fa-2x"></i><p>İşleniyor...</p></div>
            </t>
            <t t-if="state.error">
                <div class="ub-error-card"><i class="fa fa-exclamation-triangle"></i><p t-esc="state.error"/></div>
            </t>
        </div>
    `;

    static props = { navigate: Function, scanner: Object };

    setup() {
        this.state = useState({
            view: 'menu',  // 'menu', 'count', 'history'
            step: 1,
            shelfBarcode: '',
            shelfInfo: {},
            productInput: '',
            items: [],
            loading: false,
            error: null,
            results: [],
            resultMsg: '',
            // Sayım listesi
            historyItems: [],
            historyLoading: false,
            historyDetail: null,
        });
        this._unsub = this.props.scanner.onScan(bc => this.onScanDetected(bc));
    }

    get countedCount() {
        return this.state.items.filter(i => i.counted).length;
    }

    goBack() {
        if (this.state.view !== 'menu') {
            this.state.view = 'menu';
            this.state.historyDetail = null;
        } else {
            this.props.navigate('main');
        }
    }

    onScanDetected(bc) {
        if (this.state.view === 'count') {
            if (this.state.step === 1) {
                this.state.shelfBarcode = bc;
                this.onShelfScan();
            } else if (this.state.step === 2) {
                this.addProductByBarcode(bc);
            }
        }
    }

    // ─── SAYIM LİSTESİ ───────────────────────────
    async showHistory() {
        this.state.view = 'history';
        this.state.historyLoading = true;
        this.state.historyDetail = null;
        try {
            const res = await BarcodeService.countList(30);
            this.state.historyItems = res.counts || [];
        } catch (e) {
            this.state.historyItems = [];
        }
        this.state.historyLoading = false;
    }

    showHistoryDetail(h) {
        this.state.historyDetail = h;
    }

    // ─── ADIM 1: RAF TARA ─────────────────────────
    onShelfInput(ev) {
        this.state.shelfBarcode = ev.target.value;
        this._detectScan(ev.target.value, 'shelf');
    }

    onShelfKey(ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); this.onShelfScan(); }
    }

    async onShelfScan() {
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
                    total_products: result.total_products,
                    total_quantity: result.total_quantity,
                };
                this.state.items = (result.products || []).map(p => ({
                    barcode: p.barcode || p.code || String(p.id),
                    name: p.name,
                    old_qty: p.quantity,
                    quantity: 0,
                    counted: false,
                    isNew: false,
                }));
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
        this.state.items = [];
        this.state.error = null;
    }

    // ─── ADIM 2: ÜRÜN OKUT + SAYIM ───────────────
    onProductInput(ev) {
        this.state.productInput = ev.target.value;
        this._detectScan(ev.target.value, 'product');
    }

    onProductKey(ev) {
        if (ev.key === 'Enter') {
            ev.preventDefault();
            this.addProductByBarcode(this.state.productInput.trim());
        }
    }

    addProductByBarcode(bc) {
        if (!bc) return;
        const existing = this.state.items.find(i => i.barcode === bc);
        if (existing) {
            existing.quantity = (existing.quantity || 0) + 1;
            existing.counted = true;
        } else {
            // Rafta olmayan yeni ürün — kırmızı ile göster
            this.state.items.push({
                barcode: bc,
                name: '',
                old_qty: 0,
                quantity: 1,
                counted: true,
                isNew: true,
            });
        }
        this.state.productInput = '';
    }

    updateQty(barcode, val) {
        const item = this.state.items.find(i => i.barcode === barcode);
        if (item) item.quantity = parseFloat(val) || 0;
    }

    confirmItem(barcode) {
        const item = this.state.items.find(i => i.barcode === barcode);
        if (item) item.counted = true;
    }

    removeItem(barcode) {
        this.state.items = this.state.items.filter(i => i.barcode !== barcode);
    }

    // ─── KAYDET ───────────────────────────────────
    async onSave() {
        const counted = this.state.items.filter(i => i.counted);
        if (!counted.length) return;

        this.state.loading = true;
        this.state.error = null;
        try {
            const payload = counted.map(i => ({ barcode: i.barcode, quantity: i.quantity }));
            const res = await BarcodeService.countSave(this.state.shelfBarcode.trim(), payload);
            if (res.error) {
                this.state.error = res.error;
            } else {
                this.state.results = res.results || [];
                this.state.resultMsg = `${res.location}: ${res.total_counted} ürün sayıldı`;
                this.state.step = 3;
            }
        } catch (e) {
            this.state.error = 'Kaydetme hatası: ' + (e.message || e);
        }
        this.state.loading = false;
    }

    reset() {
        this.state.step = 1;
        this.state.shelfBarcode = '';
        this.state.shelfInfo = {};
        this.state.items = [];
        this.state.results = [];
        this.state.error = null;
        this.state.resultMsg = '';
    }

    // ─── AUTO-SCAN ────────────────────────────────
    _detectScan(val, target) {
        const now = Date.now();
        const key = '_rapid_' + target;
        if (this[key + '_time'] && (now - this[key + '_time']) < 80) {
            this[key + '_count'] = (this[key + '_count'] || 0) + 1;
        } else { this[key + '_count'] = 0; }
        this[key + '_time'] = now;
        if (this[key + '_timer']) clearTimeout(this[key + '_timer']);
        if (this[key + '_count'] >= 6 && val.trim().length >= 4) {
            this[key + '_timer'] = setTimeout(() => {
                if (target === 'shelf') this.onShelfScan();
                else this.addProductByBarcode(this.state.productInput.trim());
            }, 300);
        }
    }

    // ─── KAMERA ───────────────────────────────────
    cameraScan(target) {
        if (!('BarcodeDetector' in window)) {
            alert('Bu tarayıcı kamera ile barkod okumayı desteklemiyor.');
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
            statusEl.textContent = `${target === 'shelf' ? 'Raf' : 'Ürün'} barkodunu gösterin...`;
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
                            this.onShelfScan();
                        } else {
                            this.addProductByBarcode(barcodes[0].rawValue);
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

    willUnmount() { if (this._unsub) this._unsub(); }
}
