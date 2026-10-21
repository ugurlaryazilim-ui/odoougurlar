/** @odoo-module **/

import { Component, useState, xml, onMounted, onWillUnmount, useRef, onPatched } from "@odoo/owl";
import { escapeHtml, safeNum, safeColor, safeWeight, safeAlign } from "../utils/html";
import { BarcodeService, AudioFeedback } from "../barcode_service";
import { speak, vibrate, vibrateError } from "../sound_utils";
import { generateBarcodeSVG } from "./label_designer";

// Okutma kuyruğu: aynı anda tek istek. Yanıt vermeyen istek kuyruğu kilitlemesin diye süre sınırı var.
const QUEUE_TIMEOUT_MS = 20000;
// Tamamla / Eksik Onayla fatura ve Nebim senkronu içerir: daha uzun süre tanınır
const QUEUE_LONG_TIMEOUT_MS = 90000;
// Zaman aşımına uğramış (veya başka rotaya geçilmiş) görevin geç yanıtı ekrana yazılmaz
class StaleResponse extends Error {}
// Zaman aşımına uğrayıp yanıtı hâlâ beklenen kısa istek üst sınırı: dolunca kuyruk yanıtı bekler
// (uzun iş zaten tektir: yanıtı gelene kadar Tamamla / Eksik Onayla kapalı)
const MAX_ORPHAN_REQUESTS = 2;

