/** @odoo-module **/

import { Component, useState, xml, onWillUnmount, onMounted, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { BarcodeService } from "../barcode_service";
import { vibrate, vibrateError, speak } from "../sound_utils";
import { openCameraScanner } from "../camera_scanner";

export class InventoryMatrix extends Component {
    static template = xml`
        <div class="ub-screen ub-matrix-screen">
            <!-- Header (Standard) -->
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-table"></i> Ürün Envanter Raporu
                </h2>
            </div>

            <!-- Arama Kutusu (Standard) -->
            <div class="ub-search-form">
                <div class="ub-search-field">
                    <label class="ub-field-label">Barkod</label>
                    <div class="ub-barcode-input-group">
                        <input type="text"
                               class="form-control ub-barcode-input"
                               placeholder="Barkod okutun veya yazın..."
                               t-on-keydown="(ev) => this.onKeyDown(ev, 'barcode')"
                               t-att-value="state.barcodeValue"
                               t-on-input="(ev) => this.onFieldInput(ev, 'barcode')"
                               t-ref="barcodeInput"/>
                        <button class="ub-scan-icon-btn" t-on-click="startCameraScan" title="Kamera ile tara">
                            <i class="fa fa-barcode"></i>
                        </button>
                    </div>
                </div>
                <button class="btn btn-primary ub-search-submit-btn" t-on-click="onSearch" t-att-disabled="state.loading">
                    <i class="fa fa-search" t-if="!state.loading"></i>
                    <i class="fa fa-spinner fa-spin" t-if="state.loading"></i>
                    Arama
                </button>
                <div class="text-danger mt-2" t-if="state.error" t-esc="state.error"></div>
            </div>

            <t t-if="state.product">
                <!-- Ürün Kartı -->
                <div class="ub-matrix-product-card">
                    <div class="ub-mp-image" t-on-click="() => this.state.lightboxImage = state.product.image_url.replace('image_128', 'image_1920')">
                        <img t-att-src="state.product.image_url" alt="Ürün"/>
                    </div>
                    <div class="ub-mp-details">
                        <div class="ub-mp-name" t-esc="state.product.name"></div>
                        <div class="ub-mp-code" t-esc="state.product.code"></div>
                    </div>
                </div>

                <!-- Matris Tablosu -->
                <div class="ub-matrix-wrapper" t-if="state.sizes.length > 0">
                    <table class="ub-matrix-table">
                        <thead>
                            <tr>
                                <th class="ub-matrix-th-group" rowspan="2">Depo / Renk</th>
                                <th t-att-colspan="state.sizes.length">Bedenler</th>
                                <th rowspan="2">Toplam</th>
                            </tr>
                            <tr>
                                <t t-foreach="state.sizes" t-as="size" t-key="size">
                                    <th t-esc="size"></th>
                                </t>
                            </tr>
                        </thead>
                        <tbody>
                            <t t-foreach="state.warehouses" t-as="wh" t-key="wh.code">
                                <!-- Depo Toplam Satırı (Koyu) -->
                                <tr class="bg-light">
                                    <td class="ub-matrix-row-title font-weight-bold" t-esc="wh.name"></td>
                                    <t t-foreach="state.sizes" t-as="size" t-key="size">
                                        <td class="ub-matrix-qty font-weight-bold" 
                                            t-esc="wh.totals[size] || ''"></td>
                                    </t>
                                    <td class="ub-matrix-total" t-esc="wh.totalQty"></td>
                                </tr>
                                
                                <!-- Depo İçindeki Renk Satırları -->
                                <t t-foreach="wh.colors" t-as="color" t-key="color.name">
                                    <tr>
                                        <td class="ub-matrix-row-title ub-matrix-row-indent" t-esc="color.name"></td>
                                        <t t-foreach="state.sizes" t-as="size" t-key="size">
                                            <t t-set="qty" t-value="color.sizes[size]"/>
                                            <td t-attf-class="ub-matrix-qty {{qty ? '' : 'ub-matrix-qty-zero'}}" 
                                                t-esc="qty || '-'"></td>
                                        </t>
                                        <td class="font-weight-bold" t-esc="color.totalQty"></td>
                                    </tr>
                                </t>
                            </t>
                        </tbody>
                        <!-- Genel Toplam -->
                        <tfoot>
                            <tr>
                                <td class="ub-matrix-row-title ub-matrix-total">GENEL TOPLAM</td>
                                <t t-foreach="state.sizes" t-as="size" t-key="size">
                                    <td class="ub-matrix-total" t-esc="state.grandTotals[size] || '0'"></td>
                                </t>
                                <td class="ub-matrix-total font-weight-bold" t-esc="state.grandTotalQty"></td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
                
                <div class="ub-empty-state" t-else="">
                    <i class="fa fa-info-circle fa-3x mb-3 text-info"></i>
                    <h4>Stok Bulunamadı</h4>
                    <p>Bu ürüne ait hiçbir depoda stok hareketi bulunmamaktadır.</p>
                </div>
            </t>
            
            <div class="ub-empty-state" t-elif="!state.loading and !state.error">
                <i class="fa fa-table fa-3x mb-3 text-muted"></i>
                <h4>Matris Raporu</h4>
                <p>Renk ve beden kırılımlı stok tablosunu görmek için bir barkod okutun.</p>
            </div>

            <!-- Lightbox Overlay -->
            <div t-if="state.lightboxImage" class="ub-lightbox" t-on-click="() => this.state.lightboxImage = null">
                <button class="ub-lightbox-close"><i class="fa fa-times"></i></button>
                <img t-att-src="state.lightboxImage" />
            </div>
        </div>
    `;

    static props = { navigate: Function, scanner: Object };

    setup() {
        this.notification = useService("notification");
        this.barcodeInputRef = useRef('barcodeInput');
        
        this.state = useState({
            barcodeValue: '',
            loading: false,
            error: null,
            product: null,
            lightboxImage: null,
            sizes: [],
            warehouses: [],
            grandTotals: {},
            grandTotalQty: 0
        });

        this._unsubscribe = this.props.scanner.onScan(barcode => {
            this.state.barcodeValue = barcode;
            this.doSearch(barcode);
        });

        onMounted(() => {
            if (this.barcodeInputRef.el) this.barcodeInputRef.el.focus();
        });

        onWillUnmount(() => {
            if (this._unsubscribe) this._unsubscribe();
            if (this._scanTimer) clearTimeout(this._scanTimer);
        });
    }

    onFieldInput(ev, field) {
        const val = ev.target.value;
        if (field === 'barcode') {
            this.state.barcodeValue = val;
            this._detectBarcodeScan(val);
        }
    }

    _detectBarcodeScan(val) {
        const now = Date.now();
        if (this._lastInputTime && (now - this._lastInputTime) < 80) {
            this._rapidCount = (this._rapidCount || 0) + 1;
        } else {
            this._rapidCount = 0;
        }
        this._lastInputTime = now;

        if (this._scanTimer) clearTimeout(this._scanTimer);

        if (this._rapidCount >= 6 && val.trim().length >= 8) {
            this._scanTimer = setTimeout(() => {
                if (this.state.barcodeValue.trim().length >= 8) {
                    this.doSearch(this.state.barcodeValue.trim());
                }
            }, 300);
        }
    }

    onKeyDown(ev, searchType) {
        if (ev.key === 'Enter') {
            ev.preventDefault();
            const value = ev.target.value.trim();
            if (value) {
                this.doSearch(value);
            }
        }
    }

    onSearch() {
        if (this.state.barcodeValue.trim()) {
            this.doSearch(this.state.barcodeValue.trim());
        }
    }

    async startCameraScan() {
        openCameraScanner((barcode) => {
            this.state.barcodeValue = barcode;
            this.doSearch(barcode);
        });
    }

    async doSearch(barcode) {
        this.state.loading = true;
        this.state.error = null;
        this.state.product = null;
        
        try {
            const res = await BarcodeService.inventoryMatrix(barcode);
            
            if (res.error) {
                this.state.error = res.error;
                vibrateError();
                speak('stock_search_not_found'); // Resuming existing TTS
            } else if (res.success) {
                this.state.product = res.product;
                this.processMatrixData(res.matrix_data || []);
                vibrate();
                speak('stock_search_success');
            }
        } catch (error) {
            this.state.error = "Bağlantı hatası: " + (error.message || error);
            vibrateError();
            speak('stock_search_error');
        } finally {
            this.state.loading = false;
            this.state.barcodeValue = ''; // Clear for next scan
            if (this.barcodeInputRef.el) { this.barcodeInputRef.el.focus(); }
        }
    }

    processMatrixData(data) {
        // 1. Find all unique sizes and sort them
        const sizeSet = new Set();
        data.forEach(row => {
            if (row.size_name) sizeSet.add(row.size_name);
        });
        
        // Custom size sorting (S, M, L, XL etc. or numbers)
        const sizeOrder = {'XXS':1, 'XS':2, 'S':3, 'M':4, 'L':5, 'XL':6, 'XXL':7, '2XL':7, '3XL':8, '4XL':9, '5XL':10};
        this.state.sizes = Array.from(sizeSet).sort((a, b) => {
            const aNum = parseFloat(a);
            const bNum = parseFloat(b);
            if (!isNaN(aNum) && !isNaN(bNum)) return aNum - bNum;
            const aW = sizeOrder[a.toUpperCase()] || 99;
            const bW = sizeOrder[b.toUpperCase()] || 99;
            if (aW !== bW) return aW - bW;
            return a.localeCompare(b);
        });

        // 2. Group by Warehouse -> Color
        const whMap = new Map();
        const grandTotals = {};
        let grandTotalQty = 0;
        
        data.forEach(row => {
            const whCode = row.warehouse_code;
            const whName = row.warehouse_name;
            const colorName = row.color_name || 'Bilinmeyen Renk';
            const size = row.size_name;
            const qty = row.qty;
            
            if (!whMap.has(whCode)) {
                whMap.set(whCode, {
                    code: whCode,
                    name: whName,
                    colors: new Map(),
                    totals: {},
                    totalQty: 0
                });
            }
            
            const wh = whMap.get(whCode);
            if (!wh.colors.has(colorName)) {
                wh.colors.set(colorName, {
                    name: colorName,
                    sizes: {},
                    totalQty: 0
                });
            }
            
            const color = wh.colors.get(colorName);
            
            // Add Qty
            color.sizes[size] = (color.sizes[size] || 0) + qty;
            color.totalQty += qty;
            
            wh.totals[size] = (wh.totals[size] || 0) + qty;
            wh.totalQty += qty;
            
            grandTotals[size] = (grandTotals[size] || 0) + qty;
            grandTotalQty += qty;
        });
        
        // 3. Convert Maps to Arrays for template rendering
        const warehouses = [];
        for (const wh of whMap.values()) {
            const colorList = [];
            for (const color of wh.colors.values()) {
                colorList.push(color);
            }
            // Sort colors alphabetically
            colorList.sort((a, b) => a.name.localeCompare(b.name));
            wh.colors = colorList;
            warehouses.push(wh);
        }
        
        // Sort warehouses alphabetically
        warehouses.sort((a, b) => a.name.localeCompare(b.name));
        
        this.state.warehouses = warehouses;
        this.state.grandTotals = grandTotals;
        this.state.grandTotalQty = grandTotalQty;
    }
}
