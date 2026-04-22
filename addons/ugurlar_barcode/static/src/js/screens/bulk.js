/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class BulkScreen extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-list-ol"></i> Toplu İşlem
                </h2>
            </div>

            <!-- İŞLEM TİPİ SEÇİMİ -->
            <div class="ub-filter-bar">
                <div class="ub-filter-row">
                    <div class="ub-filter-field" style="flex:1">
                        <label class="ub-field-label">İşlem Türü</label>
                        <select class="form-control ub-select" t-on-change="onOpChange" t-att-value="state.operation">
                            <option value="info">Stok Bilgisi</option>
                            <option value="putaway">Toplu Raflama</option>
                        </select>
                    </div>
                </div>
                <t t-if="state.operation === 'putaway'">
                    <div class="ub-filter-row">
                        <div class="ub-filter-field" style="flex:1">
                            <label class="ub-field-label">Hedef Raf Barkodu</label>
                            <input type="text" class="form-control ub-barcode-input"
                                   placeholder="Raf barkodu..."
                                   t-att-value="state.shelfBarcode"
                                   t-on-input="(ev) => this.state.shelfBarcode = ev.target.value"/>
                        </div>
                    </div>
                </t>
            </div>

            <!-- BARKOD GİRİŞ -->
            <div class="ub-scan-area">
                <p class="ub-step-label">Ürünleri tarayın (Enter ile ekleyin)</p>
                <div class="ub-input-group">
                    <input type="text"
                           class="form-control ub-barcode-input"
                           placeholder="Barkod..."
                           t-on-keydown="onKeyDown"
                           t-att-value="state.inputValue"
                           t-on-input="(ev) => this.state.inputValue = ev.target.value"/>
                    <button class="btn btn-primary ub-scan-btn" t-on-click="addItem">
                        <i class="fa fa-plus"></i>
                    </button>
                </div>
            </div>

            <!-- TARANAN ÜRÜNLER -->
            <t t-if="state.items.length">
                <div class="ub-count-list">
                    <h4 class="ub-section-title">
                        <i class="fa fa-barcode"></i>
                        Taranan Ürünler (<t t-esc="state.items.length"/>)
                    </h4>
                    <t t-foreach="state.items" t-as="item" t-key="item_index">
                        <div class="ub-count-row">
                            <div class="ub-count-info">
                                <div class="ub-count-bc" t-esc="item.barcode"/>
                            </div>
                            <div class="ub-qty-row" style="margin:0;">
                                <input type="number" class="ub-qty-input-sm" min="1"
                                       t-att-value="item.quantity"
                                       t-on-change="(ev) => this.updateQty(item_index, ev.target.value)"/>
                            </div>
                            <button class="btn btn-sm btn-outline-danger"
                                    t-on-click="() => this.removeItem(item_index)">
                                <i class="fa fa-times"></i>
                            </button>
                        </div>
                    </t>
                </div>

                <div class="ub-action-bar">
                    <button class="btn btn-primary w-100" t-on-click="executeBulk"
                            t-att-disabled="state.loading">
                        <i class="fa fa-bolt"></i> İşlemi Başlat
                    </button>
                </div>
            </t>

            <t t-if="state.loading">
                <div class="ub-loading">
                    <i class="fa fa-spinner fa-spin fa-2x"></i>
                    <p>İşleniyor...</p>
                </div>
            </t>

            <t t-if="state.error">
                <div class="ub-error-card">
                    <i class="fa fa-exclamation-triangle"></i>
                    <p t-esc="state.error"/>
                </div>
            </t>

            <!-- SONUÇLAR -->
            <t t-if="state.results">
                <div class="ub-success-card">
                    <i class="fa fa-check-circle"></i>
                    <p><t t-esc="state.results.success_count"/> / <t t-esc="state.results.total"/> işlem başarılı</p>
                </div>
                <div class="ub-count-results">
                    <t t-foreach="state.results.results" t-as="r" t-key="r_index">
                        <div class="ub-count-result-row">
                            <div>
                                <span t-esc="r.barcode"/>
                                <span t-if="r.product_name" class="text-muted ms-1">(<t t-esc="r.product_name"/>)</span>
                            </div>
                            <div>
                                <span t-if="r.status === 'found' || r.status === 'ok'" class="badge bg-success">
                                    <t t-if="r.total_stock !== undefined" t-esc="'Stok: ' + r.total_stock"/>
                                    <t t-if="r.message" t-esc="r.message"/>
                                </span>
                                <span t-if="r.status === 'not_found'" class="badge bg-danger">Bulunamadı</span>
                                <span t-if="r.status === 'error'" class="badge bg-warning" t-esc="r.message"/>
                            </div>
                        </div>
                    </t>
                </div>
            </t>
        </div>
    `;

    static props = { navigate: Function, scanner: Object };

    setup() {
        this.state = useState({
            inputValue: '',
            operation: 'info',
            shelfBarcode: '',
            items: [],
            loading: false,
            error: null,
            results: null,
        });
        this._unsubscribe = this.props.scanner.onScan(bc => {
            this.addItemByBarcode(bc);
        });
    }

    onOpChange(ev) { this.state.operation = ev.target.value; }

    onKeyDown(ev) {
        if (ev.key === 'Enter' && this.state.inputValue.trim()) {
            ev.preventDefault();
            this.addItem();
        }
    }

    addItem() {
        const bc = this.state.inputValue.trim();
        if (bc) {
            this.addItemByBarcode(bc);
            this.state.inputValue = '';
        }
    }

    addItemByBarcode(bc) {
        const existing = this.state.items.find(i => i.barcode === bc);
        if (existing) {
            existing.quantity += 1;
        } else {
            this.state.items.push({ barcode: bc, quantity: 1 });
        }
    }

    updateQty(index, val) {
        this.state.items[index].quantity = parseInt(val) || 1;
    }

    removeItem(index) {
        this.state.items.splice(index, 1);
    }

    async executeBulk() {
        if (this.state.operation === 'putaway' && !this.state.shelfBarcode.trim()) {
            this.state.error = 'Toplu raflama için raf barkodu gerekli';
            return;
        }

        this.state.loading = true;
        this.state.error = null;
        this.state.results = null;
        try {
            const result = await BarcodeService.bulkScan(
                this.state.items,
                this.state.operation,
                this.state.shelfBarcode.trim()
            );
            if (result.error) this.state.error = result.error;
            else this.state.results = result;
        } catch (e) {
            this.state.error = 'Hata: ' + (e.message || e);
        }
        this.state.loading = false;
    }

    willUnmount() { if (this._unsubscribe) this._unsubscribe(); }
}