export class PackingScreen extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="goBack">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-gift"></i> Paketleme &amp; Faturalama
                </h2>
            </div>

            <!-- ROTA GİRİŞ -->
            <t t-if="state.view === 'search'">
                <div class="ub-search-form">
                    <div class="ub-search-field">
                        <label class="ub-field-label">Rota, Batch veya Barkod</label>
                        <div class="ub-input-group">
                            <input type="text" class="form-control ub-barcode-input"
                                   placeholder="R00215 veya ürün barkodu..."
                                   t-ref="routeInput"
                                   t-on-keydown="onRouteKey"
                                   t-att-value="state.routeInput"
                                   t-on-input="(ev) => this.state.routeInput = ev.target.value"/>
                            <button class="btn btn-primary ub-scan-btn" t-on-click="searchRoute">
                                <i class="fa fa-search"></i>
                            </button>
                        </div>
                    </div>
                    <div style="margin-top:0.5rem;">
                        <button class="btn btn-sm" style="background:#714B67; color:#fff; white-space:nowrap;"
                                t-on-click="() => this.props.navigate('cargo_label_designer')">
                            <i class="fa fa-paint-brush"></i> Kargo Etiketi Tasarla
                        </button>
                    </div>
                </div>

                <!-- FİLTRELER -->
                <div style="background:#f8f9fa; border:1px solid #dee2e6; border-radius:8px; padding:0.6rem 0.8rem; margin-top:0.6rem;">
                    <div style="display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap;">
                        <!-- Durum filtreleri -->
                        <div class="btn-group btn-group-sm" role="group">
                            <button t-att-class="'btn ' + (state.filterState === 'all' ? 'btn-primary' : 'btn-outline-primary')"
                                    t-on-click="() => this.setFilter('all')">
                                <i class="fa fa-th-list"></i> Tümü
                            </button>
                            <button t-att-class="'btn ' + (state.filterState === 'in_progress' ? 'btn-success' : 'btn-outline-success')"
                                    t-on-click="() => this.setFilter('in_progress')">
                                <i class="fa fa-play-circle"></i> Devam
                            </button>
                            <button t-att-class="'btn ' + (state.filterState === 'draft' ? 'btn-warning' : 'btn-outline-warning')"
                                    t-on-click="() => this.setFilter('draft')">
                                <i class="fa fa-pencil"></i> Taslak
                            </button>
                            <button t-att-class="'btn ' + (state.filterState === 'done' ? 'btn-info' : 'btn-outline-info')"
                                    t-on-click="() => this.setFilter('done')">
                                <i class="fa fa-check-circle"></i> Tamamlandı
                            </button>
                        </div>

                        <!-- Tarih filtreleri -->
                        <div style="display:flex; align-items:center; gap:0.3rem; margin-left:auto;">
                            <i class="fa fa-calendar" style="color:#714B67; font-size:0.85rem;"></i>
                            <input type="date" class="form-control form-control-sm"
                                   style="width:130px; font-size:0.8rem; border-color:#ced4da;"
                                   t-att-value="state.filterDateFrom"
                                   t-on-change="(ev) => { this.state.filterDateFrom = ev.target.value; this.loadBatchList(); }"/>
                            <span style="color:#999; font-size:0.75rem;">—</span>
                            <input type="date" class="form-control form-control-sm"
                                   style="width:130px; font-size:0.8rem; border-color:#ced4da;"
                                   t-att-value="state.filterDateTo"
                                   t-on-change="(ev) => { this.state.filterDateTo = ev.target.value; this.loadBatchList(); }"/>
                        </div>
                    </div>
                </div>

                <!-- Rota listesi -->
                <div class="ub-packing-batch-list" t-if="state.batches.length">
                    <div class="ub-section-title-dark" style="margin-top:0.8rem;">
                        <i class="fa fa-list"></i> Rotalar
                        <span class="badge bg-light text-dark" style="margin-left:0.5rem; font-size:0.75rem;"
                              t-esc="state.batches.length + ' rota'"/>
                    </div>
                    <t t-foreach="state.batches" t-as="b" t-key="b.id">
                        <div class="ub-picking-row" t-on-click="() => this.loadBatch(b.id)"
                             t-att-style="b.state === 'done' ? 'opacity:0.7;' : ''">
                            <div class="ub-picking-info">
                                <div class="ub-picking-name" t-esc="b.name"/>
                                <div class="ub-picking-meta">
                                    <span class="badge" style="font-size:0.7rem;"
                                          t-att-class="'badge ' + (b.state === 'done' ? 'bg-success' : b.state === 'in_progress' ? 'bg-info' : 'bg-warning')"
                                          t-esc="b.state === 'done' ? '✓ Tamamlandı' : b.state === 'in_progress' ? '▶ Devam' : '✎ Taslak'"/>
                                    <span class="badge bg-secondary" style="font-size:0.7rem;" t-if="b.time_window"
                                          t-esc="b.time_window"/>
                                </div>
                            </div>
                            <div class="ub-picking-count">
                                <span class="badge bg-primary"
                                      t-esc="b.total_orders + ' sipariş'"/>
                            </div>
                        </div>
                    </t>
                </div>

                <t t-if="state.loading">
                    <div class="ub-loading">
                        <i class="fa fa-spinner fa-spin fa-2x"></i>
                        <p>Yükleniyor...</p>
                    </div>
                </t>
            </t>

            <!-- ÜRÜN LİSTESİ + BARKOD EŞLEŞME -->
            <t t-if="state.view === 'detail'">
                <div class="ub-packing-header">
                    <div class="ub-packing-route-info">
                        <strong t-esc="state.batch.name"/>
                        <span class="badge bg-info ms-2" t-esc="state.batch.time_window"/>
                    </div>
                    <div class="ub-packing-progress">
                        <div class="ub-packing-progress-bar">
                            <div class="ub-packing-progress-fill"
                                 t-attf-style="width: {{progressPct}}%"/>
                        </div>
                        <span class="ub-packing-progress-text"
                              t-esc="state.matched + '/' + state.total + ' ürün eşleşti'"/>
                    </div>
                </div>

                <!-- Barkod tarama -->
                <div class="ub-scan-area" t-att-data-scan-pending="state.scanPending">
                    <t t-if="state.scanPending > 0">
                        <div class="small text-muted mb-1">
                            <i class="fa fa-hourglass-half me-1"></i>Sırada: <t t-esc="state.scanPending"/> işlem
                        </div>
                    </t>
                    <t t-if="state.longOpPending > 0">
                        <div class="small text-warning fw-bold mb-1" data-long-op-pending="1">
                            <i class="fa fa-spinner fa-spin me-1"></i>İşlem sunucuda sürüyor, yanıt bekleniyor. Lütfen bekleyin.
                        </div>
                    </t>
                    <div class="ub-input-group">
                        <input type="text" class="form-control ub-barcode-input"
                               placeholder="Ürün barkodunu okutun..."
                               t-ref="scanInput"
                               t-on-keydown="onScanKey"
                               t-att-value="state.scanInput"
                               t-on-input="(ev) => this.state.scanInput = ev.target.value"/>
                        <button class="btn btn-primary ub-scan-btn" t-on-click="onScan">
                            <i class="fa fa-barcode"></i>
                        </button>
                    </div>
                </div>

                <t t-if="state.scanMsg">
                    <div t-attf-class="ub-scan-feedback {{state.scanOk ? 'ub-scan-ok' : 'ub-scan-fail'}}" style="flex-wrap: wrap;">
                        <div class="d-flex align-items-center w-100 mb-2">
                            <i t-attf-class="fa {{state.scanOk ? 'fa-check' : 'fa-times'}} me-2"></i>
                            <span t-esc="state.scanMsg"/>
                        </div>
                        <t t-if="state.inc_picking_id">
                            <button class="btn btn-warning w-100 fw-bold" t-on-click="() => this.onBackorder(state.inc_picking_id)"
                                    t-att-disabled="state.loading or state.longOpPending">
                                <i class="fa fa-exclamation-triangle"></i> Eksik Onayla (Backorder Yap): <t t-esc="incOrderLabel"/>
                            </button>
                        </t>
                        <t t-if="state.reprintPickingId">
                            <button class="btn btn-info w-100 fw-bold mt-2" t-on-click="() => this.onReprintLabel(state.reprintPickingId)">
                                <i class="fa fa-print"></i> 🖨️ Etiketi Tekrar Yazdır
                            </button>
                        </t>
                    </div>
                </t>

                <!-- Okutulan sipariş: her adet bir görsel (okutulan yeşil, bekleyen kırmızı) -->
                <t t-set="order" t-value="activeOrder"/>
                <div t-if="order" t-attf-class="ub-pk-order {{order.done ? 'ub-pk-order-done' : ''}}">
                    <div class="ub-pk-order-head">
                        <div class="ub-pk-order-title">
                            <i t-attf-class="fa {{order.done ? 'fa-check-circle' : 'fa-shopping-bag'}} me-2"/>
                            <span class="ub-pk-order-no" t-esc="order.title"/>
                            <span t-if="order.customer" class="ub-pk-order-customer" t-esc="order.customer"/>
                            <span t-if="order.cargo" class="badge text-bg-secondary ms-2" t-esc="order.cargo"/>
                        </div>
                        <div class="ub-pk-order-count">
                            <t t-if="order.done">Sipariş tamamlandı</t>
                            <t t-else=""><t t-esc="order.scanned"/> / <t t-esc="order.total"/> okutuldu</t>
                        </div>
                    </div>
                    <div t-attf-class="ub-pk-order-grid {{order.units.length === 1 ? 'ub-pk-order-single' : ''}}">
                        <t t-foreach="order.units" t-as="u" t-key="u.key">
                            <button type="button"
                                    t-attf-class="ub-pk-unit {{u.done ? 'ub-pk-unit-done' : 'ub-pk-unit-pending'}} {{u.flash ? 'ub-pk-unit-flash' : ''}}"
                                    t-att-title="u.product_name + (u.done ? ' — okutuldu' : ' — bekliyor')"
                                    t-on-click="() => u.has_image and this.openLightbox(u)">
                                <img t-if="u.has_image" t-att-src="u.thumb" t-att-alt="u.product_name"/>
                                <i t-else="" class="fa fa-picture-o ub-pk-unit-noimg"/>
                                <span class="ub-pk-unit-badge">
                                    <i t-attf-class="fa {{u.done ? 'fa-check' : 'fa-times'}}"/>
                                </span>
                            </button>
                        </t>
                        <div t-if="order.more" class="ub-pk-unit-more" t-esc="'+' + order.more"/>
                    </div>
                </div>

                <!-- Ürün listesi -->
                <div class="ub-product-list" t-if="state.items.length">
                    <t t-foreach="state.items" t-as="item" t-key="item.move_id">
                        <div t-attf-class="ub-product-row {{item.matched ? 'ub-line-done' : ''}}">
                            <div class="ub-packing-check">
                                <i t-attf-class="fa {{item.matched ? 'fa-check-square text-success' : 'fa-square-o text-muted'}} fa-lg"/>
                            </div>
                            <button type="button" t-if="item.has_image" class="ub-pk-thumb"
                                    t-att-title="'Büyüt: ' + item.product_name"
                                    t-on-click="() => this.openLightbox(item)">
                                <img t-att-src="item.image_url" t-att-alt="item.product_name" loading="lazy"/>
                                <span class="ub-pk-thumb-zoom"><i class="fa fa-search-plus"/></span>
                            </button>
                            <div t-else="" class="ub-pk-thumb ub-pk-thumb-empty" title="Ürün görseli yok">
                                <i class="fa fa-picture-o"/>
                            </div>
                            <div class="ub-prod-info" style="flex:1;">
                                <div class="ub-prod-name" t-esc="item.product_name"/>
                                <div class="ub-prod-barcode">
                                    <i class="fa fa-barcode"></i>
                                    <span t-esc="item.barcode"/>
                                </div>
                                <div class="ub-packing-order-info" t-if="item.customer_name">
                                    <small class="text-muted">
                                        <i class="fa fa-user"></i>
                                        <span t-esc="item.customer_name"/>
                                        <span t-if="item.cargo_provider"
                                              class="badge bg-secondary ms-1"
                                              t-esc="item.cargo_provider"/>
                                    </small>
                                </div>
                            </div>
                            <div class="ub-prod-qty-detail d-flex align-items-center">
                                <button class="btn btn-sm btn-outline-danger me-2" 
                                        t-if="item.done_qty > 0" 
                                        t-on-click="() => this.onDecreaseQty(item.picking_id, item.barcode)">
                                    <i class="fa fa-minus"></i>
                                </button>
                                <div>
                                    <span class="fw-bold" t-esc="item.done_qty"/>
                                    /
                                    <span t-esc="item.demand_qty"/>
                                </div>
                            </div>
                        </div>
                    </t>
                </div>

                <!-- Alt aksiyon bar -->
                <div class="ub-action-bar" t-if="state.all_matched">
                    <button class="btn btn-lg w-100 ub-packing-complete-btn"
                            t-on-click="onComplete"
                            t-att-disabled="state.loading or state.longOpPending or state.completeDone">
                        <i class="fa fa-check-circle"></i> Paketle &amp; Tamamla
                    </button>
                </div>

                <div class="ub-action-bar" t-if="!state.all_matched">
                    <button class="btn btn-outline-secondary btn-lg w-100" disabled="true">
                        <i class="fa fa-clock-o"></i>
                        Tüm ürünleri tarayın (<t t-esc="state.total - state.matched"/> kaldı)
                    </button>
                </div>

                <!-- Etiket basma (tamamlandıktan sonra) -->
                <t t-if="state.completed">
                    <div class="ub-packing-label-section">
                        <div class="ub-section-title-dark">
                            <i class="fa fa-print"></i> Kargo Etiketleri
                        </div>
                        <t t-foreach="state.completedPickings" t-as="cp" t-key="cp.id">
                            <div class="ub-picking-row">
                                <div class="ub-picking-info">
                                    <div class="ub-picking-name" t-esc="cp.name"/>
                                    <div class="ub-picking-meta">
                                        <span t-if="cp.cargo_tracking" class="badge bg-info">
                                            <i class="fa fa-truck"></i>
                                            <span t-esc="cp.cargo_tracking"/>
                                        </span>
                                    </div>
                                </div>
                                <button class="btn btn-sm btn-success" t-on-click="() => this.printLabel(cp.picking_id)">
                                    <i class="fa fa-print"></i> Etiket
                                </button>
                            </div>
                        </t>
                    </div>
                </t>
            </t>

            <t t-if="state.error">
                <div class="ub-error-card">
                    <i class="fa fa-exclamation-triangle"></i>
                    <p style="white-space: pre-line;" t-esc="state.error"/>
                </div>
            </t>

            <!-- Ürün görseli: büyük önizleme (ESC / dışarı tıklama / barkod okutma kapatır) -->
            <div t-if="state.lightbox" class="ub-pk-lightbox" role="dialog" aria-modal="true"
                 t-on-click="closeLightbox">
                <div class="ub-pk-lightbox-dialog" t-on-click.stop="">
                    <div class="ub-pk-lightbox-header">
                        <div class="ub-pk-lightbox-title">
                            <div class="ub-pk-lightbox-name" t-esc="state.lightbox.name"/>
                            <div class="ub-pk-lightbox-meta" t-if="state.lightbox.barcode">
                                <i class="fa fa-barcode me-1"/><span t-esc="state.lightbox.barcode"/>
                            </div>
                        </div>
                        <a class="btn btn-link ub-pk-lightbox-action" t-att-href="state.lightbox.full"
                           target="_blank" rel="noopener" title="Orijinal boyutta aç">
                            <i class="fa fa-external-link"/>
                        </a>
                        <button type="button" class="btn-close btn-close-white" aria-label="Kapat"
                                t-on-click="closeLightbox"/>
                    </div>
                    <div class="ub-pk-lightbox-body">
                        <img t-att-src="state.lightbox.src" t-att-alt="state.lightbox.name"/>
                    </div>
                </div>
            </div>
        </div>
    `;

    static props = { navigate: Function, scanner: Object };

    setup() {
        this.state = useState({
            view: 'search',
            loading: false,
            error: null,
            routeInput: '',
            batches: [],
            // detail
            batch: null,
            items: [],
            total: 0,
            matched: 0,
            all_matched: false,
            scanInput: '',
            scanMsg: '',
            reprintPickingId: null,
            scanOk: false,
            // completed
            completed: false,
            // Tamamla tüm picking'lerde hatasız bitti (zaman aşımı sonrası geç yanıt dahil):
            // "Paketle & Tamamla" yeniden etkinleşmez. Hata/kısmi başarıda false kalır (yeniden deneme)
            completeDone: false,
            completedPickings: [],
            // filtreler
            filterState: 'all',
            filterDateFrom: '',
            filterDateTo: '',
            // ürün görseli önizleme
            lightbox: null,
            // okutulan sipariş paneli
            activeOrderKey: null,
            activeFlashMoveId: null,
            // "Eksik Onayla" hedefi (yalnız en son okutmanın siparişi)
            inc_picking_id: null,
            inc_picking_name: '',
            // kuyrukta bekleyen + işlenen işlem sayısı
            scanPending: 0,
            // yanıtı beklenen Tamamla / Eksik Onayla sayısı (düğmeler kapalı)
            longOpPending: 0,
        });
        this._orderTimer = null;
        // Okutma kuyruğu ve sıra numaraları
        this._chain = Promise.resolve();
        this._scanSeq = 0;      // en son okutmanın numarası
        this._listSeq = 0;      // en son istenen liste yenilemesinin numarası
        this._burstErrors = 0;  // kuyruk boşalana kadarki seride hatalı işlem sayısı
        this._labelRequested = new Set();  // bu rotada otomatik etiket istenen picking'ler
        this._timers = new Set();   // kuyruk zaman aşımı zamanlayıcıları (ekrandan çıkışta temizlenir)
        this._orphans = new Set();  // zaman aşımına uğramış, yanıtı beklenen kısa istekler
        this._alive = true;

        this._onKeydown = (ev) => {
            if (ev.key === 'Escape' && this.state.lightbox) {
                ev.stopPropagation();
                this.closeLightbox();
            }
        };
        window.addEventListener('keydown', this._onKeydown, true);

        this._unsub = this.props.scanner.onScan(bc => {
            this.state.lightbox = null;  // okutma önizlemeyi kapatır, akış kesilmez
            if (this.state.view === 'detail') {
                this.state.scanInput = bc;
                this.onScan();
            } else if (this.state.view === 'search') {
                this.state.routeInput = bc;
                this.searchRoute();
            }
        });

        this.routeInputRef = useRef('routeInput');
        this.scanInputRef = useRef('scanInput');
        this._lastFocusedView = null;

        onMounted(() => {
            this.loadBatchList();
            this._autoFocus(true);
        });

        onPatched(() => {
            // Sadece view değiştiğinde focus at (yazı yazarken değil)
            if (this._lastFocusedView !== this.state.view) {
                this._autoFocus(true);
            }
        });

        onWillUnmount(() => {
            this._alive = false;
            // Bekleyen zaman aşımı zamanlayıcıları ekrandan sonra çalışmasın
            for (const t of this._timers) clearTimeout(t);
            this._timers.clear();
            if (this._unsub) this._unsub();
            window.removeEventListener('keydown', this._onKeydown, true);
            clearTimeout(this._orderTimer);
        });
    }

    // ─── OKUTULAN SİPARİŞ PANELİ ────────────────
    // Sipariş = satış siparişi (origin): aynı siparişin kardeş picking'leri birlikte gösterilir
    _orderKey(item) {
        return item.origin || ('pk' + item.picking_id);
    }

    get activeOrder() {
        const key = this.state.activeOrderKey;
        if (!key) return null;
        const lines = (this.state.items || []).filter(i => !i.cancelled && this._orderKey(i) === key);
        if (!lines.length) return null;
        const MAX_UNITS = 12;
        const units = [];
        let total = 0;
        let scanned = 0;
        for (const it of lines) {
            // Paketleme hedefi: "Eksik" işaretli satırda toplanan kadar (sunucu target_qty)
            const demand = Math.max(0, Math.round((it.target_qty ?? it.demand_qty) || 0));
            const done = Math.min(demand, Math.round(it.scanned_qty || 0));
            total += demand;
            scanned += done;
            for (let i = 0; i < demand && units.length < MAX_UNITS; i++) {
                units.push({
                    key: it.move_id + '-' + i,
                    done: i < done,
                    flash: it.move_id === this.state.activeFlashMoveId && i === done - 1,
                    image_url: it.image_url,
                    thumb: (it.image_url || '').replace('image_128', 'image_256'),
                    has_image: it.has_image,
                    product_name: it.product_name,
                    barcode: it.barcode,
                });
            }
        }
        const first = lines[0];
        return {
            title: first.order_number || first.origin || first.picking_name,
            customer: first.customer_name,
            cargo: first.cargo_provider,
            units,
            total,
            scanned,
            more: Math.max(0, total - units.length),
            done: total > 0 && scanned >= total,
        };
    }

    _activateOrder(pickingId, barcode) {
        if (!this._alive) return;
        const items = this.state.items || [];
        const inPicking = items.filter(i => i.picking_id === pickingId);
        const item = inPicking.find(i => i.barcode === barcode) || inPicking[0];
        if (!item) return;
        const key = this._orderKey(item);
        this.state.activeOrderKey = key;
        this.state.activeFlashMoveId = item.move_id;
        clearTimeout(this._orderTimer);
        if (this.activeOrder && this.activeOrder.done) {
            // Tamamlanan sipariş kısa süre yeşil görünür, sonra panel kapanır
            this._orderTimer = setTimeout(() => {
                if (this.state.activeOrderKey === key && this.activeOrder && this.activeOrder.done) {
                    this.state.activeOrderKey = null;
                }
            }, 2000);
        }
    }

    _resetOrderPanel() {
        clearTimeout(this._orderTimer);
        this.state.activeOrderKey = null;
        this.state.activeFlashMoveId = null;
    }

    // ─── ÜRÜN GÖRSELİ ÖNİZLEME ──────────────────
    openLightbox(item) {
        const base = item.image_url || '';
        this.state.lightbox = {
            src: base.replace('image_128', 'image_1024'),
            full: base.replace('image_128', 'image_1920'),
            name: item.product_name,
            barcode: item.barcode,
        };
    }

    closeLightbox() {
        this.state.lightbox = null;
        this._autoFocus(true);
    }

    _autoFocus(force = false) {
        this._lastFocusedView = this.state.view;
        // Önce ana pencereye focus ver (popup'tan dönüş için şart)
        window.focus();
        // DOM hazır olduktan sonra input'a focus at
        setTimeout(() => {
            window.focus();
            if (this.state.view === 'search' && this.routeInputRef.el) {
                this.routeInputRef.el.focus();
            } else if (this.state.view === 'detail' && this.scanInputRef.el) {
                this.scanInputRef.el.focus();
            }
        }, 150);
    }

    goBack() {
        if (this.state.view === 'detail') {
            this._resetOrderPanel();
            this.state.view = 'search';
            this.state.error = null;
            this.state.completed = false;
            this.state.completeDone = false;
        } else {
            this.props.navigate('main');
        }
    }

    get progressPct() {
        if (!this.state.total) return 0;
        return Math.round((this.state.matched / this.state.total) * 100);
    }

    // ─── BATCH LİSTESİ ──────────────────────────
    async loadBatchList() {
        try {
            const params = {
                exclude_transfers: true,
            };
            if (this.state.filterState && this.state.filterState !== 'all') {
                params.filter_state = this.state.filterState;
            }
            if (this.state.filterDateFrom) {
                params.date_from = this.state.filterDateFrom;
            }
            if (this.state.filterDateTo) {
                params.date_to = this.state.filterDateTo;
            }
            const res = await BarcodeService.call('/ugurlar_barcode/api/batch_list', params);
            this.state.batches = res.batches || [];
            // Önceki liste hatası (yalnız o) başarılı yenilemede kalkar
            if (this._batchListError && this.state.error === this._batchListError) {
                this.state.error = null;
            }
            this._batchListError = null;
        } catch (e) {
            // Sessiz kalmaz: boş liste "rota yok" gibi görünmesin
            // Sürücü/ağ hata metni İngilizce olabilir: kullanıcıya sabit Türkçe metin, ayrıntı konsola
            console.warn('Rota listesi yüklenemedi', e);
            this._batchListError = 'Rota listesi yüklenemedi. Bağlantıyı kontrol edip tekrar deneyin.';
            this.state.error = this._batchListError;
        }
    }

    setFilter(state) {
        this.state.filterState = state;
        this.loadBatchList();
    }

    onRouteKey(ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); this.searchRoute(); }
    }

    async searchRoute() {
        const name = this.state.routeInput.trim();
        if (!name) return;
        this.state.loading = true;
        this.state.error = null;

        // Akıllı algılama: R/TOPLAMA ile başlıyorsa rota numarası, değilse barkod
        const isRouteName = /^[Rr]\d/i.test(name) || name.toUpperCase().startsWith('TOPLAMA');

        if (isRouteName) {
            // Rota numarası → doğrudan aç
            try {
                const res = await BarcodeService.call('/ugurlar_barcode/api/packing_batch_detail', {
                    batch_name: name,
                });
                if (res.error) {
                    this.state.error = res.error;
                    speak('packing_route_not_found');
                } else {
                    this._setBatchDetail(res);
                    speak('packing_route_found');
                }
            } catch (e) {
                this.state.error = 'Bağlantı hatası';
                speak('packing_error');
            }
        } else {
            // Barkod → o ürünün olduğu açık rotaları filtrele
            try {
                const res = await BarcodeService.call('/ugurlar_barcode/api/batch_list', {
                    exclude_transfers: true,
                    barcode_search: name,
                });
                if (res.error) {
                    this.state.error = res.error;
                    this.state.batches = [];
                    speak('packing_route_not_found');
                } else {
                    const batches = res.batches || [];
                    if (batches.length === 0) {
                        this.state.error = '"' + name + '" barkodlu ürün açık rotalarda bulunamadı';
                        this.state.batches = [];
                        speak('packing_route_not_found');
                    } else if (batches.length === 1) {
                        // Tek rota bulundu → doğrudan aç
                        this.state.loading = false;
                        await this.loadBatch(batches[0].id);
                        return;
                    } else {
                        // Birden fazla rota → listeyi filtrele
                        this.state.batches = batches;
                        this.state.error = null;
                    }
                }
            } catch (e) {
                this.state.error = 'Bağlantı hatası: ' + (e.message || e);
                this.state.batches = [];
            }
        }

        this.state.loading = false;
    }

    async loadBatch(id) {
        this.state.loading = true;
        this.state.error = null;
        try {
            const res = await BarcodeService.call('/ugurlar_barcode/api/packing_batch_detail', {
                batch_id: id,
            });
            if (res.error) {
                this.state.error = res.error;
                speak('packing_route_not_found');
            } else {
                this._setBatchDetail(res);
                speak('packing_route_found');
            }
        } catch (e) {
            this.state.error = 'Bağlantı hatası';
            speak('packing_error');
        }
        this.state.loading = false;
    }

    _setBatchDetail(res) {
        this._resetOrderPanel();
        // Bu yüklemeden önce istenmiş liste yenilemeleri artık bayat
        this._listSeq++;
        this._labelRequested = new Set();
        this.state.inc_picking_name = '';
        this.state.batch = res.batch;
        this.state.items = res.items;
        this.state.total = res.total;
        this.state.matched = res.matched;
        this.state.all_matched = res.all_matched;
        this.state.view = 'detail';
        this.state.completed = false;
        this.state.completeDone = false;
        this.state.inc_picking_id = null;
    }

    // ─── OKUTMA KUYRUĞU ─────────────────────────
    // Okutma ve sayaç değiştiren eylemler tek zincirde sırayla çalışır (aynı anda tek istek).
    // Bir öğenin hatası veya zaman aşımı sıradakileri durdurmaz.
    _enqueue(task, { timeoutMs = QUEUE_TIMEOUT_MS, refreshOnLate = true, long = false, ownsLoading = false } = {}) {
        if (this.state.scanPending === 0) this._burstErrors = 0;
        this.state.scanPending++;
        // Uzun iş: kuyruğa girdiği andan sunucu yanıtı (zaman aşımı olsa da geç yanıt) gelene kadar sayılır
        if (long) this.state.longOpPending++;
        const opts = { timeoutMs, refreshOnLate, long, ownsLoading };
        this._chain = this._chain
            .then(() => this._waitForOrphans())
            .then(() => this._runWithTimeout(task, opts))
            .catch((e) => {
                if (!(e instanceof StaleResponse)) console.error('Paketleme kuyruğu hatası:', e);
            })
            .finally(() => {
                this.state.scanPending--;
            });
        return this._chain;
    }

    // Yanıtı hâlâ beklenen zaman aşımlı istek sayısı sınırdaysa yeni istek gönderilmez (sunucuya ek yük binmez)
    async _waitForOrphans() {
        while (this._orphans.size >= MAX_ORPHAN_REQUESTS) {
            if (this._alive) {
                this.state.scanMsg = 'Sunucu yavaş yanıt veriyor: önceki işlemlerin yanıtı bekleniyor, '
                    + 'okutmalarınız sırada. Yanıt uzun süre gelmezse ekrandan çıkıp tekrar girin.';
                this.state.scanOk = false;
            }
            await Promise.race(this._orphans);
        }
    }

    _runWithTimeout(task, { timeoutMs, refreshOnLate, long, ownsLoading }) {
        const ctx = { timedOut: false };
        const batchId = this.state.batch && this.state.batch.id;
        const work = Promise.resolve().then(() => task(ctx));
        const settled = work.then(() => {}, () => {});  // yanıt geldi veya hata (reddedilmez)
        let released = false;
        const releaseLong = () => {
            if (long && !released) {
                released = true;
                this.state.longOpPending--;
            }
        };
        let timer;
        const expired = new Promise((resolve) => {
            timer = setTimeout(() => {
                this._timers.delete(timer);
                ctx.timedOut = true;
                resolve(true);
            }, timeoutMs);
            this._timers.add(timer);
        });
        const stopTimer = () => {
            clearTimeout(timer);
            this._timers.delete(timer);
        };
        return Promise.race([work.then(() => false), expired]).then((isTimeout) => {
            stopTimer();
            if (!isTimeout) {
                releaseLong();
                return;
            }
            this._onQueueTimeout(long, ownsLoading);
            if (!long) {
                this._orphans.add(settled);
                settled.then(() => this._orphans.delete(settled));
            }
            // Geç gelen yanıt ekrana yazılmaz; sunucu işlemiş olabilir, liste kuyruktan yenilenir.
            // Uzun işin düğmeleri yenileme bitene kadar kapalı kalır (bayat ekranla ikinci basış olmaz)
            settled.then(async () => {
                if (refreshOnLate && this._alive && batchId) {
                    await this._enqueue((c) => this._refreshList(batchId, c), { refreshOnLate: false });
                }
            }).finally(releaseLong);
        }, (e) => {
            stopTimer();
            releaseLong();
            throw e;
        });
    }

    _onQueueTimeout(long = false, ownsLoading = false) {
        if (!this._alive) return;
        this._burstErrors++;
        // loading yalnız onu açan görev zaman aşımına uğradıysa kapanır (sıradaki Tamamla'nınki açık kalır)
        if (ownsLoading) this.state.loading = false;
        this.state.inc_picking_id = null;
        this.state.scanMsg = long
            ? 'Sunucu yanıt vermedi (zaman aşımı) ama işlem sunucuda sürüyor olabilir. Lütfen bekleyin, '
                + 'tekrar basmayın: yanıt gelince liste yenilenecek. Yanıt uzun süre gelmezse '
                + 'ekrandan çıkıp tekrar girin.'
            : 'Sunucu yanıt vermedi (zaman aşımı). İşlemin sonucu bilinmiyor; '
                + 'yanıt gelirse liste yenilenecek. Sıradaki okutmaya geçildi. Sunucu uzun süre '
                + 'yanıt vermezse ekrandan çıkıp tekrar girin.';
        this.state.scanOk = false;
        AudioFeedback.playError();
        vibrateError();
        speak('packing_error');
    }

    // Zaman aşımına uğramış görevin geç yanıtı veya başka rotaya geçildiyse yanıt uygulanmaz
    async _guard(ctx, batchId, promise) {
        const res = await promise;
        if (ctx.timedOut || !this._alive || !this.state.batch || this.state.batch.id !== batchId) {
            throw new StaleResponse();
        }
        return res;
    }

    // Liste yenileme: yalnız en son istenen yanıt uygulanır, eski yanıt yeni durumu ezmez
    async _refreshList(batchId, ctx = null) {
        const seq = ++this._listSeq;
        const fresh = await BarcodeService.call('/ugurlar_barcode/api/packing_batch_detail', {
            batch_id: batchId,
        });
        // Zaman aşımı veya ekrandan çıkış: çağıran devam etmez (etiket / panel zamanlayıcısı açılmaz)
        if ((ctx && ctx.timedOut) || !this._alive) throw new StaleResponse();
        if (seq !== this._listSeq || fresh.error
            || !this.state.batch || this.state.batch.id !== batchId) {
            return false;
        }
        this.state.items = fresh.items;
        this.state.matched = fresh.matched;
        this.state.all_matched = fresh.all_matched;
        return true;
    }

    // Okutma yanıtındaki satır durumunu listeye işler; satır listede yoksa false (çağıran tam yeniler).
    // Sayaçlar sunucu detayıyla aynı kuralla türetilir: iptal satırı sayıma girmez.
    _applyItemUpdate(upd) {
        const items = this.state.items || [];
        const item = upd && items.find(i => i.move_id === upd.move_id);
        if (!item) return false;
        const { move_id, ...fields } = upd;
        Object.assign(item, fields);
        const counted = items.filter(i => !i.cancelled);
        this.state.matched = counted.filter(i => i.matched).length;
        this.state.all_matched = this.state.matched === counted.length;
        return true;
    }

    // Aynı rotada bir picking için otomatik etiket bir kez istenir; tekrarında "Tekrar Yazdır" sunulur
    _autoPrintLabel(pickingId) {
        if (!this._alive) return false;  // ekrandan çıkıldıktan sonra etiket penceresi açılmaz
        if (this._labelRequested.has(pickingId)) {
            this.state.reprintPickingId = pickingId;
            return false;
        }
        this._labelRequested.add(pickingId);
        this.printLabel(pickingId);
        return true;
    }

    _addCompletedPicking(pickingId, pickingName, allowMissing = false) {
        if (!this.state.completedPickings) this.state.completedPickings = [];
        if (this.state.completedPickings.find(p => p.picking_id === pickingId)) return;
        const matchedItem = (this.state.items || []).find(i => i.picking_id === pickingId);
        if (!matchedItem && !allowMissing) return;
        this.state.completedPickings.unshift({
            id: pickingId,
            picking_id: pickingId,
            name: pickingName || (matchedItem && matchedItem.picking_name),
            cargo_tracking: matchedItem ? matchedItem.cargo_tracking : '',
            cargo_provider: matchedItem ? matchedItem.cargo_provider : '',
            customer_name: matchedItem ? matchedItem.customer_name : '',
        });
    }

    // "Eksik Onayla" için sipariş adı: sipariş no / origin ve picking adı
    _orderLabel(pickingId) {
        const item = (this.state.items || []).find(i => i.picking_id === pickingId);
        const pickingName = (item && item.picking_name) || this.state.inc_picking_name || ('#' + pickingId);
        const order = item && (item.order_number || item.origin);
        return order && order !== pickingName ? `${order} (${pickingName})` : pickingName;
    }

    get incOrderLabel() {
        return this.state.inc_picking_id ? this._orderLabel(this.state.inc_picking_id) : '';
    }

    // ─── BARKOD TARAMA ──────────────────────────
    onScanKey(ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); this.onScan(); }
    }

    async onScan() {
        const code = (this.state.scanInput || '').trim();
        this.state.scanInput = '';
        if (!code || !this.state.batch) return;
        // Her okutma önceki siparişin "Eksik Onayla" hedefini geçersiz kılar (bayat id kullanılmaz)
        this.state.inc_picking_id = null;
        this.state.inc_picking_name = '';
        const batchId = this.state.batch.id;
        const seq = ++this._scanSeq;
        await this._enqueue((ctx) => this._processScan(ctx, code, batchId, seq));
    }

    async _processScan(ctx, code, batchId, seq) {
        // Arkada bekleyen okutma yoksa bu en son okutmadır
        const isLatest = () => seq === this._scanSeq;
        this.state.scanMsg = '';
        this.state.reprintPickingId = null;
        this.state.inc_picking_id = null;
        try {
            const res = await this._guard(ctx, batchId, BarcodeService.call('/ugurlar_barcode/api/packing_scan', {
                batch_id: batchId,
                barcode: code,
            }));
            if (res.error) {
                this._burstErrors++;
                this.state.scanMsg = res.error;
                this.state.scanOk = false;
                speak('packing_scan_wrong');
            } else if (res.warning) {
                // "Zaten paketlendi" durumu
                if (res.validate_pending) {
                    // Okutması bitmiş ama doğrulanamamış sipariş: etiket basılmaz
                    this.state.scanMsg = `⚠️ ${res.message}`;
                    this.state.scanOk = false;
                    speak('packing_error');
                } else if (res.label_already_printed) {
                    // Etiket zaten basıldı — tekrar basma seçeneği sun
                    this.state.scanMsg = `✅ ${res.message} (etiket daha önce basıldı)`;
                    this.state.scanOk = true;
                    this.state.reprintPickingId = res.picking_id || null;
                    speak('packing_scan_success');
                } else if (res.picking_completed && res.picking_id) {
                    // Etiket henüz basılmamış — bas (bu rotada zaten istendiyse yalnız tekrar yazdır sunulur)
                    this.state.scanOk = true;
                    speak('packing_order_complete');

                    this.state.completed = true;
                    this._addCompletedPicking(res.picking_id, res.picking_name, true);
                    const printed = this._autoPrintLabel(res.picking_id);
                    this.state.scanMsg = res.picking_name + (printed
                        ? " zaten paketlendi, etiket yazdırılıyor..."
                        : " zaten paketlendi (etiket bu rotada yazdırıldı)");
                } else {
                    this.state.scanMsg = res.message;
                    this.state.scanOk = true;
                    speak('packing_scan_success');
                }
            } else {
                this.state.scanMsg = `${res.product_name} — ${res.picking_name} (${res.done_qty}/${res.demand_qty})`;
                this.state.scanOk = true;
                speak('packing_scan_success');

                // Listeyi güncelle. Sıradan okutmada yanıttaki satır yamanır (ikinci ağır istek yok);
                // sipariş tamamlanması, hata, rota kapanışı gibi yapı değişince tam yenilenir
                // (sıra numaralı: eski yanıt yeni listeyi ezmez)
                if (res.refresh_needed || !this._applyItemUpdate(res.item_update)) {
                    await this._refreshList(batchId, ctx);
                }

                if (res.validate_error) {
                    // Okutma sayıldı ama sevkiyat doğrulanamadı: etiket basılmaz, Nebim çalışmaz
                    this._burstErrors++;
                    this.state.scanMsg = `⚠️ ${res.validate_error}`;
                    this.state.scanOk = false;
                    speak('packing_error');
                } else if (res.picking_completed && res.picking_id) {
                    // Sipariş tamamen eşleşti: kargo etiketini otomatik yazdır
                    this.state.scanMsg = res.picking_name + " siparişi eşleşti, etiket yazdırılıyor...";
                    speak('packing_order_complete');

                    // Alt ekrandaki Kargo Etiketleri listesine anında ekle
                    this.state.completed = true;
                    this._addCompletedPicking(res.picking_id, res.picking_name);

                    // Otomatik yazdırmayı tetikle (Kargo etiketi servisi bitince pop-up açacak)
                    this._autoPrintLabel(res.picking_id);
                } else if (res.picking_id && res.remaining_items && res.remaining_items.length > 0) {
                    // Sipariş içerisinde okutulması gereken başka ürünler var
                    this.state.scanMsg = `${res.product_name} paketlendi ancak ${res.picking_name} siparişi BİTMEDİ. Lütfen şunları da okutun: ${res.remaining_items.join(', ')}`;
                    this.state.scanOk = false; // Farkındalık için kırmızı veya uyarı rengi
                    if (isLatest()) {
                        // Arkada başka okutma varsa buton gösterilmez: bayat sipariş onaylanamaz
                        this.state.inc_picking_id = res.picking_id;
                        this.state.inc_picking_name = res.picking_name || '';
                    }
                    speak('packing_scan_wrong');
                }
            }
            if (!res.error && res.picking_id) {
                this._activateOrder(res.picking_id, code);
            }
            if (isLatest() && this._burstErrors && this.state.scanOk) {
                // Hızlı seride hatalı okutma olduysa son başarılı mesaj onu gizlemesin
                this.state.scanMsg += ` (bu seride ${this._burstErrors} işlem hatalı)`;
                this.state.scanOk = false;
            }
        } catch (e) {
            if (e instanceof StaleResponse) return;
            this._burstErrors++;
            const detail = (e && e.data && e.data.message) || e.message || e.toString() || '';
            this.state.scanMsg = 'Hata' + (detail ? ': ' + detail : '');
            this.state.scanOk = false;
            this.state.inc_picking_id = null;
            speak('packing_error');
        }
    }

    // ─── ETİKET TEKRAR YAZDIRMA ─────────────────────
    async onReprintLabel(pickingId) {
        this.state.scanMsg = 'Etiket tekrar yazdırılıyor...';
        this.state.scanOk = true;
        this.state.reprintPickingId = null;
        this.printLabel(pickingId);
    }

    // ─── TAMAMLA ─────────────────────────────────
    async onComplete() {
        if (!this.state.batch) return;
        if (this.state.longOpPending) {
            this.state.scanMsg = 'Önceki işlem sunucuda sürüyor, yanıtı gelince tekrar deneyin.';
            this.state.scanOk = false;
            return;
        }
        const batchId = this.state.batch.id;
        this.state.loading = true;
        this.state.error = null;
        // Bekleyen okutmalar bitmeden tamamlama çalışmaz
        await this._enqueue((ctx) => this._doComplete(ctx, batchId),
            { timeoutMs: QUEUE_LONG_TIMEOUT_MS, long: true, ownsLoading: true });
    }

    async _doComplete(ctx, batchId) {
        try {
            const call = BarcodeService.call('/ugurlar_barcode/api/packing_complete', {
                batch_id: batchId,
            });
            // Zaman aşımından SONRA gelen yanıt _guard'da atılır; ama sunucu işi bitirmiş olabilir.
            // Aynı rotadaysak sonucu (zaman aşımı mesajını temizleyerek) yine uygula.
            call.then((late) => {
                if (ctx.timedOut && this._alive && this.state.batch
                    && this.state.batch.id === batchId && late) {
                    this._applyCompleteResult(late);
                }
            }, () => {});
            const res = await this._guard(ctx, batchId, call);
            this._applyCompleteResult(res);
        } catch (e) {
            if (e instanceof StaleResponse) return;
            this.state.error = 'Tamamlama hatası';
        }
        this.state.loading = false;
    }

    // packing_complete yanıtını ekrana uygular (normal ve zaman aşımı sonrası geç yanıt için ortak)
    _applyCompleteResult(res) {
        if (res.error) {
            // Sunucu tamamlamayı reddetti (rota yok / eksik ürün var): hata görünür olsun, varsa
            // "Lütfen bekleyin" (zaman aşımı) mesajı kalksın; completeDone false kalır -> yeniden deneme açık
            this.state.error = res.error;
            this.state.scanMsg = '';
            this.state.scanOk = false;
            speak('packing_error');
            return;
        }
        const hasErrors = !!(res.errors && res.errors.length);
        if (hasErrors) {
            // Doğrulanamayan siparişler adı ve hata metniyle alt alta listelenir
            this.state.error = res.errors.join('\n');
        }
        if (res.success || res.validated > 0) {
            // scanMsg'in üzerine yazılır: varsa zaman aşımı mesajı kalkar
            this.state.scanMsg = res.message;
            this.state.scanOk = true;
            this.state.completed = true;
            // Yalnız hatasız tam başarıda düğme kilitlenir; hata/kısmi başarıda yeniden deneme açık kalır
            if (res.success && !hasErrors) this.state.completeDone = true;
            speak(hasErrors ? 'packing_error' : 'packing_complete');

            // Etiket bilgilerini hazırla — doğrulanamayan ve atlanan (hiç toplanmamış)
            // siparişlere etiket basılmaz
            const failedIds = res.failed_picking_ids || [];
            const skippedIds = res.skipped_picking_ids || [];
            const pickingInfos = [];
            for (const item of this.state.items) {
                if (failedIds.includes(item.picking_id) || skippedIds.includes(item.picking_id)) continue;
                if (!pickingInfos.find(p => p.picking_id === item.picking_id)) {
                    pickingInfos.push({
                        id: item.picking_id,
                        picking_id: item.picking_id,
                        name: item.picking_name,
                        cargo_tracking: item.cargo_tracking,
                        cargo_provider: item.cargo_provider,
                        customer_name: item.customer_name,
                    });
                }
            }
            this.state.completedPickings = pickingInfos;
        } else if (hasErrors) {
            speak('packing_error');
        }
    }

    // ─── EKSİK ONAYLA (BACKORDER) ────────────────
    async onBackorder(pickingId) {
        if (this.state.longOpPending) {
            this.state.scanMsg = 'Önceki işlem sunucuda sürüyor, yanıtı gelince tekrar deneyin.';
            this.state.scanOk = false;
            return;
        }
        const label = this._orderLabel(pickingId);
        if (!confirm(`${label} siparişini eksik ürünlerle onaylayıp kapatmak istediğinize emin misiniz?`)) return;
        if (!this.state.batch) return;
        const batchId = this.state.batch.id;
        this.state.loading = true;
        this.state.scanMsg = `${label} için backorder oluşturuluyor...`;
        this.state.inc_picking_id = null;
        this.state.inc_picking_name = '';
        await this._enqueue((ctx) => this._doBackorder(ctx, batchId, pickingId),
            { timeoutMs: QUEUE_LONG_TIMEOUT_MS, long: true, ownsLoading: true });
    }

    async _doBackorder(ctx, batchId, pickingId) {
        try {
            const res = await this._guard(ctx, batchId, BarcodeService.call('/ugurlar_barcode/api/packing_backorder', {
                picking_id: pickingId,
                batch_id: batchId,
            }));
            if (res.error) {
                this.state.scanMsg = res.error;
                this.state.scanOk = false;
                speak('packing_error');
            } else {
                this.state.scanMsg = res.message;
                this.state.scanOk = true;
                speak('packing_order_complete');

                // Detayı yeniden yükle
                await this._refreshList(batchId, ctx);

                // Otomatik etiket listesine ekle ve yazdır
                this.state.completed = true;
                this._addCompletedPicking(pickingId);
                this._labelRequested.add(pickingId);
                setTimeout(() => {
                    if (this._alive) this.printLabel(pickingId);
                }, 100);
            }
        } catch (e) {
            if (e instanceof StaleResponse) return;
            this.state.scanMsg = 'Bağlantı hatası';
            this.state.scanOk = false;
            speak('packing_error');
        }
        this.state.loading = false;
    }

    // ─── GERİ AL (UNDO) MİKTAR DÜŞÜRME ────────────
    async onDecreaseQty(pickingId, barcode) {
        if (!confirm('Bu ürünün okutulmuş miktarını 1 azaltmak istediğinize emin misiniz?')) return;
        if (!this.state.batch) return;
        const batchId = this.state.batch.id;
        this.state.loading = true;
        await this._enqueue((ctx) => this._doDecrease(ctx, batchId, pickingId, barcode), { ownsLoading: true });
    }

    async _doDecrease(ctx, batchId, pickingId, barcode) {
        try {
            const res = await this._guard(ctx, batchId, BarcodeService.call('/ugurlar_barcode/api/packing_undo', {
                picking_id: pickingId,
                barcode: barcode,
            }));
            if (res.error) {
                this.state.scanMsg = res.error;
                this.state.scanOk = false;
                speak('packing_error');
            } else {
                this.state.scanMsg = res.message;
                this.state.scanOk = true;
                speak('packing_scan_success');

                // Refresh detail
                await this._refreshList(batchId, ctx);
                // Geri alınan adet panelde kırmızıya döner
                this._activateOrder(pickingId, barcode);
            }
        } catch (e) {
            if (e instanceof StaleResponse) return;
            this.state.scanMsg = 'Bağlantı hatası';
            this.state.scanOk = false;
        }
        this.state.loading = false;
    }

    // ─── ETİKET BAS ─────────────────────────────
    async printLabel(pickingId) {
        try {
            // log_print: picking chatter'ına tek "Kargo Etiketi Yazdırıldı" notu (yeniden denemede yok)
            let data = await BarcodeService.call('/ugurlar_barcode/api/packing_label_data', {
                picking_id: pickingId,
                log_print: true,
            });
            if (data.error) { this.state.error = data.error; return; }

            // Fatura numarası kontrolü — Nebim API yavaş cevap verebilir
            if (!data.nebim_invoice_no) {
                // 3 saniye bekleyip tekrar dene (Nebim API'nin cevap vermesi için)
                await new Promise(r => setTimeout(r, 3000));
                const retry = await BarcodeService.call('/ugurlar_barcode/api/packing_label_data', {
                    picking_id: pickingId,
                    // Nebim senkronu birinci çağrıda tetiklendi; ikincisi yalnız okur (Nebim iki kez çağrılmaz)
                    trigger_sync: false,
                });
                if (!retry.error && retry.nebim_invoice_no) {
                    data = retry;
                }
            }

            // Fatura numarası hâlâ yoksa kullanıcıya sesli ve görsel uyarı göster
            if (!data.nebim_invoice_no) {
                this.state.scanMsg = '⚠️ Fatura numarası henüz oluşmadı! Nebim bağlantısını kontrol edin. Etiket fatura numarası olmadan basılacak.';
                this.state.scanOk = false;
                speak('Dikkat! Fatura numarası oluşmadı. Nebim bağlantısını kontrol edin.');
                vibrateError();
            }

            let template = null;
            try {
                const res = await BarcodeService.labelTemplateList();
                const ct = (res.templates || []).filter(t => t.name.startsWith('Kargo'));
                if (ct.length > 0) template = ct[0];
            } catch (e) { /* varsayılan kullanılacak */ }

            if (template && template.elements && template.elements.length > 0) {
                this._renderCargoTemplate(template, data);
            } else {
                this._openDefaultLabelPrint(data);
            }
        } catch (e) {
            this.state.error = 'Etiket verisi alınamadı';
        }
    }

    _getFieldValue(type, data) {
        const map = {
            order_number:      data.order_number || data.origin || '',
            picking_name:      data.picking_name || '',
            origin:            data.origin || '',
            marketplace:       data.marketplace_name || '',
            customer_name:     data.customer_name || data.partner_name || '',
            partner_phone:     data.partner_phone || '',
            shipping_address:  data.shipping_address || data.partner_address || '',
            shipping_city:     data.shipping_city || '',
            shipping_district: data.shipping_district || '',
            cargo_tracking:    data.cargo_tracking || '',
            cargo_provider:    data.cargo_provider || '',
            total_qty:         (data.total_qty || 0) + ' adet',
            total_items:       (data.total_items || 0) + ' çeşit',
            date_today:        new Date().toLocaleDateString('tr-TR'),
            nebim_invoice_no:  data.nebim_invoice_no || '',
            nebim_invoice_date: data.nebim_invoice_date || '',
        };
        return map[type] !== undefined ? map[type] : '';
    }

    _renderCargoTemplate(template, data) {
        const wMm = template.width_mm;
        const hMm = template.height_mm;

        let elementsHtml = '';
        for (const el of template.elements) {
            const x = safeNum(el.x), y = safeNum(el.y), w = safeNum(el.width), h = safeNum(el.height);
            const fs = safeNum(el.fontSize, 9) || 9, fw = safeWeight(el.fontWeight);
            const ta = safeAlign(el.textAlign), color = safeColor(el.color, '#000000');
            const bgColor = safeColor(el.bgColor, 'transparent'), rotation = safeNum(el.rotation);
            let content = '';

            if (el.type === 'line') {
                const lineH = Math.max(h, 0.3);
                elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${lineH}mm; background:${color}; transform:rotate(${rotation}deg);"></div>`;
                continue;
            }
            if (el.type === 'box') {
                const bw = safeNum(el.borderWidth, 1) || 1;
                elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; border:${bw}px solid ${color}; background:${bgColor}; transform:rotate(${rotation}deg);"></div>`;
                continue;
            }
            if (el.type === 'cargo_barcode') {
                const bv = data.cargo_tracking || '';
                if (bv) {
                    const enc = encodeURIComponent(bv), iW = Math.round(w*12), iH = Math.round(h*12);
                    elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; transform:rotate(${rotation}deg); text-align:center;"><img src="/report/barcode/Code128/${enc}?width=${iW}&height=${iH}&humanreadable=1" style="width:100%;height:100%;object-fit:contain;image-rendering:pixelated;" onerror="this.style.display='none'" /></div>`;
                }
                continue;
            }
            if (el.type === 'cargo_qr_code') {
                const qv = el.content || data.cargo_tracking || '';
                if (qv) {
                    elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; transform:rotate(${rotation}deg);"><img src="/report/barcode/?type=QR&value=${encodeURIComponent(qv)}&width=${Math.round(w*12)}&height=${Math.round(h*12)}" style="width:100%;height:100%;object-fit:contain;" /></div>`;
                }
                continue;
            }
            if (el.type === 'item_list') {
                const items = data.items || [];
                let tbl = '<table style="width:100%;border-collapse:collapse;font-size:inherit;"><thead><tr style="border-bottom:0.3mm solid #333;"><th style="text-align:left;padding:0 0.5mm;">#</th><th style="text-align:left;padding:0 0.5mm;">Ürün</th><th style="text-align:right;padding:0 0.5mm;">Adet</th><th style="text-align:left;padding:0 0.5mm;">Barkod</th></tr></thead><tbody>';
                items.forEach((item, idx) => { tbl += `<tr><td style="padding:0 0.5mm;">${idx+1}</td><td style="padding:0 0.5mm;">${escapeHtml(item.product_name)}</td><td style="text-align:right;padding:0 0.5mm;">${escapeHtml(item.qty)}</td><td style="padding:0 0.5mm;">${escapeHtml(item.barcode)}</td></tr>`; });
                tbl += '</tbody></table>';
                elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; font-size:${fs}pt; font-weight:${fw}; overflow:hidden; color:${color}; background:${bgColor}; transform:rotate(${rotation}deg);">${tbl}</div>`;
                continue;
            }
            if (el.type === 'custom_text' || el.type === 'sender_name') {
                content = escapeHtml(el.content || '');
            } else {
                content = escapeHtml(this._getFieldValue(el.type, data));
            }
            elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; font-size:${fs}pt; font-weight:${fw}; text-align:${ta}; color:${color}; background:${bgColor}; transform:rotate(${rotation}deg); overflow:hidden; line-height:1.3; display:flex; align-items:center; ${ta === 'center' ? 'justify-content:center;' : ta === 'right' ? 'justify-content:flex-end;' : ''}">${content}</div>`;
        }

        const html = `<!DOCTYPE html><html><head>
            <meta charset="utf-8">
            <title>Kargo Etiketi ${wMm}x${hMm}mm</title>
            <style>
                @page { size: ${wMm}mm ${hMm}mm; margin: 0; }
                * { margin: 0; padding: 0; box-sizing: border-box; }
                html, body { margin: 0; padding: 0; }
                body {
                    width: ${wMm}mm; height: ${hMm}mm;
                    font-family: Arial, Helvetica, sans-serif;
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }
                .label {
                    position: relative;
                    width: ${wMm}mm; height: ${hMm}mm;
                    overflow: hidden;
                }
                img { image-rendering: pixelated; image-rendering: -moz-crisp-edges; }
                @media print {
                    @page { size: ${wMm}mm ${hMm}mm; margin: 0; }
                    html, body { width: ${wMm}mm; height: ${hMm}mm; overflow: hidden; }
                    .label { overflow: hidden; page-break-after: avoid; }
                }
            </style>
        </head><body>
            <div class="label">${elementsHtml}</div>
        </body></html>`;

        this._printViaWindow(html);
    }

    _openDefaultLabelPrint(data) {
        const cargoBarcode = data.cargo_tracking || '';
        const barcodeHtml = cargoBarcode
            ? `<div style="text-align:center; margin:2mm 0;">
                 <img src="/report/barcode/Code128/${encodeURIComponent(cargoBarcode)}?width=840&height=200&humanreadable=1"
                     style="width:70mm; height:18mm; display:inline-block; object-fit:contain; image-rendering:-webkit-crisp-edges; image-rendering:pixelated;" />
               </div>`
            : '';

        const itemsHtml = data.items.map(i =>
            `<tr><td>${escapeHtml(i.product_name)}</td><td style="text-align:center;">${escapeHtml(i.qty)}</td><td style="text-align:center;">${escapeHtml(i.barcode)}</td></tr>`
        ).join('');

        const html = `<!DOCTYPE html><html><head>
            <meta charset="utf-8">
            <title>Kargo Etiketi — ${escapeHtml(data.picking_name)}</title>
            <style>
                @page { size: 100mm 150mm; margin: 3mm; }
                * { margin:0; padding:0; box-sizing:border-box; }
                body { font-family: Arial, sans-serif; font-size: 11px; }
                .label { width: 94mm; padding: 4mm; }
                .header { display:flex; justify-content:space-between; border-bottom:2px solid #000; padding-bottom:4px; margin-bottom:6px; }
                .header h2 { font-size:14px; margin:0; }
                .info-grid { display:grid; grid-template-columns:1fr 1fr; gap:4px 12px; margin-bottom:6px; }
                .info-label { font-weight:bold; font-size:9px; color:#666; text-transform:uppercase; }
                .info-value { font-size:11px; }
                .cargo-section { text-align:center; border:2px solid #000; padding:6px; margin:6px 0; }
                .cargo-section .tracking { font-size:16px; font-weight:bold; letter-spacing:1px; }
                table { width:100%; border-collapse:collapse; margin-top:4px; }
                th, td { border:1px solid #ccc; padding:3px 4px; font-size:9px; }
                th { background:#f0f0f0; }
            </style>
        </head><body>
            <div class="label">
                <div class="header">
                    <h2>${escapeHtml(data.cargo_provider || 'KARGO')}</h2>
                    <span>${escapeHtml(data.picking_name)}</span>
                </div>
                <div class="info-grid">
                    <div><div class="info-label">Sipariş No</div><div class="info-value">${escapeHtml(data.order_number || data.origin)}</div></div>
                    <div><div class="info-label">Müşteri</div><div class="info-value">${escapeHtml(data.customer_name || data.partner_name)}</div></div>
                    <div><div class="info-label">Tel</div><div class="info-value">${escapeHtml(data.partner_phone || '-')}</div></div>
                    <div><div class="info-label">Adet</div><div class="info-value">${escapeHtml(data.total_qty)} ürün</div></div>
                </div>
                <div><div class="info-label">Adres</div><div class="info-value" style="font-size:10px;">${escapeHtml(data.shipping_address || data.partner_address)}</div><div class="info-value">${escapeHtml([data.shipping_district, data.shipping_city].filter(x=>x).join(' / '))}</div></div>
                <div class="cargo-section"><div class="info-label">Kargo Takip No</div><div class="tracking">${escapeHtml(cargoBarcode)}</div>${barcodeHtml}</div>
                <table><thead><tr><th>Ürün</th><th>Adet</th><th>Barkod</th></tr></thead><tbody>${itemsHtml}</tbody></table>
            </div>
        </body></html>`;

        this._printViaWindow(html);
    }

    _printViaWindow(html) {
        const win = window.open('', '_blank', 'width=800,height=600');
        if (!win) {
            this._printViaIframe(html);
            return;
        }
        win.document.write(html);
        win.document.close();

        // Yazdırma sonrası otomatik kapat + focus
        let _closed = false;
        const autoCloseAndFocus = () => {
            if (_closed) return;
            _closed = true;
            try { win.close(); } catch (e) { /* popup zaten kapanmış */ }
            // Popup kapandıktan sonra ana pencereye dön ve input'a focus ver
            setTimeout(() => this._autoFocus(), 400);
        };

        // afterprint event ile otomatik kapatma
        win.addEventListener('afterprint', () => {
            setTimeout(autoCloseAndFocus, 300);
        });

        const deadline = Date.now() + 5000;  // görsel yüklenemezse en geç 5 sn sonra yazdır
        const tryPrint = () => {
            const imgs = win.document.querySelectorAll('img');
            const allLoaded = Array.from(imgs).every(img => img.complete);
            if (allLoaded || imgs.length === 0 || Date.now() > deadline) {
                win.focus();
                win.print();
                // Fallback: afterprint desteklenmeyen tarayıcılar için
                // print() dialog kapandıktan sonra bu satır çalışır
                setTimeout(autoCloseAndFocus, 500);
            } else {
                setTimeout(tryPrint, 200);
            }
        };
        setTimeout(tryPrint, 600);
    }

    _printViaIframe(html) {
        const old = document.getElementById('ub-print-iframe');
        if (old) old.parentNode.removeChild(old);

        const iframe = document.createElement('iframe');
        iframe.id = 'ub-print-iframe';
        iframe.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;opacity:0;pointer-events:none;z-index:-9999;';
        document.body.appendChild(iframe);

        const doc = iframe.contentWindow.document;
        doc.open();
        doc.write(html);
        doc.close();

        let _cleaned = false;
        const autoCleanup = () => {
            if (_cleaned) return;
            _cleaned = true;
            try { iframe.parentNode.removeChild(iframe); } catch (e) {}
            setTimeout(() => this._autoFocus(), 400);
        };

        iframe.contentWindow.addEventListener('afterprint', () => {
            setTimeout(autoCleanup, 300);
        });

        const deadline = Date.now() + 5000;  // görsel yüklenemezse en geç 5 sn sonra yazdır
        const tryPrint = () => {
            const imgs = doc.querySelectorAll('img');
            const allLoaded = Array.from(imgs).every(img => img.complete);
            if (allLoaded || imgs.length === 0 || Date.now() > deadline) {
                iframe.contentWindow.focus();
                iframe.contentWindow.print();
                setTimeout(autoCleanup, 500);
            } else {
                setTimeout(tryPrint, 200);
            }
        };
        setTimeout(tryPrint, 600);
    }


}
