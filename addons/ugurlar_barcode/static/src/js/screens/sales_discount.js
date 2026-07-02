/** @odoo-module **/

import { Component, useState, xml, onWillUnmount, onMounted, useRef } from "@odoo/owl";
import { BarcodeService, AudioFeedback } from "../barcode_service";

export class SalesDiscount extends Component {
    static template = xml`
        <div class="ub-screen ub-discount-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-tags"></i> Fiyat ve İndirim Gör
                </h2>
            </div>

            <!-- Müşteri ve Barkod Giriş Alanı -->
            <div class="ub-discount-inputs">
                <div class="ub-input-row">
                    <div class="ub-input-group">
                        <i class="fa fa-user"></i>
                        <input type="text"
                               class="form-control"
                               placeholder="Müşteri Kartı / Telefon"
                               t-att-value="state.customerCode"
                               t-on-input="onCustomerInput"
                               t-on-keydown="(ev) => ev.key === 'Enter' and this.calculateDiscounts()"/>
                    </div>
                    <div class="ub-customer-dropdown" t-if="state.showCustomerDropdown">
                        <t t-if="state.customerSearchResults.length > 0">
                            <t t-foreach="state.customerSearchResults" t-as="cust" t-key="cust.id">
                                <div class="ub-customer-dropdown-item" t-on-click="() => this.selectCustomer(cust)">
                                    <span class="ub-cd-name"><t t-esc="cust.name"/></span>
                                    <span class="ub-cd-phone"><t t-esc="cust.phone || cust.customer_code"/></span>
                                </div>
                            </t>
                        </t>
                        <t t-else="">
                            <div class="ub-customer-dropdown-item text-muted">Sonuç bulunamadı.</div>
                        </t>
                    </div>
                </div>
                
                <div class="ub-input-row">
                    <div class="ub-input-group">
                        <i class="fa fa-barcode"></i>
                        <input type="text"
                               class="form-control ub-barcode-input"
                               placeholder="Ürün Barkodu Okutun..."
                               t-on-keydown="(ev) => this.onBarcodeKeydown(ev)"
                               t-att-value="state.barcodeValue"
                               t-on-input="(ev) => this.onBarcodeInput(ev)"
                               t-ref="barcodeInput"/>
                        <button class="btn ub-scan-btn" t-on-click="startCameraScan">
                            <i class="fa fa-camera"></i>
                        </button>
                    </div>
                </div>
            </div>

            <t t-if="state.loading">
                <div class="ub-loading">
                    <i class="fa fa-spinner fa-spin fa-2x"></i>
                    <p>Kampanyalar Hesaplanıyor...</p>
                </div>
            </t>

            <t t-if="state.error">
                <div class="ub-error-card">
                    <i class="fa fa-exclamation-triangle"></i>
                    <p t-esc="state.error"/>
                </div>
            </t>

            <!-- Sepet Listesi -->
            <div class="ub-discount-list" t-if="state.basket.length > 0">
                <t t-foreach="state.basket" t-as="item" t-key="item.uid">
                    <div class="ub-discount-card">
                        <div class="ub-dc-image">
                            <img t-if="item.image_url" t-att-src="item.image_url" alt="Ürün" />
                            <i t-else="" class="fa fa-box fa-3x text-muted"></i>
                        </div>
                        <div class="ub-dc-details">
                            <div class="ub-dc-header">
                                <span class="ub-dc-name" t-esc="item.name || item.barcode"/>
                                <button class="btn ub-btn-remove" t-on-click="() => this.removeItem(item.uid)">
                                    <i class="fa fa-trash"></i>
                                </button>
                            </div>
                            <div class="ub-dc-barcode" t-esc="item.barcode"/>
                            
                            <div class="ub-dc-qty-price">
                                <span class="ub-dc-qty"><t t-esc="item.quantity"/> Adet</span>
                                <span class="ub-dc-price" t-if="item.retail_price">x <t t-esc="formatPrice(item.retail_price)"/></span>
                            </div>

                            <div class="ub-dc-variant-info" t-if="item.stock_qty != null or item.color_name or item.size_name">
                                <span t-if="item.stock_qty != null"><i class="fa fa-cube"></i> Stok: <t t-esc="item.stock_qty"/> Adet</span>
                                <span class="ub-dc-vi-sep" t-if="item.stock_qty != null and (item.color_name or item.size_name)"> | </span>
                                <span t-if="item.color_name"><i class="fa fa-paint-brush"></i> Renk: <t t-esc="item.color_name"/></span>
                                <span class="ub-dc-vi-sep" t-if="item.color_name and item.size_name"> | </span>
                                <span t-if="item.size_name"><i class="fa fa-arrows-alt"></i> Beden: <t t-esc="item.size_name"/></span>
                            </div>

                            <div class="ub-dc-campaign" t-if="item.campaign_name">
                                <i class="fa fa-star"></i> Kampanya: <t t-esc="item.campaign_name"/>
                            </div>
                            
                            <div class="ub-dc-totals">
                                <div class="ub-dc-discount" t-if="item.discount_amount > 0">
                                    -<t t-esc="formatPrice(item.discount_amount)"/> İndirim
                                </div>
                                <div class="ub-dc-final" t-if="item.final_price > 0">
                                    <t t-esc="formatPrice(item.final_price)"/>
                                </div>
                            </div>
                            
                            <!-- Upsell Warning -->
                            <div class="ub-upsell-warning" t-if="item.upsell_message">
                                <i class="fa fa-info-circle"></i> <t t-esc="item.upsell_message"/>
                            </div>
                        </div>
                    </div>
                </t>
            </div>
            <div class="ub-empty-state" t-else="">
                <i class="fa fa-shopping-basket fa-4x text-muted mb-3"></i>
                <h4>Sepet Boş</h4>
                <p>İndirimleri görmek için ürün barkodu okutun.</p>
            </div>

            <!-- Dip Toplam -->
            <div class="ub-discount-summary" t-if="state.basket.length > 0">
                <div class="ub-ds-row">
                    <span>Ara Toplam</span>
                    <span><t t-esc="formatPrice(state.summary.total_retail)"/></span>
                </div>
                <t t-if="state.summary.total_discount > 0">
                    <t t-foreach="campaignTotals" t-as="camp" t-key="camp.name">
                        <div class="ub-ds-row ub-ds-discount">
                            <span><t t-esc="camp.name"/></span>
                            <span>-<t t-esc="formatPrice(camp.amount)"/></span>
                        </div>
                    </t>
                    <div class="ub-ds-row ub-ds-discount" style="border-top: 1px dashed #dc3545; padding-top: 5px; margin-top: 5px; font-weight: bold;">
                        <span>Genel Toplam İndirim</span>
                        <div>
                            <span>-<t t-esc="formatPrice(state.summary.total_discount)"/></span>
                            <span class="ub-ds-savings-badge">%<t t-esc="savingsPercentage"/> Kazanç!</span>
                        </div>
                    </div>
                </t>
                <div class="ub-ds-row ub-ds-grand">
                    <span>Ödenecek Tutar</span>
                    <span><t t-esc="formatPrice(state.summary.total_final)"/></span>
                </div>
                <button class="btn btn-danger w-100 mt-2" t-on-click="clearBasket">
                    <i class="fa fa-refresh"></i> Sepeti Temizle
                </button>
            </div>
        </div>
    `;

