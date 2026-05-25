/** @odoo-module **/

import { Component, useState, xml, onMounted, onWillUnmount } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";
import { speak, vibrate, vibrateError } from "../sound_utils";

export class BatchPickingScreen extends Component {
    static template = xml`
        <div class="ub-screen bp-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="goBack">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-list-ol"></i> Rota Toplama
                </h2>
            </div>

            <!-- ═══ GÖRÜNÜM 1: ROTA LİSTESİ ═══ -->
            <t t-if="state.view === 'list'">
                <t t-if="state.loading">
                    <div class="ub-loading"><i class="fa fa-spinner fa-spin fa-2x"></i><p>Yükleniyor...</p></div>
                </t>
                <div class="bp-list-container" t-if="!state.loading">
                    <!-- ─── FİLTRE BARI ─── -->
                    <div class="bp-filter-bar">
                        <!-- Satır 1: Durum pilleri + Arama -->
                        <div class="bp-filter-row">
                            <div class="bp-filter-pills">
                                <button t-attf-class="bp-pill {{state.filterState === 'all' ? 'bp-pill-active' : ''}}"
                                        t-on-click="() => this.setFilter('all')">
                                    <i class="fa fa-th-list"></i> Tümü
                                    <span class="bp-pill-count" t-esc="state.stateCounts.draft + state.stateCounts.in_progress + state.stateCounts.done"/>
                                </button>
                                <button t-attf-class="bp-pill bp-pill-draft {{state.filterState === 'draft' ? 'bp-pill-active' : ''}}"
                                        t-on-click="() => this.setFilter('draft')">
                                    <i class="fa fa-pencil"></i> Taslak
                                    <span class="bp-pill-count" t-esc="state.stateCounts.draft"/>
                                </button>
                                <button t-attf-class="bp-pill bp-pill-progress {{state.filterState === 'in_progress' ? 'bp-pill-active' : ''}}"
                                        t-on-click="() => this.setFilter('in_progress')">
                                    <i class="fa fa-spinner"></i> Devam
                                    <span class="bp-pill-count" t-esc="state.stateCounts.in_progress"/>
                                </button>
                                <button t-attf-class="bp-pill bp-pill-done {{state.filterState === 'done' ? 'bp-pill-active' : ''}}"
                                        t-on-click="() => this.setFilter('done')">
                                    <i class="fa fa-check"></i> Tamamlandı
                                    <span class="bp-pill-count" t-esc="state.stateCounts.done"/>
                                </button>
                            </div>
                            <div class="bp-filter-search">
                                <i class="fa fa-search"></i>
                                <input type="text" class="bp-search-input" placeholder="Rota veya depo ara..."
                                       t-att-value="state.searchText"
                                       t-on-input="(ev) => this.onSearch(ev.target.value)"/>
                                <button class="bp-search-clear" t-if="state.searchText"
                                        t-on-click="() => this.onSearch('')">
                                    <i class="fa fa-times"></i>
                                </button>
                            </div>
                        </div>
                        <!-- Satır 2: Mağaza + Tarih filtreleri -->
                        <div class="bp-filter-row bp-filter-advanced">
                            <div class="bp-filter-group">
                                <label class="bp-filter-label"><i class="fa fa-building"></i> Mağaza</label>
                                <select class="bp-filter-select" t-on-change="(ev) => this.setWarehouse(ev.target.value)">
                                    <option value="">Tüm Mağazalar</option>
                                    <t t-foreach="state.warehouses" t-as="wh" t-key="wh">
                                        <option t-att-value="wh" t-att-selected="state.filterWarehouse === wh" t-esc="wh"/>
                                    </t>
                                </select>
                            </div>
                            <div class="bp-filter-group">
                                <label class="bp-filter-label"><i class="fa fa-calendar"></i> Başlangıç</label>
                                <input type="date" class="bp-filter-date"
                                       t-att-value="state.filterDateFrom"
                                       t-on-change="(ev) => this.setDateFrom(ev.target.value)"/>
                            </div>
                            <div class="bp-filter-group">
                                <label class="bp-filter-label"><i class="fa fa-calendar"></i> Bitiş</label>
                                <input type="date" class="bp-filter-date"
                                       t-att-value="state.filterDateTo"
                                       t-on-change="(ev) => this.setDateTo(ev.target.value)"/>
                            </div>
                            <button class="bp-filter-clear-btn" t-if="state.filterWarehouse || state.filterDateFrom || state.filterDateTo"
                                    t-on-click="clearAdvancedFilters">
                                <i class="fa fa-times-circle"></i> Temizle
                            </button>
                        </div>
                    </div>

                    <!-- ─── SONUÇ SAYISI ─── -->
                    <div class="bp-list-info">
                        <span><t t-esc="state.batches.length"/> rota listeleniyor</span>
                    </div>

                    <!-- ─── TABLO BAŞLIĞI ─── -->
                    <div class="bp-table" t-if="state.batches.length">
                        <div class="bp-table-head">
                            <span class="bp-col-name">Rota</span>
                            <span class="bp-col-wh">Depo</span>
                            <span class="bp-col-time">Zaman</span>
                            <span class="bp-col-orders">Sipariş</span>
                            <span class="bp-col-items">Ürün</span>
                            <span class="bp-col-state">Durum</span>
                            <span class="bp-col-action"></span>
                        </div>
                        <t t-foreach="state.batches" t-as="b" t-key="b.id">
                            <div t-attf-class="bp-table-row bp-table-row-{{b.state}}" t-on-click="() => this.selectBatch(b.id)">
                                <span class="bp-col-name">
                                    <strong t-esc="b.name"/>
                                    <small class="bp-batch-type" t-esc="b.batch_type"/>
                                </span>
                                <span class="bp-col-wh">
                                    <span class="bp-wh-tag" t-if="b.warehouse_name" t-esc="b.warehouse_name"/>
                                </span>
                                <span class="bp-col-time">
                                    <span t-esc="b.time_window"/>
                                    <small class="bp-date-sub" t-if="b.date_display" t-esc="b.date_display"/>
                                </span>
                                <span class="bp-col-orders">
                                    <i class="fa fa-shopping-cart"></i> <t t-esc="b.total_orders"/>
                                </span>
                                <span class="bp-col-items">
                                    <i class="fa fa-cube"></i> <t t-esc="b.total_items"/>
                                </span>
                                <span class="bp-col-state">
                                    <span t-attf-class="bp-state-tag bp-state-{{b.state}}"
                                          t-esc="b.state === 'draft' ? 'Taslak' : b.state === 'in_progress' ? 'Devam' : 'Tamamlandı'"/>
                                </span>
                                <span class="bp-col-action">
                                    <button class="btn btn-sm btn-outline-danger" style="margin-right:4px;"
                                            t-if="b.state !== 'done' and state.canDelete"
                                            t-on-click.stop="() => this.deleteBatch(b.id, b.name)">
                                        <i class="fa fa-trash"></i>
                                    </button>
                                    <button t-attf-class="btn btn-sm {{b.state === 'done' ? 'btn-outline-success' : 'btn-success'}} bp-btn-collect">
                                        <i t-attf-class="fa {{b.state === 'done' ? 'fa-eye' : 'fa-play'}}"></i>
                                        <t t-esc="b.state === 'done' ? 'Gör' : 'Topla'"/>
                                    </button>
                                </span>
                            </div>
                        </t>
                    </div>

                    <div class="bp-empty-state" t-if="!state.batches.length">
                        <i class="fa fa-inbox fa-3x"></i>
                        <p t-if="state.filterState !== 'all' || state.searchText">Filtreye uygun rota bulunamadı</p>
                        <p t-else="">Bekleyen rota yok</p>
                        <button class="btn btn-outline-secondary btn-sm" t-if="state.filterState !== 'all' || state.searchText"
                                t-on-click="() => { this.state.filterState = 'all'; this.state.searchText = ''; this.loadBatches(); }">
                            <i class="fa fa-refresh"></i> Filtreleri Temizle
                        </button>
                    </div>
                </div>
            </t>


            <!-- ═══ GÖRÜNÜM 2: RAF YÖNLENDİRMELİ TOPLAMA ═══ -->
            <t t-if="state.view === 'collect'">
                <!-- Üst Bar: Rota adı + İlerleme -->
                <div class="bp-top-bar">
                    <span class="bp-route-name" t-esc="state.batch.name"/>
                    <span class="bp-progress-text">
                        <t t-esc="state.collectedCount"/> / <t t-esc="state.items.length"/>
                    </span>
                </div>

                <!-- İlerleme çubuğu -->
                <div class="bp-progress-bar">
                    <div class="bp-progress-fill" t-attf-style="width: {{state.progressPct}}%"></div>
                </div>

                <t t-if="state.currentItem">
                    <!-- YEŞİL BANT: Lokasyon -->
                    <div class="bp-band bp-band-location">
                        <i class="fa fa-map-marker"></i>
                        <t t-if="state.currentItem.location_parts and state.currentItem.location_parts.zone">
                            <span t-esc="state.currentItem.location_parts.warehouse"/>
                            <span> - </span>
                            <span t-esc="state.currentItem.location_parts.zone"/>
                            <t t-if="state.currentItem.location_parts.section">
                                <span> - </span>
                                <span t-esc="state.currentItem.location_parts.section"/>
                            </t>
                        </t>
                        <t t-else="">
                            <span t-esc="state.currentItem.location || 'Bilinmiyor'"/>
                        </t>
                    </div>

                    <!-- TURUNCU BANT: Göz + Miktar -->
                    <div class="bp-band bp-band-qty">
                        <span class="bp-shelf-label">
                            <t t-if="state.currentItem.location_parts and state.currentItem.location_parts.shelf">
                                Göz: <t t-esc="state.currentItem.location_parts.shelf"/>
                            </t>
                        </span>
                        <span class="bp-qty-label">
                            Adet: <strong t-esc="state.currentItem.collected_qty"/> / <strong t-esc="state.currentItem.demand_qty"/>
                        </span>
                    </div>

                    <!-- Barkod + Marka + Kategori + Renk bilgisi -->
                    <div class="bp-barcode-info">
                        <span>Barkod: <strong t-esc="state.currentItem.barcode"/></span>
                        <t t-if="state.currentItem.brand || state.currentItem.color || state.currentItem.category">
                            <span class="bp-brand-color-info">
                                <t t-if="state.currentItem.brand"><span class="bp-info-tag bp-tag-brand" t-esc="state.currentItem.brand"/></t>
                                <t t-if="state.currentItem.category"><span class="bp-info-tag bp-tag-category" style="background:#e3f2fd; color:#1976d2; margin:0 3px; padding:2px 6px; border-radius:4px; font-size:11px;" t-esc="state.currentItem.category"/></t>
                                <t t-if="state.currentItem.color"><span class="bp-info-tag bp-tag-color" t-esc="state.currentItem.color"/></t>
                            </span>
                        </t>
                    </div>

                    <!-- MOR BANT: Ürün Kodu + Varyant -->
                    <div class="bp-band bp-band-variant">
                        <span t-esc="state.currentItem.default_code"/>
                        <t t-if="state.currentItem.variant_info">
                            <span>, </span>
                            <span t-esc="state.currentItem.variant_info"/>
                        </t>
                    </div>

                    <!-- BARKOD INPUT + BUTONLAR -->
                    <div class="bp-scan-row">
                        <button class="btn btn-danger bp-btn-skip" t-on-click="onSkip">Eksik</button>
                        <div class="ub-barcode-input-group bp-scan-input-wrap" style="flex: 1; margin: 0 5px;">
                            <input type="text" class="form-control ub-barcode-input bp-scan-input"
                                   placeholder="Barkod Okuma"
                                   t-ref="scanInput"
                                   t-on-keydown="onScanKey"
                                   t-att-value="state.scanInput"
                                   t-on-input="(ev) => this.state.scanInput = ev.target.value"/>
                            <button class="ub-scan-icon-btn" t-on-click="startCameraScan" title="Kamera ile tara">
                                <i class="fa fa-barcode"></i>
                            </button>
                        </div>
                        <button class="btn btn-warning bp-btn-go" t-on-click="onScan">
                            <i class="fa fa-arrow-right"></i>
                        </button>
                        <button class="btn btn-info bp-btn-product" t-on-click="goToProduct" title="Ürüne Git">
                            <i class="fa fa-external-link"></i>
                        </button>
                    </div>

                    <!-- Tarama sonucu mesajı -->
                    <t t-if="state.scanMsg">
                        <div t-attf-class="bp-scan-feedback {{state.scanOk ? 'bp-scan-ok' : 'bp-scan-fail'}}">
                            <i t-attf-class="fa {{state.scanOk ? 'fa-check-circle' : 'fa-times-circle'}}"></i>
                            <span t-esc="state.scanMsg"/>
                        </div>
                    </t>

                    <!-- ÜRÜN GÖRSELİ -->
                    <div class="bp-product-image">
                        <img t-att-src="state.currentItem.image_url" alt="Ürün" loading="lazy"
                             t-on-error="onImageError"
                             t-on-click="onImageClick"/>
                    </div>

                    <!-- SAĞ PANEL: Rota Listesi Tablosu -->
                    <div class="bp-route-table">
                        <div class="bp-route-table-header">
                            <span>Barkod</span>
                            <span>Marka</span>
                            <span>Kategori</span>
                            <span>Renk</span>
                            <span>Beden</span>
                            <span>Sokak</span>
                            <span>Kat-Göz</span>
                            <span>Adet</span>
                            <span>Top.</span>
                        </div>
                        <t t-foreach="state.items" t-as="item" t-key="item.move_id">
                            <div t-attf-class="bp-route-table-row {{item.move_id === state.currentItem?.move_id ? 'bp-row-active' : ''}} {{item.collected_qty >= item.demand_qty ? 'bp-row-done' : ''}}"
                                 t-on-click="() => this.selectItem(item)">
                                <span class="bp-cell-barcode bp-barcode-copy" t-att-data-barcode="item.barcode || ''" t-on-click.stop="(ev) => this.copyBarcode(ev)" t-esc="item.barcode || ''"/>
                                <span class="bp-cell-brand" t-esc="item.brand || '-'"/>
                                <span class="bp-cell-category" t-esc="item.category || '-'"/>
                                <span class="bp-cell-color" t-esc="item.color || '-'"/>
                                <span class="bp-cell-size" t-esc="item.size || '-'"/>
                                <span t-esc="(item.location_parts || {}).zone || '-'"/>
                                <span>
                                    <t t-esc="(item.location_parts || {}).section || ''"/>
                                    <t t-if="(item.location_parts || {}).shelf"> - <t t-esc="item.location_parts.shelf"/></t>
                                </span>
                                <span t-esc="item.demand_qty"/>
                                <span class="d-flex justify-content-between align-items-center">
                                    <t t-esc="item.collected_qty"/>
                                    <button class="btn btn-sm text-danger p-0 ms-1" t-if="item.collected_qty > 0" t-on-click.stop="() => this.onDecreaseQty(item)">
                                        <i class="fa fa-minus-circle"></i>
                                    </button>
                                </span>
                            </div>
                        </t>
                    </div>
                </t>

                <!-- Tümü toplandı -->
                <t t-if="!state.currentItem and state.items.length">
                    <div class="bp-all-done">
                        <i class="fa fa-check-circle fa-3x"></i>
                        <h3>Tüm Ürünler Toplandı!</h3>
                        <p t-esc="state.collectedCount + '/' + state.items.length + ' ürün'"/>
                        <button class="btn btn-success btn-lg" t-on-click="onComplete">
                            <i class="fa fa-flag-checkered"></i> Toplamayı Tamamla
                        </button>
                    </div>
                </t>
            </t>

            <!-- ═══ GÖRÜNÜM 3: ÖZET ═══ -->
            <t t-if="state.view === 'summary'">
                <div class="bp-summary">
                    <div class="bp-summary-icon">
                        <i class="fa fa-check-circle"></i>
                    </div>
                    <h3>Toplama Tamamlandı</h3>
                    <div class="bp-summary-stats">
                        <div class="bp-stat">
                            <span class="bp-stat-value" t-esc="state.summary.collected_moves"/>
                            <span class="bp-stat-label">Toplanan</span>
                        </div>
                        <div class="bp-stat bp-stat-warn" t-if="state.summary.skipped_moves > 0">
                            <span class="bp-stat-value" t-esc="state.summary.skipped_moves"/>
                            <span class="bp-stat-label">Eksik</span>
                        </div>
                        <div class="bp-stat bp-stat-partial" t-if="state.summary.partial_moves > 0">
                            <span class="bp-stat-value" t-esc="state.summary.partial_moves"/>
                            <span class="bp-stat-label">Kısmi</span>
                        </div>
                    </div>
                    <p class="bp-summary-msg" t-esc="state.summary.message"/>
                    <div class="bp-summary-actions">
                        <button class="btn btn-primary btn-lg" t-on-click="() => this.props.navigate('packing')">
                            <i class="fa fa-gift"></i> Paketlemeye Git
                        </button>
                        <button class="btn btn-outline-secondary btn-lg" t-on-click="() => { this.state.view = 'list'; this.loadBatches(); }">
                            <i class="fa fa-arrow-left"></i> Listeye Dön
                        </button>
                    </div>
                </div>
            </t>

            <t t-if="state.error">
                <div class="ub-error-card"><i class="fa fa-exclamation-triangle"></i><p t-esc="state.error"/></div>
            </t>
        </div>
    `;

