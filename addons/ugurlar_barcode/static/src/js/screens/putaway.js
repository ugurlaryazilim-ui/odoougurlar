/** @odoo-module **/

import { Component, useState, useRef, xml, onWillUnmount, onMounted } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";
import { vibrate, vibrateError, speak } from "../sound_utils";


export class PutawayScreen extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-arrow-down"></i> Raflama
                </h2>
                <div class="ub-mode-toggle">
                    <button t-attf-class="btn btn-sm {{state.mode === 'putaway' ? 'ub-mode-active-green' : 'btn-outline-secondary'}}"
                            t-on-click="() => this.setMode('putaway')">
                        <i class="fa fa-arrow-down"></i> Rafla
                    </button>
                    <button t-attf-class="btn btn-sm {{state.mode === 'remove' ? 'ub-mode-active-red' : 'btn-outline-secondary'}}"
                            t-on-click="() => this.setMode('remove')">
                        <i class="fa fa-arrow-up"></i> Kaldır
                    </button>
                </div>
            </div>

            <!-- ADIM 1: RAF BARKODU -->
            <div class="ub-search-form" t-if="state.step === 1">
                <div class="ub-search-field">
                    <label class="ub-field-label">
                        <span class="ub-step-badge">1</span> Raf Barkodu
                    </label>
                    <div class="ub-barcode-input-group">
                        <input type="text" class="form-control ub-barcode-input"
                               placeholder="Raf barkodunu okutun..."
                               t-on-keydown="onShelfKey"
                               t-att-value="state.shelfBarcode"
                               t-on-input="(ev) => this.onShelfInput(ev)"
                               t-ref="shelfInput"/>
                        <button class="ub-scan-icon-btn" t-on-click="() => this.cameraScan('shelf')" title="Kamera ile tara">
                            <i class="fa fa-barcode"></i>
                        </button>
                    </div>
                </div>
                <button class="btn btn-primary ub-search-submit-btn" t-on-click="onShelfConfirm">
                    <i class="fa fa-check"></i> Raf Seç
                </button>
            </div>

            <!-- ADIM 2: ÜRÜN BARKODU + RAF BİLGİSİ -->
            <t t-if="state.step === 2">
                <!-- Seçilen raf bilgisi -->
                <div class="ub-shelf-info-section">
                    <div class="ub-shelf-detail-row">
                        <span class="ub-shelf-detail-label">Raf Yolu:</span>
                        <strong t-esc="state.shelfInfo.complete_name || state.shelfBarcode"/>
                    </div>
                    <div class="ub-shelf-detail-row" t-if="state.shelfInfo.warehouse">
                        <span class="ub-shelf-detail-label">Depo:</span>
                        <span t-esc="state.shelfInfo.warehouse"/>
                    </div>
                    <div class="ub-shelf-detail-row">
                        <span class="ub-shelf-detail-label">Toplam Adet:</span>
                        <strong class="ub-stock-positive" t-esc="state.shelfInfo.total_quantity || 0"/>
                    </div>
                    <button class="btn btn-sm btn-outline-secondary mt-2" t-on-click="changeShelf">
                        <i class="fa fa-refresh"></i> Raf Değiştir
                    </button>
                </div>

                <!-- Ürün barkod tara -->
                <div class="ub-search-form">
                    <div class="ub-search-field">
                        <label class="ub-field-label">
                            <span class="ub-step-badge">2</span> Ürün Barkodu
                        </label>
                        <div class="ub-barcode-input-group">
                            <input type="text" class="form-control ub-barcode-input"
                                   placeholder="Ürün barkodunu okutun..."
                                   t-on-keydown="onProductKey"
                                   t-att-value="state.productBarcode"
                                   t-on-input="(ev) => this.onProductInput(ev)"
                                   t-ref="productInput"/>
                            <button class="ub-scan-icon-btn" t-on-click="() => this.cameraScan('product')" title="Kamera ile tara">
                                <i class="fa fa-barcode"></i>
                            </button>
                        </div>
                    </div>
                    <div class="ub-qty-section">
                        <label class="ub-field-label">Adet</label>
                        <input type="number" class="form-control ub-qty-input-wide"
                               t-att-value="state.quantity" min="1"
                               t-on-input="onQuantityInput"/>
                    </div>
                    <button t-attf-class="btn ub-search-submit-btn {{state.mode === 'putaway' ? 'ub-action-putaway' : 'ub-action-remove'}}"
                            t-on-click="onExecute" t-att-disabled="state.loading || state.processing">
                        <i t-attf-class="fa {{state.mode === 'putaway' ? 'fa-arrow-down' : 'fa-arrow-up'}}"></i>
                        <t t-if="state.mode === 'putaway'"> Rafla</t>
                        <t t-else=""> Raftan Kaldır</t>
                    </button>
                </div>

                <!-- Bildirim alanı (başarı/hata) -->
                <t t-if="state.toast">
                    <div t-attf-class="ub-toast-card {{state.toast.type === 'success' ? 'ub-toast-success' : 'ub-toast-error'}}"
                         style="margin: 0.5rem 0; padding: 0.75rem 1rem; border-radius: 8px; display: flex; align-items: center; gap: 0.5rem; animation: fadeInUp 0.3s ease;">
                        <i t-attf-class="fa {{state.toast.type === 'success' ? 'fa-check-circle' : 'fa-exclamation-triangle'}}"
                           style="font-size: 1.3rem;"></i>
                        <span t-esc="state.toast.message" style="flex:1;"/>
                    </div>
                </t>

                <!-- Raftaki ürünler tablosu -->
                <t t-if="state.shelfProducts.length">
                    <div class="ub-variants-section">
                        <div class="ub-section-title-dark" style="display:flex; justify-content:space-between; align-items:center;">
                            <span><i class="fa fa-cubes"></i> Raftaki Ürünler</span>
                            <span class="ub-table-summary">
                                <t t-esc="state.shelfProducts.length"/> ürün
                            </span>
                        </div>
                        <div class="ub-variant-table-wrap">
                            <table class="ub-variant-table ub-variant-table-striped">
                                <thead>
                                    <tr>
                                        <th>Kod</th>
                                        <th>Adı</th>
                                        <th>Barkod</th>
                                        <th class="text-end">Adet</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <t t-foreach="state.shelfProducts" t-as="p" t-key="p.id">
                                        <tr style="cursor:pointer" t-on-click="() => this.showProductHistory(p)" title="Stok geçmişini gör">
                                            <td t-esc="p.code || '-'"/>
                                            <td><strong t-esc="p.name"/></td>
                                            <td class="ub-barcode-cell" t-esc="p.barcode || '-'"/>
                                            <td class="text-end">
                                                <span class="ub-stock-positive" t-esc="p.quantity"/>
                                            </td>
                                        </tr>
                                    </t>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </t>

                <!-- STOK GEÇMİŞİ MODALI -->
                <t t-if="state.historyModal">
                    <div class="ub-modal-overlay" t-on-click="closeHistoryModal">
                        <div class="ub-modal-content" t-on-click.stop="">
                            <div class="ub-modal-header">
                                <h3><i class="fa fa-history"></i> Stok Geçmişi</h3>
                                <button class="btn btn-sm btn-outline-secondary" t-on-click="closeHistoryModal">
                                    <i class="fa fa-times"></i>
                                </button>
                            </div>
                            <div class="ub-modal-product-name">
                                <strong t-esc="state.historyModal.productName"/>
                            </div>
                            <t t-if="state.historyModal.loading">
                                <div class="ub-loading"><i class="fa fa-spinner fa-spin"></i> Yükleniyor...</div>
                            </t>
                            <t t-elif="state.historyModal.items.length === 0">
                                <div style="text-align:center;padding:1rem;color:#999;">
                                    <i class="fa fa-inbox" style="font-size:1.5rem;"></i>
                                    <p>Henüz işlem geçmişi yok</p>
                                </div>
                            </t>
                            <t t-else="">
                                <div class="ub-variant-table-wrap">
                                    <table class="ub-variant-table ub-variant-table-striped">
                                        <thead>
                                            <tr>
                                                <th>İşlem</th>
                                                <th>Konum</th>
                                                <th class="text-end">Adet</th>
                                                <th>Tarih</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            <t t-foreach="state.historyModal.items" t-as="h" t-key="h.id">
                                                <tr>
                                                    <td t-esc="h.type_label"/>
                                                    <td style="font-size:0.8rem" t-esc="h.location"/>
                                                    <td class="text-end"><strong t-esc="h.quantity"/></td>
                                                    <td style="font-size:0.75rem;color:#666" t-esc="h.date"/>
                                                </tr>
                                            </t>
                                        </tbody>
                                    </table>
                                </div>
                            </t>
                        </div>
                    </div>
                </t>
            </t>

            <t t-if="state.loading">
                <div class="ub-loading"><i class="fa fa-spinner fa-spin fa-2x"></i><p>İşleniyor...</p></div>
            </t>

            <t t-if="state.error">
                <div class="ub-error-card"><i class="fa fa-exclamation-triangle"></i><p t-esc="state.error"/></div>
            </t>

            <!-- SON İŞLEMLER -->
            <div class="ub-variants-section" t-if="state.history.length" style="margin-top:0.5rem;">
                <div class="ub-section-title-dark">
                    <i class="fa fa-history"></i> Son İşlemler
                </div>
                <div class="ub-variant-table-wrap">
                    <table class="ub-variant-table ub-variant-table-striped">
                        <thead>
                            <tr>
                                <th>İşlem</th>
                                <th>Detay</th>
                            </tr>
                        </thead>
                        <tbody>
                            <t t-foreach="state.history" t-as="h" t-key="h.time">
                                <tr>
                                    <td>
                                        <i t-attf-class="fa {{h.type === 'putaway' ? 'fa-arrow-down' : 'fa-arrow-up'}}"
                                           t-attf-style="color: {{h.type === 'putaway' ? '#27ae60' : '#e74c3c'}}"></i>
                                        <t t-if="h.type === 'putaway'"> Raflama</t>
                                        <t t-else=""> Kaldırma</t>
                                    </td>
                                    <td t-esc="h.message"/>
                                </tr>
                            </t>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;

    static props = { navigate: Function, scanner: Object };

    setup() {
        // OWL useRef — DOM erişimi için best-practice
        this.shelfInputRef = useRef('shelfInput');
        this.productInputRef = useRef('productInput');

        this.state = useState({
            mode: 'putaway',
            step: 1,
            shelfBarcode: '',
            shelfInfo: {},
            shelfProducts: [],
            productBarcode: '',
            quantity: 1,
            loading: false,
            processing: false,
            error: null,
            success: null,
            toast: null,
            history: [],
            historyModal: null,  // Stok geçmişi modali
        });

        // Barkod okuyucu — SADECE scanner callback kullanılır
        this._unsub = this.props.scanner.onScan(bc => this.onScanDetected(bc));

        onMounted(() => this._focusCurrentInput());

        onWillUnmount(() => {
            if (this._unsub) this._unsub();
            if (this._toastTimer) clearTimeout(this._toastTimer);
        });
    }

    _focusCurrentInput() {
        setTimeout(() => {
            const el = this.state.step === 1
                ? this.shelfInputRef.el
                : this.productInputRef.el;
            if (el) el.focus();
        }, 100);
    }

    onQuantityInput(ev) {
        this.state.quantity = Math.max(1, Number.parseInt(ev.target.value, 10) || 1);
    }

    setMode(mode) {
        this.state.mode = mode;
        this.state.error = null;
        this.state.success = null;
        this.state.toast = null;
    }

    _showToast(type, message) {
        this.state.toast = { type, message };
        if (this._toastTimer) clearTimeout(this._toastTimer);
        this._toastTimer = setTimeout(() => {
            this.state.toast = null;
        }, 4000);
    }

    // ─── BARKOD OKUYUCU CALLBACK ─────────────────
    onScanDetected(bc) {
        if (this.state.processing) return; // Kilit varsa atla
        if (this.state.step === 1) {
            this.state.shelfBarcode = bc;
            this.onShelfConfirm();
        } else if (this.state.step === 2) {
            this.state.productBarcode = bc;
            this.onExecute();
        }
    }

    // ─── ADIM 1: RAF TARA ─────────────────────────
    onShelfInput(ev) {
        this.state.shelfBarcode = ev.target.value;
        // _detectScan KALDIRILDI — scanner callback yeterli
        // Manuel giriş için sadece Enter kullanılır
    }

    onShelfKey(ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); this.onShelfConfirm(); }
    }

    async onShelfConfirm() {
        if (!this.state.shelfBarcode.trim()) return;
        if (this.state.loading) return;
        this.state.loading = true;
        this.state.error = null;
        try {
            const result = await BarcodeService.shelfControl(this.state.shelfBarcode.trim());
            if (result.error) {
                this.state.error = result.error;
            } else {
                this.state.shelfInfo = {
                    ...result.location,
                    total_quantity: result.total_quantity,
                };
                this.state.shelfProducts = result.products || [];
                this.state.step = 2;
                // Ürün inputuna focus
                this._focusCurrentInput();
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
        this.state.shelfProducts = [];
        this.state.productBarcode = '';
        this.state.error = null;
        this.state.success = null;
        this.state.toast = null;
        this._focusCurrentInput();
    }

    // ─── ADIM 2: ÜRÜN TARA + İŞLEM ───────────────
    onProductInput(ev) {
        this.state.productBarcode = ev.target.value;
        // _detectScan KALDIRILDI — scanner callback yeterli
        // Manuel giriş için sadece Enter kullanılır
    }

    onProductKey(ev) {
        if (ev.key === 'Enter') {
            ev.preventDefault();
            this.onExecute();
        }
    }

    async onExecute() {
        const barcode = this.state.productBarcode.trim();
        if (!barcode) return;

        // ─── ÇIFT TETİKLENME KİLİDİ ───
        if (this.state.processing) {
            return;
        }

        // ─── QUANTITY VALIDATION (raftan kaldırmada) ───
        if (this.state.mode === 'remove') {
            const qty = this.state.quantity;
            const existingProduct = this.state.shelfProducts.find(
                p => p.barcode === barcode || p.code === barcode
            );
            if (existingProduct && qty > existingProduct.quantity) {
                const msg = `Yetersiz stok! Rafta ${existingProduct.quantity} adet var, ${qty} adet kaldıramazsınız.`;
                this.state.error = msg;
                this._showToast('error', msg);
                speak('putaway_product_not_found');
                vibrateError();
                return;
            }
        }

        this.state.processing = true;
        this.state.loading = true;
        this.state.error = null;
        this.state.success = null;
        this.state.toast = null;

        try {
            const qty = this.state.quantity;
            const shelf = this.state.shelfBarcode.trim();
            const mode = this.state.mode;

            const res = mode === 'putaway'
                ? await BarcodeService.putaway(barcode, shelf, qty)
                : await BarcodeService.removeFromShelf(barcode, shelf, qty);

            if (res.error) {
                this.state.error = res.error;
                this._showToast('error', res.error);
                speak('putaway_product_not_found');
                vibrateError();
            } else {
                const actionText = mode === 'putaway' ? '✅ Raflama başarılı' : '✅ Raftan kaldırıldı';
                const msg = `${actionText}: ${res.message || barcode}`;
                this.state.success = msg;
                this._showToast('success', msg);

                if (mode === 'putaway') {
                    speak('putaway_product_shelved');
                } else {
                    speak('putaway_product_removed');
                }
                vibrate();

                this.state.history.unshift({
                    type: mode,
                    message: res.message || barcode,
                    time: Date.now(),
                });
                if (this.state.history.length > 10) this.state.history.pop();

                // Raf bilgisini güncelle
                this._refreshShelf();

                // Barkod alanını temizle, yeni okutmaya hazır
                this.state.productBarcode = '';
                this.state.quantity = 1;
                this._focusCurrentInput();
            }
        } catch (e) {
            this.state.error = 'Hata: ' + (e.message || e);
            this._showToast('error', 'Hata: ' + (e.message || e));
            speak('putaway_error');
        }

        this.state.loading = false;
        // Kilidi kısa bir gecikme ile kaldır — scanner debounce
        setTimeout(() => {
            this.state.processing = false;
        }, 600);
    }

    async _refreshShelf() {
        try {
            const result = await BarcodeService.shelfControl(this.state.shelfBarcode.trim());
            if (!result.error) {
                this.state.shelfInfo.total_quantity = result.total_quantity;
                this.state.shelfProducts = result.products || [];
            }
        } catch (e) {}
    }

    resetProduct() {
        this.state.productBarcode = '';
        this.state.quantity = 1;
        this.state.error = null;
        this.state.success = null;
        this.state.toast = null;
        this._focusCurrentInput();
    }

    // ─── STOK GEÇMİŞİ MODAL ──────────────────────
    async showProductHistory(product) {
        this.state.historyModal = {
            productName: product.name,
            productId: product.product_id || product.id,
            loading: true,
            items: [],
        };

        try {
            const locationId = this.state.shelfInfo?.id || 0;
            const res = await BarcodeService.productShelfHistory(
                product.product_id || product.id,
                locationId
            );
            if (res.history) {
                this.state.historyModal.items = res.history;
            }
        } catch (e) {}
        this.state.historyModal.loading = false;
    }

    closeHistoryModal() {
        this.state.historyModal = null;
    }

    // ─── KAMERA TARAYICI ──────────────────────────
    cameraScan(target) {
        if (!('BarcodeDetector' in window)) {
            alert('Bu tarayıcı kamera ile barkod okumayı desteklemiyor.\nChrome (Android) veya Edge kullanın.');
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
            statusEl.textContent = `${target === 'shelf' ? 'Raf' : 'Ürün'} barkodunu kameraya gösterin...`;
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
                            this.onShelfConfirm();
                        } else {
                            this.state.productBarcode = barcodes[0].rawValue;
                            this.onExecute();
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

}
