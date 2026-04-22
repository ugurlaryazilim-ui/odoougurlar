/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class MovementsScreen extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-exchange"></i> Stok Hareketleri
                </h2>
            </div>

            <!-- FİLTRELER (HamurLabs tarzı) -->
            <div class="ub-search-form">
                <div class="ub-search-field">
                    <label class="ub-field-label">Barkod Ara</label>
                    <div class="ub-barcode-input-group">
                        <input type="text" class="form-control ub-barcode-input"
                               placeholder="Ürün barkodu veya kodu..."
                               t-att-value="state.productBarcode"
                               t-on-input="(ev) => this.state.productBarcode = ev.target.value"
                               t-on-keydown="onKeyDown"/>
                        <button class="ub-scan-icon-btn" t-on-click="cameraScan" title="Kamera ile tara">
                            <i class="fa fa-barcode"></i>
                        </button>
                    </div>
                </div>
                <div style="display:flex; gap:0.8rem;">
                    <div class="ub-search-field" style="flex:1;">
                        <label class="ub-field-label">Dönem</label>
                        <select class="form-control ub-select" t-on-change="onDaysChange" t-att-value="state.days">
                            <option value="0">Tümü</option>
                            <option value="1">Bugün</option>
                            <option value="3">Son 3 Gün</option>
                            <option value="7" selected="">Son 7 Gün</option>
                            <option value="14">Son 14 Gün</option>
                            <option value="30">Son 30 Gün</option>
                            <option value="90">Son 90 Gün</option>
                            <option value="365">Son 1 Yıl</option>
                        </select>
                    </div>
                    <div class="ub-search-field" style="flex:1;">
                        <label class="ub-field-label">Tür</label>
                        <select class="form-control ub-select" t-on-change="onTypeChange" t-att-value="state.moveType">
                            <option value="all">Tümü</option>
                            <option value="in">Giriş</option>
                            <option value="out">Çıkış</option>
                            <option value="internal">İç Transfer</option>
                        </select>
                    </div>
                </div>
                <button class="btn btn-primary ub-search-submit-btn" t-on-click="loadMovements">
                    <i class="fa fa-search"></i> Filtrele
                </button>
            </div>

            <t t-if="state.loading">
                <div class="ub-loading"><i class="fa fa-spinner fa-spin fa-2x"></i><p>Yükleniyor...</p></div>
            </t>

            <t t-if="state.error">
                <div class="ub-error-card"><i class="fa fa-exclamation-triangle"></i><p t-esc="state.error"/></div>
            </t>

            <t t-if="state.result">
                <!-- ÜRÜN BİLGİ KARTI (barkod ile aranmışsa) -->
                <t t-if="state.result.product_info">
                    <div class="ub-shelf-info-section">
                        <div class="ub-shelf-detail-row">
                            <span class="ub-shelf-detail-label">Barkod:</span>
                            <span class="ub-barcode-cell" t-esc="state.result.product_info.barcode"/>
                        </div>
                        <div class="ub-shelf-detail-row">
                            <span class="ub-shelf-detail-label">Ürün Kodu:</span>
                            <strong t-esc="state.result.product_info.code"/>
                        </div>
                        <div class="ub-shelf-detail-row" t-if="state.result.product_info.marka">
                            <span class="ub-shelf-detail-label">Marka:</span>
                            <span t-esc="state.result.product_info.marka"/>
                        </div>
                    </div>
                </t>

                <!-- İŞLEM BUTONLARI (HamurLabs tarzı) -->
                <div class="ub-action-buttons" style="margin:0.8rem 1rem 0; flex-direction:row;">
                    <button class="btn ub-action-btn ub-action-stock" style="flex:1; padding:0.6rem;"
                            t-on-click="loadMovements">
                        <i class="fa fa-filter"></i> Filtrele
                    </button>
                    <button class="btn ub-action-btn" style="flex:1; padding:0.6rem; background:linear-gradient(135deg, #27ae60, #2ecc71);"
                            t-on-click="clearFilters">
                        <i class="fa fa-eraser"></i> Temizle
                    </button>
                </div>

                <!-- İSTATİSTİK KARTLARI -->
                <div class="ub-stats-row">
                    <div class="ub-stat-card ub-stat-in">
                        <div class="ub-stat-num" t-esc="state.result.stats.in_count"/>
                        <div class="ub-stat-txt">Giriş</div>
                    </div>
                    <div class="ub-stat-card ub-stat-out">
                        <div class="ub-stat-num" t-esc="state.result.stats.out_count"/>
                        <div class="ub-stat-txt">Çıkış</div>
                    </div>
                    <div class="ub-stat-card ub-stat-int">
                        <div class="ub-stat-num" t-esc="state.result.stats.internal_count"/>
                        <div class="ub-stat-txt">Transfer</div>
                    </div>
                    <div class="ub-stat-card ub-stat-total">
                        <div class="ub-stat-num" t-esc="state.result.total"/>
                        <div class="ub-stat-txt">Toplam</div>
                    </div>
                </div>

                <!-- HAREKET TABLOSU (HamurLabs tarzı — kart yerine tablo) -->
                <t t-if="state.result.movements.length">
                    <div class="ub-variants-section">
                        <div class="ub-section-title-dark" style="display:flex; justify-content:space-between; align-items:center;">
                            <span><i class="fa fa-list"></i> Hareket Listesi</span>
                            <span class="ub-table-summary">
                                <t t-esc="filteredMovements.length"/> / <t t-esc="state.result.movements.length"/> kayıt
                            </span>
                        </div>

                        <!-- Tablo içi arama -->
                        <div style="padding:0.5rem 0.8rem; background:#f8f9fa; border-bottom:1px solid #e9ecef; display:flex; align-items:center; gap:0.5rem;">
                            <i class="fa fa-search" style="color:#999;"></i>
                            <input type="text" class="form-control" style="border:1px solid #dee2e6; padding:0.4rem 0.6rem; font-size:0.85rem;"
                                   placeholder="Tabloda ara..."
                                   t-att-value="state.tableSearch"
                                   t-on-input="(ev) => this.state.tableSearch = ev.target.value"/>
                        </div>

                        <div class="ub-variant-table-wrap">
                            <table class="ub-variant-table ub-variant-table-striped">
                                <thead>
                                    <tr>
                                        <th class="ub-th-sortable" t-on-click="() => this.toggleSort('date')">
                                            Tarih <i t-attf-class="fa {{sortIcon('date')}}"></i>
                                        </th>
                                        <th>Ürün</th>
                                        <th class="ub-th-sortable" t-on-click="() => this.toggleSort('move_type_label')">
                                            Hareket Tipi <i t-attf-class="fa {{sortIcon('move_type_label')}}"></i>
                                        </th>
                                        <th class="text-center ub-th-sortable" t-on-click="() => this.toggleSort('quantity')">
                                            Adet <i t-attf-class="fa {{sortIcon('quantity')}}"></i>
                                        </th>
                                        <th>Kaynak → Hedef</th>
                                        <th>Referans</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <t t-foreach="paginatedMovements" t-as="m" t-key="m.id">
                                        <tr t-attf-class="{{m.move_type === 'incoming' ? 'ub-move-row-in' : m.move_type === 'outgoing' ? 'ub-move-row-out' : 'ub-move-row-int'}}"
                                            t-on-click="() => this.showDetail(m)">
                                            <td style="white-space:nowrap; font-size:0.82rem;" t-esc="m.date"/>
                                            <td>
                                                <div style="font-weight:500; font-size:0.85rem;" t-esc="m.product_name"/>
                                                <div class="ub-barcode-cell" t-esc="m.product_barcode"/>
                                            </td>
                                            <td>
                                                <span t-attf-class="badge {{m.move_type === 'incoming' ? 'ub-badge-in' : m.move_type === 'outgoing' ? 'ub-badge-out' : 'ub-badge-int'}}"
                                                      t-esc="m.move_type_label"/>
                                            </td>
                                            <td class="text-center">
                                                <strong t-attf-class="{{m.move_type === 'outgoing' ? 'text-danger' : 'text-success'}}"
                                                        t-esc="(m.move_type === 'outgoing' ? '-' : '+') + m.quantity"/>
                                            </td>
                                            <td style="font-size:0.78rem; color:#666;">
                                                <t t-esc="shortLoc(m.source)"/> → <t t-esc="shortLoc(m.destination)"/>
                                            </td>
                                            <td>
                                                <span t-if="m.picking_name" class="badge" style="background:#e9ecef;color:#333;font-size:0.72rem;" t-esc="m.picking_name"/>
                                            </td>
                                        </tr>
                                    </t>
                                </tbody>
                            </table>
                        </div>

                        <!-- PAGINATION -->
                        <div class="ub-table-pagination">
                            <span class="ub-page-info">
                                <t t-esc="paginationInfo"/>
                            </span>
                            <div class="ub-page-btns">
                                <button class="btn btn-sm btn-outline-secondary" t-att-disabled="state.page &lt;= 1"
                                        t-on-click="() => this.state.page--">
                                    <i class="fa fa-chevron-left"></i> Önceki
                                </button>
                                <span class="ub-page-current" t-esc="state.page + ' / ' + totalPages"/>
                                <button class="btn btn-sm btn-outline-secondary" t-att-disabled="state.page &gt;= totalPages"
                                        t-on-click="() => this.state.page++">
                                    Sonraki <i class="fa fa-chevron-right"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                </t>

                <div class="ub-no-stock" t-if="!state.result.movements.length">
                    <i class="fa fa-inbox"></i>
                    <p>Bu dönemde hareket bulunamadı</p>
                </div>
            </t>

            <!-- DETAY MODAL -->
            <t t-if="state.detailItem">
                <div class="ub-detail-overlay" t-on-click="closeDetail">
                    <div class="ub-detail-card" t-on-click.stop="">
                        <div class="ub-detail-header">
                            <span><i class="fa fa-info-circle"></i> Hareket Detayı</span>
                            <button class="ub-camera-close-btn" style="width:32px;height:32px;font-size:1rem;" t-on-click="closeDetail">✕</button>
                        </div>
                        <div class="ub-detail-body">
                            <div class="ub-shelf-detail-row">
                                <span class="ub-shelf-detail-label">Ürün:</span>
                                <strong t-esc="state.detailItem.product_name"/>
                            </div>
                            <div class="ub-shelf-detail-row">
                                <span class="ub-shelf-detail-label">Barkod:</span>
                                <span class="ub-barcode-cell" t-esc="state.detailItem.product_barcode"/>
                            </div>
                            <div class="ub-shelf-detail-row" t-if="state.detailItem.product_code">
                                <span class="ub-shelf-detail-label">Ürün Kodu:</span>
                                <span t-esc="state.detailItem.product_code"/>
                            </div>
                            <div class="ub-shelf-detail-row">
                                <span class="ub-shelf-detail-label">Tarih:</span>
                                <span t-esc="state.detailItem.date"/>
                            </div>
                            <div class="ub-shelf-detail-row">
                                <span class="ub-shelf-detail-label">Hareket Tipi:</span>
                                <span t-attf-class="badge {{state.detailItem.move_type === 'incoming' ? 'ub-badge-in' : state.detailItem.move_type === 'outgoing' ? 'ub-badge-out' : 'ub-badge-int'}}"
                                      t-esc="state.detailItem.move_type_label"/>
                            </div>
                            <div class="ub-shelf-detail-row">
                                <span class="ub-shelf-detail-label">Adet:</span>
                                <strong t-esc="state.detailItem.quantity + ' ' + (state.detailItem.uom || 'Adet')"/>
                            </div>
                            <div class="ub-shelf-detail-row">
                                <span class="ub-shelf-detail-label">Kaynak:</span>
                                <span t-esc="state.detailItem.source"/>
                            </div>
                            <div class="ub-shelf-detail-row">
                                <span class="ub-shelf-detail-label">Hedef:</span>
                                <span t-esc="state.detailItem.destination"/>
                            </div>
                            <div class="ub-shelf-detail-row" t-if="state.detailItem.picking_name">
                                <span class="ub-shelf-detail-label">Referans:</span>
                                <span t-esc="state.detailItem.picking_name"/>
                            </div>
                        </div>
                    </div>
                </div>
            </t>
        </div>
    `;

    static props = { navigate: Function, scanner: Object };

    setup() {
        this.state = useState({
            days: 7,
            moveType: 'all',
            productBarcode: '',
            loading: false,
            error: null,
            result: null,
            tableSearch: '',
            sortField: 'date',
            sortAsc: false,
            page: 1,
            pageSize: 20,
            detailItem: null,
        });
        this._unsub = this.props.scanner.onScan(bc => {
            this.state.productBarcode = bc;
            this.loadMovements();
        });
        this.loadMovements();
    }

    // ─── COMPUTED ──────────────────────────────────
    get filteredMovements() {
        if (!this.state.result) return [];
        let list = [...this.state.result.movements];
        // Tablo içi arama
        if (this.state.tableSearch.trim()) {
            const q = this.state.tableSearch.toLowerCase();
            list = list.filter(m =>
                (m.product_name || '').toLowerCase().includes(q) ||
                (m.product_barcode || '').toLowerCase().includes(q) ||
                (m.picking_name || '').toLowerCase().includes(q) ||
                (m.move_type_label || '').toLowerCase().includes(q) ||
                (m.reference || '').toLowerCase().includes(q)
            );
        }
        // Sıralama
        const field = this.state.sortField;
        const asc = this.state.sortAsc;
        list.sort((a, b) => {
            let va = a[field], vb = b[field];
            if (field === 'quantity') { va = Number(va); vb = Number(vb); }
            if (va < vb) return asc ? -1 : 1;
            if (va > vb) return asc ? 1 : -1;
            return 0;
        });
        return list;
    }

    get totalPages() {
        return Math.max(1, Math.ceil(this.filteredMovements.length / this.state.pageSize));
    }

    get paginatedMovements() {
        const start = (this.state.page - 1) * this.state.pageSize;
        return this.filteredMovements.slice(start, start + this.state.pageSize);
    }

    get paginationInfo() {
        const total = this.filteredMovements.length;
        if (!total) return '0 kayıt';
        const start = (this.state.page - 1) * this.state.pageSize + 1;
        const end = Math.min(this.state.page * this.state.pageSize, total);
        return `${start}-${end} / ${total} kayıt`;
    }

    // ─── YARDIMCILAR ──────────────────────────────
    shortLoc(name) {
        if (!name) return '';
        const parts = name.split('/');
        return parts.length > 2 ? parts.slice(-2).join('/') : name;
    }

    sortIcon(field) {
        if (this.state.sortField !== field) return 'fa-sort';
        return this.state.sortAsc ? 'fa-sort-asc' : 'fa-sort-desc';
    }

    toggleSort(field) {
        if (this.state.sortField === field) {
            this.state.sortAsc = !this.state.sortAsc;
        } else {
            this.state.sortField = field;
            this.state.sortAsc = true;
        }
        this.state.page = 1;
    }

    // ─── EVENTS ───────────────────────────────────
    onDaysChange(ev) { this.state.days = ev.target.value; }
    onTypeChange(ev) { this.state.moveType = ev.target.value; }

    onKeyDown(ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); this.loadMovements(); }
    }

    clearFilters() {
        this.state.days = 7;
        this.state.moveType = 'all';
        this.state.productBarcode = '';
        this.state.tableSearch = '';
        this.state.page = 1;
        this.loadMovements();
    }

    showDetail(m) { this.state.detailItem = m; }
    closeDetail() { this.state.detailItem = null; }

    // ─── DATA ─────────────────────────────────────
    async loadMovements() {
        this.state.loading = true;
        this.state.error = null;
        this.state.result = null;
        this.state.page = 1;
        try {
            const result = await BarcodeService.stockMovements(
                this.state.days, this.state.productBarcode.trim(), this.state.moveType);
            if (result.error) this.state.error = result.error;
            else this.state.result = result;
        } catch (e) {
            this.state.error = 'Bağlantı hatası: ' + (e.message || e);
        }
        this.state.loading = false;
    }

    // ─── KAMERA ───────────────────────────────────
    cameraScan() {
        if (!('BarcodeDetector' in window)) {
            alert('Bu tarayıcı kamera ile barkod okumayı desteklemiyor.');
            return;
        }
        const overlay = document.createElement('div');
        overlay.className = 'ub-camera-overlay';
        overlay.innerHTML = `
            <div class="ub-camera-header">
                <span>Ürün barkodunu gösterin...</span>
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
            statusEl.textContent = 'Ürün barkodunu gösterin...';
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
                        this.state.productBarcode = barcodes[0].rawValue;
                        this.loadMovements();
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