    static props = {
        navigate: Function,
        scanner: Object,
    };

    setup() {
        this.barcodeInputRef = useRef('barcodeInput');
        this.uidCounter = 1;

        // localStorage'dan yükle
        const savedState = localStorage.getItem('ub_discount_state');
        let initialBasket = [];
        let initialSummary = { total_retail: 0.0, total_discount: 0.0, total_final: 0.0 };
        let initialCustomerCode = '';

        if (savedState) {
            try {
                const parsed = JSON.parse(savedState);
                initialBasket = parsed.basket || [];
                initialSummary = parsed.summary || initialSummary;
                initialCustomerCode = parsed.customerCode || '';
                // En büyük uid'yi bul
                if (initialBasket.length > 0) {
                    this.uidCounter = Math.max(...initialBasket.map(i => i.uid || 0)) + 1;
                }
            } catch (e) {}
        }

        this.state = useState({
            barcodeValue: '',
            customerCode: initialCustomerCode,
            loading: false,
            error: null,
            basket: initialBasket, 
            summary: initialSummary,
            showCustomerDropdown: false,
            customerSearchResults: []
        });

        // Fiziksel barkod okuyucu dinleyicisi
        this._unsubscribe = this.props.scanner.onScan(barcode => {
            this.handleScan(barcode);
        });

        onMounted(() => {
            if (this.barcodeInputRef.el) this.barcodeInputRef.el.focus();
        });

        onWillUnmount(() => {
            if (this._unsubscribe) this._unsubscribe();
        });
    }

    get campaignTotals() {
        const totals = {};
        for (let item of this.state.basket) {
            if (item.campaign_name && item.discount_amount > 0) {
                totals[item.campaign_name] = (totals[item.campaign_name] || 0) + item.discount_amount;
            }
        }
        return Object.entries(totals).map(([name, amount]) => ({ name, amount }));
    }

    get savingsPercentage() {
        if (this.state.summary.total_retail > 0) {
            return Math.round((this.state.summary.total_discount / this.state.summary.total_retail) * 100);
        }
        return 0;
    }

    saveState() {
        localStorage.setItem('ub_discount_state', JSON.stringify({
            basket: this.state.basket,
            summary: this.state.summary,
            customerCode: this.state.customerCode
        }));
    }

