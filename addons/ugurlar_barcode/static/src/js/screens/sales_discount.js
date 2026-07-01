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
                               t-on-change="onCustomerChange"
                               t-on-keydown="(ev) => ev.key === 'Enter' and this.calculateDiscounts()"/>
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

                            <div class="ub-dc-campaign" t-if="item.campaign_name">
                                <i class="fa fa-star"></i> <t t-esc="item.campaign_name"/>
                            </div>
                            
                            <div class="ub-dc-totals">
                                <div class="ub-dc-discount" t-if="item.discount_amount > 0">
                                    -<t t-esc="formatPrice(item.discount_amount)"/> İndirim
                                </div>
                                <div class="ub-dc-final" t-if="item.final_price > 0">
                                    <t t-esc="formatPrice(item.final_price)"/>
                                </div>
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
                <div class="ub-ds-row ub-ds-discount" t-if="state.summary.total_discount > 0">
                    <span>Toplam İndirim</span>
                    <span>-<t t-esc="formatPrice(state.summary.total_discount)"/></span>
                </div>
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

        this.state = useState({
            barcodeValue: '',
            customerCode: '',
            loading: false,
            error: null,
            basket: [], // { uid, barcode, quantity, name, image_url, retail_price, discount_amount, final_price, campaign_name }
            summary: {
                total_retail: 0.0,
                total_discount: 0.0,
                total_final: 0.0
            }
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

    formatPrice(price) {
        if (price == null || isNaN(price)) return '₺0,00';
        return '₺' + Number(price).toLocaleString('tr-TR', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    onCustomerChange(ev) {
        this.state.customerCode = ev.target.value.trim();
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
                campaign_name: ''
            });
        }
        
        this.state.barcodeValue = '';
        if (this.barcodeInputRef.el) this.barcodeInputRef.el.focus();
        
        // Yeniden hesapla
        this.calculateDiscounts();
    }

    removeItem(uid) {
        this.state.basket = this.state.basket.filter(i => i.uid !== uid);
        if (this.state.basket.length > 0) {
            this.calculateDiscounts();
        } else {
            this.state.summary = { total_retail: 0, total_discount: 0, total_final: 0 };
        }
    }

    clearBasket() {
        this.state.basket = [];
        this.state.summary = { total_retail: 0, total_discount: 0, total_final: 0 };
        this.state.error = null;
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
                for (let i = 0; i < result.lines.length; i++) {
                    const line = result.lines[i];
                    newBasket.push({
                        uid: this.uidCounter++,
                        barcode: line.barcode,
                        quantity: line.quantity,
                        name: line.name,
                        image_url: line.image_url,
                        retail_price: line.retail_price,
                        discount_amount: line.discount_amount,
                        final_price: line.final_price,
                        campaign_name: line.campaign_name
                    });
                }
                this.state.basket = newBasket;
                this.state.summary = result.summary;
                AudioFeedback.playSuccess();
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
