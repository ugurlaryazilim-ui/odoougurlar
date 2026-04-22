/** @odoo-module **/

import { Component, useState, xml, onMounted } from "@odoo/owl";
import { BarcodeService, AudioFeedback } from "../barcode_service";

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
                <div class="bp-batch-list" t-if="!state.loading">
                    <t t-if="state.batches.length">
                        <t t-foreach="state.batches" t-as="b" t-key="b.id">
                            <div class="bp-batch-card" t-on-click="() => this.selectBatch(b.id)">
                                <div class="bp-batch-header">
                                    <span class="bp-batch-name" t-esc="b.name"/>
                                    <span t-attf-class="badge bp-state-{{b.state}}" t-esc="b.state === 'draft' ? 'Taslak' : b.state === 'in_progress' ? 'Devam' : b.state"/>
                                </div>
                                <div class="bp-batch-meta">
                                    <span><i class="fa fa-clock-o"></i> <t t-esc="b.time_window"/></span>
                                    <span><i class="fa fa-shopping-cart"></i> <t t-esc="b.total_orders"/> sipariş</span>
                                    <span><i class="fa fa-cube"></i> <t t-esc="b.total_items"/> ürün</span>
                                </div>
                                <div class="bp-batch-action">
                                    <button class="btn btn-success bp-btn-collect">
                                        <i class="fa fa-play"></i> Topla
                                    </button>
                                </div>
                            </div>
                        </t>
                    </t>
                    <div class="ub-no-stock" t-if="!state.batches.length">
                        <i class="fa fa-inbox"></i>
                        <p>Bekleyen rota yok</p>
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

                    <!-- Barkod bilgisi -->
                    <div class="bp-barcode-info">
                        <span>Barkod: <strong t-esc="state.currentItem.barcode"/></span>
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
                             t-on-error="onImageError"/>
                    </div>

                    <!-- SAĞ PANEL: Rota Listesi Tablosu -->
                    <div class="bp-route-table">
                        <div class="bp-route-table-header">
                            <span>Barkod</span>
                            <span>Sokak</span>
                            <span>Kat-Göz</span>
                            <span>Adet</span>
                            <span>Top.</span>
                        </div>
                        <t t-foreach="state.items" t-as="item" t-key="item.move_id">
                            <div t-attf-class="bp-route-table-row {{item.move_id === state.currentItem.move_id ? 'bp-row-active' : ''}} {{item.collected_qty >= item.demand_qty ? 'bp-row-done' : ''}}">
                                <span class="bp-cell-barcode" t-esc="(item.barcode || '').substring(0, 10) + (item.barcode.length > 10 ? '..' : '')"/>
                                <span t-esc="(item.location_parts || {}).zone || '-'"/>
                                <span>
                                    <t t-esc="(item.location_parts || {}).section || ''"/>
                                    <t t-if="(item.location_parts || {}).shelf"> - <t t-esc="item.location_parts.shelf"/></t>
                                </span>
                                <span t-esc="item.demand_qty"/>
                                <span class="d-flex justify-content-between align-items-center">
                                    <t t-esc="item.collected_qty"/>
                                    <button class="btn btn-sm text-danger p-0 ms-1" t-if="item.collected_qty > 0" t-on-click="() => this.onDecreaseQty(item)">
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
        });

        this._unsub = this.props.scanner.onScan(bc => {
            if (this.state.view === 'collect') {
                this.state.scanInput = bc;
                this.onScan();
            }
        });

        onMounted(() => this.loadBatches());
    }

    goBack() {
        if (this.state.view === 'collect') {
            this.state.view = 'list';
            this.state.error = null;
        } else if (this.state.view === 'summary') {
            this.state.view = 'list';
            this.loadBatches();
        } else {
            this.props.navigate('main');
        }
    }

    // ═══ LİSTE ═══
    async loadBatches() {
        this.state.loading = true;
        try {
            const res = await BarcodeService.call('/ugurlar_barcode/api/batch_list', {});
            this.state.batches = res.batches || [];
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
                return;
            }
            this.state.batch = res.batch;
            this.state.items = res.items || [];
            this._updateProgress();
            this._goToNextItem();
            this.state.view = 'collect';
        } catch (e) {
            this.state.error = 'Rota yüklenirken hata oluştu';
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
        }
        this.state.scanInput = '';
        this.state.scanMsg = '';

        // Input'a fokus
        setTimeout(() => {
            const inp = document.querySelector('.bp-scan-input');
            if (inp) inp.focus();
        }, 100);
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
                AudioFeedback.playError();
                this._vibrate(200);
            } else if (res.warning) {
                this.state.scanMsg = res.message;
                this.state.scanOk = true;
                AudioFeedback.playError(); // Uyarı, o yüzden hata sesi veya farklı
            } else {
                this.state.scanMsg = `✓ ${res.product_name} — ${res.collected_qty}/${res.demand_qty}`;
                this.state.scanOk = true;
                AudioFeedback.playSuccess();

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
                    setTimeout(() => {
                        this.state.currentItem = null;
                    }, 1000);
                }
            }
        } catch (e) {
            this.state.scanMsg = 'Tarama hatası';
            this.state.scanOk = false;
            AudioFeedback.playError();
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
            } else {
                this.state.scanMsg = res.message;
                this.state.scanOk = true;
                
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
            }
        } catch (e) {
            this.state.error = 'Tamamlama hatası';
        }
        this.state.loading = false;
    }

    // ═══ YARDIMCI ═══
    _vibrate(ms) {
        try { if (navigator.vibrate) navigator.vibrate(ms); } catch (e) {}
    }

    onImageError(ev) {
        ev.target.src = '/web/static/img/placeholder.png';
    }

    willUnmount() {
        if (this._unsub) this._unsub();
    }
}