    formatPrice(price) {
        if (price == null || isNaN(price)) return '₺0,00';
        return '₺' + Number(price).toLocaleString('tr-TR', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    async onCustomerInput(ev) {
        const val = ev.target.value;
        this.state.customerCode = val;
        this.saveState();
        
        if (this._searchTimeout) {
            clearTimeout(this._searchTimeout);
        }
        
        if (val.trim().length >= 3) {
            this._searchTimeout = setTimeout(async () => {
                try {
                    const res = await BarcodeService.call('/ugurlar_barcode/api/search_customer', { query: val.trim() });
                    if (res && res.customers) {
                        this.state.customerSearchResults = res.customers;
                        this.state.showCustomerDropdown = true;
                    }
                } catch (e) {
                    console.warn("Customer search failed", e);
                }
            }, 500); // 500ms gecikme (debounce)
        } else {
            this.state.showCustomerDropdown = false;
        }
    }

    selectCustomer(customer) {
        this.state.customerCode = customer.customer_code || customer.phone || customer.name;
        this.state.showCustomerDropdown = false;
        this.saveState();
        if (this.state.basket.length > 0) {
            this.calculateDiscounts();
        }
    }

    onBarcodeInput(ev) {
        this.state.barcodeValue = ev.target.value;
    }

    onBarcodeKeydown(ev) {
        if (ev.key === 'Enter') {
            ev.preventDefault();
            const val = ev.target.value.trim();
            if (val) {
                this.handleScan(val);
            }
        }
    }

    handleScan(barcode) {
        if (!barcode) return;
        
        // Sepette varsa miktar artır, yoksa ekle
        const existing = this.state.basket.find(i => i.barcode === barcode);
        if (existing) {
            existing.quantity += 1;
        } else {
            this.state.basket.push({
                uid: this.uidCounter++,
                barcode: barcode,
                quantity: 1,
                name: 'Hesaplanıyor...',
                image_url: '',
                retail_price: 0,
                discount_amount: 0,
                final_price: 0,
                campaign_name: '',
                upsell_message: '',
                color_name: '',
                size_name: '',
                stock_qty: null
            });
        }
        
        this.state.barcodeValue = '';
        if (this.barcodeInputRef.el) this.barcodeInputRef.el.focus();
        
        // Yeniden hesapla
        this.calculateDiscounts();
    }

    removeItem(uid) {
        this.state.basket = this.state.basket.filter(i => i.uid !== uid);
        this.saveState();
        if (this.state.basket.length > 0) {
            this.calculateDiscounts();
        } else {
            this.state.summary = { total_retail: 0, total_discount: 0, total_final: 0 };
            this.saveState();
        }
    }

    clearBasket() {
        this.state.basket = [];
        this.state.summary = { total_retail: 0, total_discount: 0, total_final: 0 };
        this.state.error = null;
        this.saveState();
        if (this.barcodeInputRef.el) this.barcodeInputRef.el.focus();
    }

    async calculateDiscounts() {
        if (this.state.basket.length === 0) return;

        this.state.loading = true;
        this.state.error = null;

        try {
            // Sadece barcode ve quantity gönderiyoruz
            const payload = this.state.basket.map(i => ({ barcode: i.barcode, quantity: i.quantity }));
            
            const result = await BarcodeService.calculateDiscounts(payload, this.state.customerCode);
            
            if (result.error) {
                this.state.error = result.error;
                AudioFeedback.playError();
            } else if (result.success) {
                // Sepeti gelen sonuca göre güncelle (isim, fiyatlar, resim)
                // Gelen liste ile sepeti eşleştir
                const newBasket = [];
                let notFoundItems = [];
                for (let i = 0; i < result.lines.length; i++) {
                    const line = result.lines[i];
                    if (line.not_found) {
                        notFoundItems.push(line.barcode);
                        continue; // Sepete ekleme
                    }
                    newBasket.push({
                        uid: this.uidCounter++,
                        barcode: line.barcode,
                        quantity: line.quantity,
                        name: line.name,
                        image_url: line.image_url,
                        retail_price: line.retail_price,
                        discount_amount: line.discount_amount,
                        final_price: line.final_price,
                        campaign_name: line.campaign_name,
                        upsell_message: line.upsell_message,
                        color_name: line.color_name,
                        size_name: line.size_name,
                        stock_qty: line.stock_qty
                    });
                }
                this.state.basket = newBasket;
                this.state.summary = result.summary;
                this.saveState();
                
                if (notFoundItems.length > 0) {
                    this.state.error = 'Ürün Bulunamadı: ' + notFoundItems.join(', ');
                    AudioFeedback.playError();
                } else {
                    AudioFeedback.playSuccess();
                }
            }
        } catch (e) {
            this.state.error = 'Bağlantı Hatası: ' + (e.message || e);
            AudioFeedback.playError();
        } finally {
            this.state.loading = false;
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
            this.handleScan(barcode);
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
}
