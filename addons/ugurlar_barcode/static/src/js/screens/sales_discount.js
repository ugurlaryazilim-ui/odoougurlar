/** @odoo-module **/

import { Component, useState, xml, onWillUnmount, onMounted, useRef } from "@odoo/owl";
import { BarcodeService, AudioFeedback } from "../barcode_service";
import { openCameraScanner } from "../camera_scanner";

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
                        
                        <div class="ub-customer-dropdown" t-if="state.showCustomerDropdown">
                            <t t-if="state.customerSearchLoading">
                                <div class="ub-customer-dropdown-item text-muted">
                                    <i class="fa fa-spinner fa-spin"></i> Nebim'de Aranıyor...
                                </div>
                            </t>
                            <t t-elif="state.customerSearchError">
                                <div class="ub-customer-dropdown-item text-danger">
                                    <i class="fa fa-exclamation-circle"></i> <t t-esc="state.customerSearchError"/>
                                </div>
                            </t>
                            <t t-elif="state.customerSearchResults.length > 0">
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
                        <div class="ub-dc-image" t-att-style="item.image_url ? 'cursor:pointer;' : ''" t-on-click="() => this.state.lightboxImage = item.image_url ? item.image_url.replace('image_128', 'image_1920') : null">
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
                            </div>

                            <div class="ub-dc-variant-info" t-if="item.stock_qty != null or item.color_name or item.size_name">
                                <span t-if="item.stock_qty != null"><i class="fa fa-cube"></i> Stok: <t t-esc="item.stock_qty"/> Adet</span>
                                <span class="ub-dc-vi-sep" t-if="item.stock_qty != null and (item.color_name or item.size_name)"> | </span>
                                <span t-if="item.color_name"><i class="fa fa-paint-brush"></i> Renk: <t t-esc="item.color_name"/></span>
                                <span class="ub-dc-vi-sep" t-if="item.color_name and item.size_name"> | </span>
                                <span t-if="item.size_name"><i class="fa fa-arrows-alt"></i> Beden: <t t-esc="item.size_name"/></span>
                            </div>

                            <!-- NAKİT / VADELİ FİYAT TABLOSU -->
                            <div class="ub-dc-price-table" t-if="item.retail_price > 0">
                                <div class="ub-dc-pt-row">
                                    <div class="ub-dc-pt-label">
                                        <span class="ub-dc-pt-badge ub-badge-cash">NAKİT</span>
                                    </div>
                                    <div class="ub-dc-pt-value" t-esc="formatPrice(item.retail_price)"/>
                                </div>
                                <div class="ub-dc-pt-row" t-if="item.installment_price > 0">
                                    <div class="ub-dc-pt-label">
                                        <span class="ub-dc-pt-badge ub-badge-installment">VADELİ</span>
                                    </div>
                                    <div class="ub-dc-pt-value" t-esc="formatPrice(item.installment_price)"/>
                                </div>
                            </div>

                            <div class="ub-dc-campaign" t-if="item.campaign_name">
                                <i class="fa fa-star"></i> Kampanya: <t t-esc="item.campaign_name"/>
                            </div>
                            
                            <!-- İNDİRİMLİ SON FİYATLAR -->
                            <div class="ub-dc-totals" t-if="item.discount_amount > 0 or item.final_price > 0">
                                <div class="ub-dc-discount" t-if="item.discount_amount > 0">
                                    <i class="fa fa-arrow-down"></i> -<t t-esc="formatPrice(item.discount_amount)"/> İndirim
                                </div>
                                <div class="ub-dc-final-prices" t-if="item.final_price > 0">
                                    <div class="ub-dc-fp-item ub-dc-fp-cash">
                                        <span class="ub-dc-fp-badge">NAKİT</span>
                                        <span class="ub-dc-fp-amount"><t t-esc="formatPrice(item.final_price)"/></span>
                                    </div>
                                    <div class="ub-dc-fp-item ub-dc-fp-installment" t-if="item.installment_final > 0">
                                        <span class="ub-dc-fp-badge">VADELİ</span>
                                        <span class="ub-dc-fp-amount"><t t-esc="formatPrice(item.installment_final)"/></span>
                                    </div>
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
                    <div class="ub-ds-row ub-ds-total-discount">
                        <span>Genel Toplam İndirim</span>
                        <div class="ub-ds-total-discount-right">
                            <span>-<t t-esc="formatPrice(state.summary.total_discount)"/></span>
                            <span class="ub-ds-savings-badge">%<t t-esc="savingsPercentage"/> Kazanç!</span>
                        </div>
                    </div>
                </t>

                <!-- NAKİT / VADELİ ÖDEME KARTLARI -->
                <div class="ub-ds-payment-cards">
                    <div class="ub-ds-pcard ub-ds-pcard-cash">
                        <div class="ub-ds-pcard-left">
                            <div class="ub-ds-pcard-icon">
                                <i class="fa fa-money"></i>
                            </div>
                            <div class="ub-ds-pcard-info">
                                <div class="ub-ds-pcard-title">Nakit Ödeme</div>
                                <div class="ub-ds-pcard-subtitle">Perakende satış fiyatı</div>
                            </div>
                        </div>
                        <div class="ub-ds-pcard-amount"><t t-esc="formatPrice(state.summary.total_final)"/></div>
                    </div>
                    <div class="ub-ds-pcard ub-ds-pcard-installment" t-if="state.summary.total_installment_final > 0">
                        <div class="ub-ds-pcard-left">
                            <div class="ub-ds-pcard-icon">
                                <i class="fa fa-credit-card"></i>
                            </div>
                            <div class="ub-ds-pcard-info">
                                <div class="ub-ds-pcard-title">Vadeli Ödeme</div>
                                <div class="ub-ds-pcard-subtitle">Taksitli satış fiyatı</div>
                            </div>
                        </div>
                        <div class="ub-ds-pcard-amount"><t t-esc="formatPrice(state.summary.total_installment_final)"/></div>
                    </div>
                </div>

                <button class="btn btn-danger w-100 mt-2" t-on-click="clearBasket">
                    <i class="fa fa-refresh"></i> Sepeti Temizle
                </button>
            </div>

            <!-- Lightbox Overlay -->
            <div t-if="state.lightboxImage" class="ub-lightbox" t-on-click="() => this.state.lightboxImage = null">
                <button class="ub-lightbox-close"><i class="fa fa-times"></i></button>
                <img t-att-src="state.lightboxImage" />
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
        let initialSummary = { total_retail: 0.0, total_discount: 0.0, total_final: 0.0, total_installment: 0.0, total_installment_discount: 0.0, total_installment_final: 0.0 };
        let initialCustomerCode = '';

        if (savedState) {
            try {
                const parsed = JSON.parse(savedState);
                initialBasket = parsed.basket || [];
                initialSummary = parsed.summary || initialSummary;
                initialCustomerCode = parsed.customerCode || '';
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
            customerSearchLoading: false,
            customerSearchError: null,
            customerSearchResults: [],
            lightboxImage: null
        });

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
            this.state.showCustomerDropdown = true;
            this.state.customerSearchLoading = true;
            this.state.customerSearchError = null;
            
            this._searchTimeout = setTimeout(async () => {
                try {
                    const res = await BarcodeService.call('/ugurlar_barcode/api/search_customer', { query: val.trim() });
                    this.state.customerSearchLoading = false;
                    
                    if (res && res.error) {
                        this.state.customerSearchError = res.error;
                    } else if (res && res.customers) {
                        this.state.customerSearchResults = res.customers;
                    } else {
                        this.state.customerSearchError = "Geçersiz yanıt alındı.";
                    }
                } catch (e) {
                    this.state.customerSearchLoading = false;
                    this.state.customerSearchError = "Bağlantı veya Sunucu Hatası!";
                    console.warn("Customer search failed", e);
                }
            }, 500);
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
                installment_price: 0,
                discount_amount: 0,
                installment_discount: 0,
                final_price: 0,
                installment_final: 0,
                campaign_name: '',
                upsell_message: '',
                color_name: '',
                size_name: '',
                stock_qty: null
            });
        }
        
        this.state.barcodeValue = '';
        if (this.barcodeInputRef.el) this.barcodeInputRef.el.focus();
        
        this.calculateDiscounts();
    }

    removeItem(uid) {
        this.state.basket = this.state.basket.filter(i => i.uid !== uid);
        this.saveState();
        if (this.state.basket.length > 0) {
            this.calculateDiscounts();
        } else {
            this.state.summary = { total_retail: 0, total_discount: 0, total_final: 0, total_installment: 0, total_installment_discount: 0, total_installment_final: 0 };
            this.saveState();
        }
    }

    clearBasket() {
        this.state.basket = [];
        this.state.summary = { total_retail: 0, total_discount: 0, total_final: 0, total_installment: 0, total_installment_discount: 0, total_installment_final: 0 };
        this.state.error = null;
        this.saveState();
        if (this.barcodeInputRef.el) this.barcodeInputRef.el.focus();
    }

    async calculateDiscounts() {
        if (this.state.basket.length === 0) return;

        this.state.loading = true;
        this.state.error = null;

        try {
            const payload = this.state.basket.map(i => ({ barcode: i.barcode, quantity: i.quantity }));
            
            const result = await BarcodeService.calculateDiscounts(payload, this.state.customerCode);
            
            if (result.error) {
                this.state.error = result.error;
                AudioFeedback.playError();
            } else if (result.success) {
                const newBasket = [];
                let notFoundItems = [];
                for (let i = 0; i < result.lines.length; i++) {
                    const line = result.lines[i];
                    if (line.not_found) {
                        notFoundItems.push(line.barcode);
                        continue;
                    }
                    newBasket.push({
                        uid: this.uidCounter++,
                        barcode: line.barcode,
                        quantity: line.quantity,
                        name: line.name,
                        image_url: line.image_url,
                        retail_price: line.retail_price,
                        installment_price: line.installment_price || 0,
                        discount_amount: line.discount_amount,
                        installment_discount: line.installment_discount || 0,
                        final_price: line.final_price,
                        installment_final: line.installment_final || 0,
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
        openCameraScanner((barcode) => {
            this.handleScan(barcode);
        });
    }
}
