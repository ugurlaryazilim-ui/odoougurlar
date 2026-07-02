/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { BarcodeService } from "../barcode_service";

export class InventoryMatrix extends Component {
    static template = xml`
        <div class="ub-screen ub-matrix-screen">
            <!-- Header -->
            <div class="ub-header">
                <button class="ub-back-btn" t-on-click="() => this.props.navigate('main_menu')">
                    <i class="fa fa-angle-left"></i>
                </button>
                <h1 class="ub-title">Ürün Envanter Raporu</h1>
                <div class="ub-user">
                    <i class="fa fa-user-circle"></i>
                </div>
            </div>

            <!-- Arama Kutusu -->
            <div class="ub-matrix-search">
                <div class="ub-matrix-input-group">
                    <i class="fa fa-barcode"></i>
                    <input type="text"
                           class="form-control"
                           placeholder="Barkod okutun veya yazın..."
                           t-att-value="state.barcodeValue"
                           t-on-input="(ev) => this.state.barcodeValue = ev.target.value"
                           t-on-keydown="(ev) => ev.key === 'Enter' and this.searchBarcode()"/>
                    <button class="btn btn-sm btn-primary" t-on-click="searchBarcode" t-att-disabled="state.loading">
                        <i class="fa fa-search" t-if="!state.loading"></i>
                        <i class="fa fa-spinner fa-spin" t-if="state.loading"></i>
                    </button>
                </div>
                <div class="text-danger mt-2" t-if="state.error" t-esc="state.error"></div>
            </div>

            <t t-if="state.product">
                <!-- Ürün Kartı -->
                <div class="ub-matrix-product-card">
                    <div class="ub-mp-image">
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
        </div>
    `;

    static props = { navigate: Function };

    setup() {
        this.notification = useService("notification");
        
        this.state = useState({
            barcodeValue: '',
            loading: false,
            error: null,
            product: null,
            sizes: [],
            warehouses: [],
            grandTotals: {},
            grandTotalQty: 0
        });
    }

    async searchBarcode() {
        const val = this.state.barcodeValue.trim();
        if (!val) return;

        this.state.loading = true;
        this.state.error = null;
        this.state.product = null;
        
        try {
            const res = await BarcodeService.inventoryMatrix(val);
            
            if (res.error) {
                this.state.error = res.error;
            } else if (res.success) {
                this.state.product = res.product;
                this.processMatrixData(res.matrix_data || []);
            }
        } catch (error) {
            this.state.error = "Bağlantı hatası: " + error.message;
        } finally {
            this.state.loading = false;
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