    static props = { navigate: Function, scanner: Object };

    setup() {
        this.state = useState({
            view: 'list',
            loading: false,
            error: null,
            batches: [],
            batch: null,
            items: [],
            currentItem: null,
            currentIndex: 0,
            collectedCount: 0,
            progressPct: 0,
            scanInput: '',
            scanMsg: '',
            scanOk: false,
            summary: null,
            // ── Filtre alanları ──
            filterState: 'draft',
            searchText: '',
            filterWarehouse: '',
            filterDateFrom: '',
            filterDateTo: '',
            warehouses: [],
            stateCounts: { draft: 0, in_progress: 0, done: 0 },
            canDelete: false,
        });

        // ── Filtreleri localStorage'dan yükle (günlük cache) ──
        this._loadFiltersFromCache();

        this._searchTimer = null;

        this._onPopState = (ev) => {
            const state = ev.state || {};
            if (state.ubScreen === 'batch_picking') {
                const targetView = state.bpView || 'list';
                if (this.state.view !== targetView) {
                    this.state.view = targetView;
                    if (targetView === 'list') {
                        this.loadBatches();
                    }
                }
            }
        };

        this._unsub = this.props.scanner.onScan(bc => {
            if (this.state.view === 'collect') {
                this.state.scanInput = bc;
                this.onScan();
            }
        });

        onMounted(() => {
            window.addEventListener('popstate', this._onPopState);
            this.loadBatches();
        });

        onWillUnmount(() => {
            if (this._unsub) this._unsub();
            window.removeEventListener('popstate', this._onPopState);
        });
    }

