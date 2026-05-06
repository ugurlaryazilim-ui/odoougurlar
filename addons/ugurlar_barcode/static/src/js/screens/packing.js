/** @odoo-module **/

import { Component, useState, xml, onMounted } from "@odoo/owl";
import { BarcodeService, AudioFeedback } from "../barcode_service";
import { generateBarcodeSVG } from "./label_designer";

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
                        <label class="ub-field-label">Rota / Batch Numarası</label>
                        <div class="ub-input-group">
                            <input type="text" class="form-control ub-barcode-input"
                                   placeholder="TOPLAMA-2026-04-06-0930..."
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

                <!-- Bugünkü batch listesi -->
                <div class="ub-packing-batch-list" t-if="state.batches.length">
                    <div class="ub-section-title-dark" style="margin-top:0.8rem;">
                        <i class="fa fa-list"></i> Son Rotalar
                    </div>
                    <t t-foreach="state.batches" t-as="b" t-key="b.id">
                        <div class="ub-picking-row" t-on-click="() => this.loadBatch(b.id)">
                            <div class="ub-picking-info">
                                <div class="ub-picking-name" t-esc="b.name"/>
                                <div class="ub-picking-meta">
                                    <span class="badge bg-info" t-esc="b.time_window"/>
                                    <span class="badge bg-secondary" t-esc="b.state"/>
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
                <div class="ub-scan-area">
                    <div class="ub-input-group">
                        <input type="text" class="form-control ub-barcode-input"
                               placeholder="Ürün barkodunu okutun..."
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
                            <button class="btn btn-warning w-100 fw-bold" t-on-click="() => this.onBackorder(state.inc_picking_id)">
                                <i class="fa fa-exclamation-triangle"></i> Eksik Onayla (Backorder Yap)
                            </button>
                        </t>
                    </div>
                </t>

                <!-- Ürün listesi -->
                <div class="ub-product-list" t-if="state.items.length">
                    <t t-foreach="state.items" t-as="item" t-key="item.move_id">
                        <div t-attf-class="ub-product-row {{item.matched ? 'ub-line-done' : ''}}">
                            <div class="ub-packing-check">
                                <i t-attf-class="fa {{item.matched ? 'fa-check-square text-success' : 'fa-square-o text-muted'}} fa-lg"/>
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
                            t-att-disabled="state.loading">
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
                    <p t-esc="state.error"/>
                </div>
            </t>
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
            scanOk: false,
            // completed
            completed: false,
            completedPickings: [],
        });

        this._unsub = this.props.scanner.onScan(bc => {
            if (this.state.view === 'detail') {
                this.state.scanInput = bc;
                this.onScan();
            } else if (this.state.view === 'search') {
                this.state.routeInput = bc;
                this.searchRoute();
            }
        });

        onMounted(() => this.loadBatchList());
    }

    goBack() {
        if (this.state.view === 'detail') {
            this.state.view = 'search';
            this.state.error = null;
            this.state.completed = false;
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
            const res = await BarcodeService.call('/ugurlar_barcode/api/batch_list', {});
            this.state.batches = res.batches || [];
        } catch (e) {
            // sessiz
        }
    }

    onRouteKey(ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); this.searchRoute(); }
    }

    async searchRoute() {
        const name = this.state.routeInput.trim();
        if (!name) return;
        this.state.loading = true;
        this.state.error = null;
        try {
            const res = await BarcodeService.call('/ugurlar_barcode/api/packing_batch_detail', {
                batch_name: name,
            });
            if (res.error) {
                this.state.error = res.error;
            } else {
                this._setBatchDetail(res);
            }
        } catch (e) {
            this.state.error = 'Bağlantı hatası';
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
            } else {
                this._setBatchDetail(res);
            }
        } catch (e) {
            this.state.error = 'Bağlantı hatası';
        }
        this.state.loading = false;
    }

    _setBatchDetail(res) {
        this.state.batch = res.batch;
        this.state.items = res.items;
        this.state.total = res.total;
        this.state.matched = res.matched;
        this.state.all_matched = res.all_matched;
        this.state.view = 'detail';
        this.state.completed = false;
        this.state.inc_picking_id = null;
    }

    // ─── BARKOD TARAMA ──────────────────────────
    onScanKey(ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); this.onScan(); }
    }

    async onScan() {
        if (!this.state.scanInput.trim()) return;
        this.state.scanMsg = '';
        try {
            const res = await BarcodeService.call('/ugurlar_barcode/api/packing_scan', {
                batch_id: this.state.batch.id,
                barcode: this.state.scanInput.trim(),
            });
            if (res.error) {
                this.state.scanMsg = res.error;
                this.state.scanOk = false;
                AudioFeedback.playError();
            } else if (res.warning) {
                this.state.scanMsg = res.message;
                this.state.scanOk = true;
                AudioFeedback.playSuccess();
            } else {
                this.state.scanMsg = `${res.product_name} — ${res.picking_name} (${res.done_qty}/${res.demand_qty})`;
                this.state.scanOk = true;
                AudioFeedback.playSuccess();

                // Listeyi güncelle
                for (const item of this.state.items) {
                    if (item.move_id === undefined) continue;
                }
                const fresh = await BarcodeService.call('/ugurlar_barcode/api/packing_batch_detail', {
                    batch_id: this.state.batch.id,
                });
                if (!fresh.error) {
                    this.state.items = fresh.items;
                    this.state.matched = fresh.matched;
                    this.state.all_matched = fresh.all_matched;
                }

                // Eğer sipariş tamamen eşleştiyse kargo etiketini otomatik yazdır
                if (res.picking_completed && res.picking_id) {
                    this.state.scanMsg = res.picking_name + " siparişi eşleşti, etiket yazdırılıyor...";
                    
                    // Alt ekrandaki Kargo Etiketleri listesine anında ekle
                    this.state.completed = true;
                    this.state.inc_picking_id = null;
                    if (!this.state.completedPickings) this.state.completedPickings = [];
                    if (!this.state.completedPickings.find(p => p.picking_id === res.picking_id)) {
                        const matchedItem = this.state.items.find(i => i.picking_id === res.picking_id);
                        if (matchedItem) {
                            this.state.completedPickings.unshift({
                                id: res.picking_id,
                                picking_id: res.picking_id,
                                name: res.picking_name,
                                cargo_tracking: matchedItem.cargo_tracking,
                                cargo_provider: matchedItem.cargo_provider,
                                customer_name: matchedItem.customer_name,
                            });
                        }
                    }

                    // Otomatik yazdırmayı tetikle (Kargo etiketi servisi bitince pop-up açacak)
                    this.printLabel(res.picking_id);
                } else if (res.picking_id && res.remaining_items && res.remaining_items.length > 0) {
                    // Sipariş içerisinde okutulması gereken başka ürünler var
                    this.state.scanMsg = `${res.product_name} paketlendi ancak ${res.picking_name} siparişi BİTMEDİ. Lütfen şunları da okutun: ${res.remaining_items.join(', ')}`;
                    this.state.scanOk = false; // Farkındalık için kırmızı veya uyarı rengi
                    this.state.inc_picking_id = res.picking_id;
                    AudioFeedback.playError(); // Uyarı sesi
                }
            }
        } catch (e) {
            this.state.scanMsg = 'Hata';
            this.state.scanOk = false;
            this.state.inc_picking_id = null;
            AudioFeedback.playError();
        }
        this.state.scanInput = '';
    }

    // ─── TAMAMLA ─────────────────────────────────
    async onComplete() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const res = await BarcodeService.call('/ugurlar_barcode/api/packing_complete', {
                batch_id: this.state.batch.id,
            });
            if (res.errors && res.errors.length) {
                this.state.error = res.errors.join('\n');
            }
            if (res.success || res.validated > 0) {
                this.state.scanMsg = res.message;
                this.state.scanOk = true;
                this.state.completed = true;

                // Etiket bilgilerini hazırla
                const pickingInfos = [];
                for (const item of this.state.items) {
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
            }
        } catch (e) {
            this.state.error = 'Tamamlama hatası';
        }
        this.state.loading = false;
    }

    // ─── EKSİK ONAYLA (BACKORDER) ────────────────
    async onBackorder(pickingId) {
        if (!confirm('Eksik ürünlerle siparişi onaylayıp kapatmak istediğinize emin misiniz?')) return;
        this.state.loading = true;
        this.state.scanMsg = 'Backorder oluşturuluyor...';
        this.state.inc_picking_id = null;
        
        try {
            const res = await BarcodeService.call('/ugurlar_barcode/api/packing_backorder', {
                picking_id: pickingId,
            });
            if (res.error) {
                this.state.scanMsg = res.error;
                this.state.scanOk = false;
            } else {
                this.state.scanMsg = res.message;
                this.state.scanOk = true;
                
                // Detayı yeniden yükle
                const fresh = await BarcodeService.call('/ugurlar_barcode/api/packing_batch_detail', {
                    batch_id: this.state.batch.id,
                });
                if (!fresh.error) {
                    this.state.items = fresh.items;
                    this.state.matched = fresh.matched;
                    this.state.all_matched = fresh.all_matched;
                }
                
                // Otomatik etiket listesine ekle ve yazdır
                this.state.completed = true;
                if (!this.state.completedPickings) this.state.completedPickings = [];
                if (!this.state.completedPickings.find(p => p.picking_id === pickingId)) {
                    const matchedItem = this.state.items.find(i => i.picking_id === pickingId);
                    if (matchedItem) {
                        this.state.completedPickings.unshift({
                            id: pickingId,
                            picking_id: pickingId,
                            name: matchedItem.picking_name,
                            cargo_tracking: matchedItem.cargo_tracking,
                            cargo_provider: matchedItem.cargo_provider,
                            customer_name: matchedItem.customer_name,
                        });
                    }
                }
                setTimeout(() => {
                    this.printLabel(pickingId);
                }, 100);
            }
        } catch (e) {
            this.state.scanMsg = 'Bağlantı hatası';
            this.state.scanOk = false;
        }
        this.state.loading = false;
    }

    // ─── GERİ AL (UNDO) MİKTAR DÜŞÜRME ────────────
    async onDecreaseQty(pickingId, barcode) {
        if (!confirm('Bu ürünün okutulmuş miktarını 1 azaltmak istediğinize emin misiniz?')) return;
        this.state.loading = true;
        try {
            const res = await BarcodeService.call('/ugurlar_barcode/api/packing_undo', {
                picking_id: pickingId,
                barcode: barcode,
            });
            if (res.error) {
                this.state.scanMsg = res.error;
                this.state.scanOk = false;
            } else {
                this.state.scanMsg = res.message;
                this.state.scanOk = true;
                
                // Refresh detail
                const fresh = await BarcodeService.call('/ugurlar_barcode/api/packing_batch_detail', {
                    batch_id: this.state.batch.id,
                });
                if (!fresh.error) {
                    this.state.items = fresh.items;
                    this.state.matched = fresh.matched;
                    this.state.all_matched = fresh.all_matched;
                }
            }
        } catch (e) {
            this.state.scanMsg = 'Bağlantı hatası';
            this.state.scanOk = false;
        }
        this.state.loading = false;
    }

    // ─── ETİKET BAS ─────────────────────────────
    async printLabel(pickingId) {
        try {
            // 1. Sipariş verisi çek
            const data = await BarcodeService.call('/ugurlar_barcode/api/packing_label_data', {
                picking_id: pickingId,
            });
            if (data.error) {
                this.state.error = data.error;
                return;
            }

            // 2. Kayıtlı "Kargo" şablonunu çek
            let template = null;
            try {
                const res = await BarcodeService.labelTemplateList();
                const cargoTemplates = (res.templates || []).filter(t => t.name.startsWith('Kargo'));
                if (cargoTemplates.length > 0) {
                    template = cargoTemplates[0]; // İlk Kargo şablonunu kullan
                }
            } catch (e) {
                console.warn('Kargo şablonu yüklenemedi, varsayılan kullanılacak');
            }

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
        };
        return map[type] !== undefined ? map[type] : '';
    }

    _renderCargoTemplate(template, data) {
        const wMm = template.width_mm;
        const hMm = template.height_mm;

        // DEBUG — konsola boyut bilgisi yaz
        console.log('=== KARGO ETİKET BOYUT DEBUG ===');
        console.log('Template adı:', template.name);
        console.log('Template ID:', template.id);
        console.log('width_mm:', wMm, 'height_mm:', hMm);
        console.log('Template raw:', JSON.stringify({id: template.id, name: template.name, width_mm: template.width_mm, height_mm: template.height_mm}));

        let elementsHtml = '';
        for (const el of template.elements) {
            const x = el.x;
            const y = el.y;
            const w = el.width;
            const h = el.height;
            const fs = el.fontSize || 9;
            const fw = el.fontWeight || 'normal';
            const ta = el.textAlign || 'left';
            const color = el.color || '#000000';
            const bgColor = el.bgColor || 'transparent';
            const rotation = el.rotation || 0;

            let content = '';

            if (el.type === 'line') {
                const lineH = Math.max(h, 0.3);
                elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${lineH}mm; background:${color}; transform:rotate(${rotation}deg);"></div>`;
                continue;
            }

            if (el.type === 'box') {
                const bw = el.borderWidth || 1;
                elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; border:${bw}px solid ${color}; background:${bgColor}; transform:rotate(${rotation}deg);"></div>`;
                continue;
            }

            if (el.type === 'cargo_barcode') {
                const barcodeValue = data.cargo_tracking || '';
                if (barcodeValue) {
                    const encoded = encodeURIComponent(barcodeValue);
                    const imgW = Math.round(w * 12);
                    const imgH = Math.round(h * 12);
                    elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; transform:rotate(${rotation}deg); text-align:center;">
                        <img src="/report/barcode/Code128/${encoded}?width=${imgW}&height=${imgH}&humanreadable=1"
                            style="width:100%; height:100%; object-fit:contain; image-rendering:-webkit-crisp-edges; image-rendering:pixelated;"
                            onerror="this.style.display='none'" />
                    </div>`;
                }
                continue;
            }

            if (el.type === 'cargo_qr_code') {
                const qrValue = el.content || data.cargo_tracking || '';
                if (qrValue) {
                    elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; transform:rotate(${rotation}deg);"><img src="/report/barcode/?type=QR&value=${encodeURIComponent(qrValue)}&width=${Math.round(w * 12)}&height=${Math.round(h * 12)}" style="width:100%;height:100%;object-fit:contain;" /></div>`;
                }
                continue;
            }

            if (el.type === 'item_list') {
                const items = data.items || [];
                let tableHtml = '<table style="width:100%;border-collapse:collapse;font-size:inherit;"><thead><tr style="border-bottom:0.3mm solid #333;"><th style="text-align:left;padding:0 0.5mm;">#</th><th style="text-align:left;padding:0 0.5mm;">Ürün</th><th style="text-align:right;padding:0 0.5mm;">Adet</th><th style="text-align:left;padding:0 0.5mm;">Barkod</th></tr></thead><tbody>';
                items.forEach((item, idx) => {
                    tableHtml += `<tr><td style="padding:0 0.5mm;">${idx+1}</td><td style="padding:0 0.5mm;">${item.product_name}</td><td style="text-align:right;padding:0 0.5mm;">${item.qty}</td><td style="padding:0 0.5mm;">${item.barcode}</td></tr>`;
                });
                tableHtml += '</tbody></table>';
                elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; font-size:${fs}pt; font-weight:${fw}; overflow:hidden; color:${color}; background:${bgColor}; transform:rotate(${rotation}deg);">${tableHtml}</div>`;
                continue;
            }

            if (el.type === 'custom_text' || el.type === 'sender_name') {
                content = el.content || '';
            } else {
                content = this._getFieldValue(el.type, data);
            }

            elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; font-size:${fs}pt; font-weight:${fw}; text-align:${ta}; color:${color}; background:${bgColor}; transform:rotate(${rotation}deg); overflow:hidden; line-height:1.3; display:flex; align-items:center; ${ta === 'center' ? 'justify-content:center;' : ta === 'right' ? 'justify-content:flex-end;' : ''}">${content}</div>`;
        }

        const html = `<!DOCTYPE html><html><head>
            <meta charset="utf-8">
            <title>Kargo Etiketi ${wMm}x${hMm}mm — ${data.picking_name}</title>
            <style>
                @page {
                    size: ${wMm}mm ${hMm}mm !important;
                    margin: 0 !important;
                }
                * { margin:0; padding:0; box-sizing:border-box; }
                html, body {
                    margin:0 !important; padding:0 !important;
                    width: ${wMm}mm !important;
                    height: ${hMm}mm !important;
                }
                body {
                    font-family: Arial, Helvetica, sans-serif;
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }
                .label {
                    position: relative;
                    width: ${wMm}mm;
                    height: ${hMm}mm;
                    overflow: visible;
                    page-break-after: always;
                    page-break-inside: avoid;
                }
                img {
                    image-rendering: pixelated;
                    image-rendering: -moz-crisp-edges;
                    -ms-interpolation-mode: nearest-neighbor;
                }
                @media print {
                    @page {
                        size: ${wMm}mm ${hMm}mm !important;
                        margin: 0 !important;
                    }
                    html, body {
                        margin: 0 !important; padding: 0 !important;
                        width: ${wMm}mm !important;
                        height: ${hMm}mm !important;
                    }
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
            `<tr><td>${i.product_name}</td><td style="text-align:center;">${i.qty}</td><td style="text-align:center;">${i.barcode}</td></tr>`
        ).join('');

        const html = `<!DOCTYPE html><html><head>
            <meta charset="utf-8">
            <title>Kargo Etiketi — ${data.picking_name}</title>
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
                    <h2>${data.cargo_provider || 'KARGO'}</h2>
                    <span>${data.picking_name}</span>
                </div>
                <div class="info-grid">
                    <div><div class="info-label">Sipariş No</div><div class="info-value">${data.order_number || data.origin}</div></div>
                    <div><div class="info-label">Müşteri</div><div class="info-value">${data.customer_name || data.partner_name}</div></div>
                    <div><div class="info-label">Tel</div><div class="info-value">${data.partner_phone || '-'}</div></div>
                    <div><div class="info-label">Adet</div><div class="info-value">${data.total_qty} ürün</div></div>
                </div>
                <div><div class="info-label">Adres</div><div class="info-value" style="font-size:10px;">${data.shipping_address || data.partner_address}</div><div class="info-value">${[data.shipping_district, data.shipping_city].filter(x=>x).join(' / ')}</div></div>
                <div class="cargo-section"><div class="info-label">Kargo Takip No</div><div class="tracking">${cargoBarcode}</div>${barcodeHtml}</div>
                <table><thead><tr><th>Ürün</th><th>Adet</th><th>Barkod</th></tr></thead><tbody>${itemsHtml}</tbody></table>
            </div>
        </body></html>`;

        this._printViaWindow(html);
    }

    _printViaWindow(html) {
        // Yeni pencere aç — @page size desteği iframe'den daha güvenilir
        const win = window.open('', '_blank', `width=800,height=600`);
        if (!win) {
            // Popup engellenmiş — iframe fallback
            this._printViaIframe(html);
            return;
        }
        win.document.write(html);
        win.document.close();

        // Görsellerin (barkod, QR) yüklenmesini bekle, sonra yazdır
        const tryPrint = () => {
            const imgs = win.document.querySelectorAll('img');
            const allLoaded = Array.from(imgs).every(img => img.complete && img.naturalHeight > 0);
            if (allLoaded || imgs.length === 0) {
                win.focus();
                win.print();
            } else {
                setTimeout(tryPrint, 200);
            }
        };
        setTimeout(tryPrint, 600);
    }

    _printViaIframe(html) {
        // Popup engellendiğinde fallback — iframe ile yazdır
        const old = document.getElementById('ub-print-iframe');
        if (old) old.parentNode.removeChild(old);

        const iframe = document.createElement('iframe');
        iframe.id = 'ub-print-iframe';
        iframe.style.position = 'fixed';
        iframe.style.right = '0';
        iframe.style.bottom = '0';
        iframe.style.width = '300mm';
        iframe.style.height = '300mm';
        iframe.style.opacity = '0.01';
        iframe.style.border = '0';
        iframe.style.pointerEvents = 'none';
        iframe.style.zIndex = '-9999';
        document.body.appendChild(iframe);

        const doc = iframe.contentWindow.document;
        doc.open();
        doc.write(html);
        doc.close();

        const tryPrint = () => {
            const imgs = doc.querySelectorAll('img');
            const allLoaded = Array.from(imgs).every(img => img.complete && img.naturalHeight > 0);
            if (allLoaded || imgs.length === 0) {
                iframe.contentWindow.focus();
                iframe.contentWindow.print();
            } else {
                setTimeout(tryPrint, 200);
            }
        };
        setTimeout(tryPrint, 600);
    }

    willUnmount() {
        if (this._unsub) this._unsub();
    }
}