    goBack() {
        if (this.state.view === 'collect' || this.state.view === 'summary') {
            history.back(); // Tarayıcı geri tuşunu simüle et, _onPopState yakalayacak
        } else {
            this.props.navigate('main');
        }
    }

    // ═══ FİLTRE & SİLME ═══
    setFilter(filterState) {
        this.state.filterState = filterState;
        this._saveFiltersToCache();
        this.loadBatches();
    }

    onSearch(text) {
        this.state.searchText = text;
        this._saveFiltersToCache();
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => this.loadBatches(), 350);
    }

    setWarehouse(value) {
        this.state.filterWarehouse = value;
        this._saveFiltersToCache();
        this.loadBatches();
    }

    setDateFrom(value) {
        this.state.filterDateFrom = value;
        this._saveFiltersToCache();
        this.loadBatches();
    }

    setDateTo(value) {
        this.state.filterDateTo = value;
        this._saveFiltersToCache();
        this.loadBatches();
    }

    clearAdvancedFilters() {
        this.state.filterWarehouse = '';
        this.state.filterDateFrom = '';
        this.state.filterDateTo = '';
        this._saveFiltersToCache();
        this.loadBatches();
    }

    // ═══ FİLTRE CACHE (localStorage — günlük expiry) ═══
    _filterCacheKey = 'bp_filters';

    _saveFiltersToCache() {
        try {
            const today = new Date().toISOString().slice(0, 10);
            const data = {
                filterState: this.state.filterState,
                searchText: this.state.searchText,
                filterWarehouse: this.state.filterWarehouse,
                filterDateFrom: this.state.filterDateFrom,
                filterDateTo: this.state.filterDateTo,
                _date: today,
            };
            localStorage.setItem(this._filterCacheKey, JSON.stringify(data));
        } catch (e) { /* quota / private mode */ }
    }

    _loadFiltersFromCache() {
        try {
            const raw = localStorage.getItem(this._filterCacheKey);
            if (!raw) return;
            const data = JSON.parse(raw);
            const today = new Date().toISOString().slice(0, 10);
            // Günlük expiry: farklı günse temizle
            if (data._date !== today) {
                localStorage.removeItem(this._filterCacheKey);
                return;
            }
            if (data.filterState) this.state.filterState = data.filterState;
            if (data.searchText) this.state.searchText = data.searchText;
            if (data.filterWarehouse) this.state.filterWarehouse = data.filterWarehouse;
            if (data.filterDateFrom) this.state.filterDateFrom = data.filterDateFrom;
            if (data.filterDateTo) this.state.filterDateTo = data.filterDateTo;
        } catch (e) { /* parse error / private mode */ }
    }

    async deleteBatch(batchId, batchName) {
        if (!confirm(`"${batchName}" rotasını silmek istediğinize emin misiniz?`)) return;
        
        this.state.loading = true;
        try {
            const res = await BarcodeService.call('/ugurlar_barcode/api/batch_delete', { batch_id: batchId });
            if (res.error) {
                alert(res.error);
            } else {
                this.loadBatches();
            }
        } catch (e) {
            alert('Silme işlemi başarısız');
        }
        this.state.loading = false;
    }

    // ═══ LİSTE ═══
    async loadBatches() {
        this.state.loading = true;
        try {
            const res = await BarcodeService.call('/ugurlar_barcode/api/batch_list', {
                filter_state: this.state.filterState,
                search: this.state.searchText,
                warehouse: this.state.filterWarehouse,
                date_from: this.state.filterDateFrom,
                date_to: this.state.filterDateTo,
            });
            this.state.batches = res.batches || [];
            if (res.state_counts) {
                this.state.stateCounts = res.state_counts;
            }
            if (res.warehouses) {
                this.state.warehouses = res.warehouses;
            }
            if (res.can_delete !== undefined) {
                this.state.canDelete = res.can_delete;
            }
        } catch (e) {
            this.state.error = 'Yükleme hatası';
        }
        this.state.loading = false;
    }

    // ═══ BATCH SEÇ ve TOPLAMA BAŞLAT ═══
    async selectBatch(batchId) {
        this.state.loading = true;
        this.state.error = null;
        try {
            const res = await BarcodeService.batchRouteItems(batchId);
            if (res.error) {
                this.state.error = res.error;
                this.state.loading = false;
                speak('batch_route_not_found');
                return;
            }
            this.state.batch = res.batch;
            this.state.items = res.items || [];
            this._updateProgress();
            this._goToNextItem();
            this.state.view = 'collect';
            speak('batch_route_found');
            
            // Sub-state ekle (Geri tuşu listeye dönsün diye)
            history.pushState(Object.assign({}, history.state, { bpView: 'collect' }), '');
        } catch (e) {
            this.state.error = 'Rota yüklenirken hata oluştu';
            speak('batch_error');
        }
        this.state.loading = false;
    }

    // ═══ SONRAKI ÜRÜNE GEÇ ═══
    _goToNextItem() {
        const items = this.state.items;
        // İlk tamamlanmamış ürünü bul
        let nextIdx = items.findIndex(i => i.collected_qty < i.demand_qty);
        if (nextIdx >= 0) {
            this.state.currentIndex = nextIdx;
            this.state.currentItem = items[nextIdx];
        } else {
            this.state.currentItem = null; // Tümü toplandı
            // ─── OTOMATİK TAMAMLA ───
            // Tüm ürünler toplandığında otomatik doğrula
            setTimeout(() => this.onComplete(), 800);
        }
        this.state.scanInput = '';
        this.state.scanMsg = '';

        // Input'a fokus
        setTimeout(() => {
            const inp = document.querySelector('.bp-scan-input');
            if (inp) inp.focus();
        }, 100);
    }

    // ═══ MANUEL ÜRÜN SEÇ ═══
    selectItem(item) {
        if (!item || item.collected_qty >= item.demand_qty) return;
        const idx = this.state.items.findIndex(i => i.move_id === item.move_id);
        if (idx >= 0) {
            this.state.currentIndex = idx;
            this.state.currentItem = item;
            this.state.scanInput = '';
            this.state.scanMsg = '';
            
            // Input'a fokus
            setTimeout(() => {
                const inp = document.querySelector('.bp-scan-input');
                if (inp) inp.focus();
            }, 100);
        }
    }

    _updateProgress() {
        const items = this.state.items;
        const collected = items.filter(i => i.collected_qty >= i.demand_qty).length;
        this.state.collectedCount = collected;
        this.state.progressPct = items.length ? Math.round((collected / items.length) * 100) : 0;
    }

    // ═══ BARKOD TARA ═══
    onScanKey(ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); this.onScan(); }
    }

    async onScan() {
        const barcode = (this.state.scanInput || '').trim();
        if (!barcode) return;

        this.state.scanMsg = '';
        try {
            const res = await BarcodeService.batchCollectScan(this.state.batch.id, barcode);

            if (res.error) {
                this.state.scanMsg = res.error;
                this.state.scanOk = false;
                speak('batch_scan_wrong');
                this._vibrate(200);
            } else if (res.warning) {
                this.state.scanMsg = res.message;
                this.state.scanOk = true;
                speak('batch_scan_wrong');
            } else {
                this.state.scanMsg = `✓ ${res.product_name} — ${res.collected_qty}/${res.demand_qty}`;
                this.state.scanOk = true;
                speak('batch_scan_success');

                // İlgili satırı güncelle
                for (const item of this.state.items) {
                    if (item.move_id === res.move_id) {
                        item.collected_qty = res.collected_qty;
                        break;
                    }
                }

                this._updateProgress();

                // Mevcut ürün tamamlandıysa sonrakine geç
                if (res.item_complete) {
                    setTimeout(() => this._goToNextItem(), 600);
                }

                // Tüm rota tamamlandıysa
                if (res.all_collected) {
                    this.state.scanMsg = '🎉 Tüm ürünler toplandı!';
                    speak('batch_all_collected');
                    setTimeout(() => {
                        this.state.currentItem = null;
                    }, 1000);
                }
            }
        } catch (e) {
            this.state.scanMsg = 'Tarama hatası';
            this.state.scanOk = false;
            speak('batch_error');
        }

        this.state.scanInput = '';
    }

    // ═══ MİKTAR AZALTMA (UNDO) ═══
    async onDecreaseQty(item) {
        if (!confirm('Bu ürünün toplanan miktarını 1 azaltmak istediğinize emin misiniz?')) return;
        this.state.loading = true;
        
        try {
            const res = await BarcodeService.call('/ugurlar_barcode/api/batch_undo', {
                move_id: item.move_id,
            });
            if (res.error) {
                this.state.scanMsg = res.error;
                this.state.scanOk = false;
                speak('batch_error');
            } else {
                this.state.scanMsg = res.message;
                this.state.scanOk = true;
                speak('batch_scan_success');
                
                // Miktarı UI kısmında da güncelle
                item.collected_qty -= 1;
                this._updateProgress();
                
                // Eğer ürün geri alınarak bitmemiş hale geldiyse, aktif ürünü ona çek
                if (item.collected_qty < item.demand_qty) {
                    this.state.currentItem = item;
                    // Eğer currentItem yokken (hepsi bittiyken) iptal edildiyse, currentItem olarak ata
                    if (!this.state.currentItem) {
                        this.state.currentItem = item;
                    }
                }
            }
        } catch (e) {
            this.state.scanMsg = 'Bağlantı hatası';
            this.state.scanOk = false;
        }
        
        this.state.loading = false;
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
                <span>Barkodu kameraya gösterin...</span>
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
            statusEl.textContent = 'Barkodu kameraya gösterin...';
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
                        this.state.scanInput = barcodes[0].rawValue;
                        this.onScan();
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

    // ═══ EKSİK / ATLA ═══
    onSkip() {
        if (!this.state.currentItem) return;
        // Mevcut ürünün collected_qty'sini demand_qty'ye eşitle ama "eksik" olarak işaretle
        // Basitçe sonraki ürüne geçiyor
        const item = this.state.currentItem;
        this.state.scanMsg = `⏭ ${item.display_name || item.product_name} atlandı (eksik)`;
        this.state.scanOk = false;

        // Atla: demand_qty'yi collected_qty'ye set et ki sıralama karışmasın
        // Ama bunu yaparsak stok hatalı olur, sadece UI'da geç
        item.collected_qty = item.demand_qty; // UI'da tamamlanmış göster
        this._updateProgress();
        setTimeout(() => this._goToNextItem(), 400);
    }

    // ═══ TOPLAMA TAMAMLA ═══
    async onComplete() {
        this.state.loading = true;
        try {
            const res = await BarcodeService.batchCollectComplete(this.state.batch.id);
            if (res.error) {
                this.state.error = res.error;
            } else {
                this.state.summary = res;
                this.state.view = 'summary';
                speak('batch_complete');
                
                // Sub-state güncelle (Geri tuşu listeye dönsün diye)
                history.replaceState(Object.assign({}, history.state, { bpView: 'summary' }), '');
            }
        } catch (e) {
            this.state.error = 'Tamamlama hatası';
        }
        this.state.loading = false;
    }


    // ═══ ÜRÜNE GİT ═══
    goToProduct() {
        if (!this.state.currentItem) return;
        // /odoo/inventory/products/ sayfası product.template ID bekler (varyant değil!)
        const tmplId = this.state.currentItem.product_tmpl_id;
        if (!tmplId) return;
        const url = `/odoo/inventory/products/${tmplId}`;
        window.open(url, '_blank');
    }

    // ═══ YARDIMCI ═══
    _vibrate(ms) {
        try { if (navigator.vibrate) navigator.vibrate(ms); } catch (e) {}
    }

    onImageError(ev) {
        ev.target.src = '/web/static/img/placeholder.png';
    }

    onImageClick(ev) {
        const imgSrc = ev.target.src;
        if (!imgSrc || imgSrc.includes('placeholder')) return;

        // Büyük boyut adayları (en büyükten küçüğe dene)
        const sizes = ['image_1920', 'image_512', 'image_256'];
        const candidates = sizes
            .map(s => imgSrc.replace(/image_\d+/, s))
            .filter(url => url !== imgSrc);
        candidates.push(imgSrc); // son çare: orijinal küçük resim

        const overlay = document.createElement('div');
        overlay.className = 'bp-lightbox-overlay';
        overlay.innerHTML = `
            <button class="bp-lightbox-close">✕</button>
            <img alt="Ürün Görseli"/>
        `;

        const close = () => {
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        };

        overlay.querySelector('.bp-lightbox-close').onclick = (e) => { e.stopPropagation(); close(); };
        overlay.onclick = close;

        const lbImg = overlay.querySelector('img');
        lbImg.onclick = (e) => e.stopPropagation();

        // Sırayla dene: yüklenemeyen boyutu atla, sonrakini dene
        let tryIdx = 0;
        const tryNext = () => {
            if (tryIdx >= candidates.length) {
                close(); // hiçbiri yüklenemezse kapat
                return;
            }
            lbImg.src = candidates[tryIdx++];
        };
        lbImg.onerror = tryNext;
        tryNext();

        document.body.appendChild(overlay);
    }

    copyBarcode(ev) {
        const el = ev.currentTarget;
        if (!el) return;
        const barcode = el.dataset.barcode;
        if (!barcode) return;
        const origText = el.textContent;

        const showCopied = () => {
            el.classList.add('bp-copied');
            el.textContent = '✓ Kopyalandı';
            setTimeout(() => {
                el.textContent = origText;
                el.classList.remove('bp-copied');
            }, 1200);
        };

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(barcode).then(showCopied).catch(() => {
                this._fallbackCopy(barcode);
                showCopied();
            });
        } else {
            this._fallbackCopy(barcode);
            showCopied();
        }
    }

    _fallbackCopy(text) {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
    }

}
