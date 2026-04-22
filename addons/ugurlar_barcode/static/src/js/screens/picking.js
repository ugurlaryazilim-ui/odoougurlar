/** @odoo-module **/

import { Component, useState, xml, onMounted } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class PickingScreen extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="goBack">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-shopping-cart"></i> Sipariş Toplama
                </h2>
            </div>

            <!-- Sipariş Listesi -->
            <t t-if="state.view === 'list'">
                <t t-if="state.loading">
                    <div class="ub-loading"><i class="fa fa-spinner fa-spin fa-2x"></i><p>Yükleniyor...</p></div>
                </t>
                <div class="ub-picking-list" t-if="state.pickings.length">
                    <t t-foreach="state.pickings" t-as="p" t-key="p.id">
                        <div class="ub-picking-row" t-on-click="() => this.selectPicking(p.id)">
                            <div class="ub-picking-info">
                                <div class="ub-picking-name" t-esc="p.name"/>
                                <div class="ub-picking-meta">
                                    <span t-if="p.partner" t-esc="p.partner"/>
                                    <span t-if="p.origin" class="badge bg-secondary" t-esc="p.origin"/>
                                </div>
                            </div>
                            <div class="ub-picking-count">
                                <span class="badge bg-primary" t-esc="p.move_count + ' ürün'"/>
                            </div>
                        </div>
                    </t>
                </div>
                <div class="ub-no-stock" t-if="!state.loading and !state.pickings.length">
                    <i class="fa fa-check-circle"></i>
                    <p>Bekleyen toplama yok</p>
                </div>
            </t>

            <!-- Sipariş Detay + Tarama -->
            <t t-if="state.view === 'detail'">
                <div class="ub-picking-detail-header">
                    <strong t-esc="state.picking.name"/>
                    <span t-if="state.picking.origin" t-esc="' — ' + state.picking.origin"/>
                </div>

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
                    <div t-attf-class="ub-scan-feedback {{state.scanOk ? 'ub-scan-ok' : 'ub-scan-fail'}}">
                        <i t-attf-class="fa {{state.scanOk ? 'fa-check' : 'fa-times'}}"></i>
                        <span t-esc="state.scanMsg"/>
                    </div>
                </t>

                <div class="ub-product-list" t-if="state.lines.length">
                    <t t-foreach="state.lines" t-as="line" t-key="line.id">
                        <div t-attf-class="ub-product-row {{line.done_qty >= line.demand_qty ? 'ub-line-done' : ''}}">
                            <div class="ub-prod-info">
                                <div class="ub-prod-name" t-esc="line.product_name"/>
                                <div class="ub-prod-barcode"><i class="fa fa-barcode"></i> <span t-esc="line.product_barcode"/></div>
                            </div>
                            <div class="ub-prod-qty-detail">
                                <span t-esc="line.done_qty"/> / <span t-esc="line.demand_qty"/>
                            </div>
                        </div>
                    </t>
                </div>

                <div class="ub-action-bar">
                    <button class="btn btn-success btn-lg w-100" t-on-click="onValidate"
                            t-att-disabled="state.loading">
                        <i class="fa fa-check"></i> Toplama Tamamla
                    </button>
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
            view: 'list', loading: false, error: null,
            pickings: [], picking: null, lines: [],
            scanInput: '', scanMsg: '', scanOk: false,
        });
        this._unsub = this.props.scanner.onScan(bc => {
            if (this.state.view === 'detail') {
                this.state.scanInput = bc;
                this.onScan();
            }
        });
        onMounted(() => this.loadList());
    }

    goBack() {
        if (this.state.view === 'detail') { this.state.view = 'list'; this.state.error = null; }
        else this.props.navigate('main');
    }

    async loadList() {
        this.state.loading = true;
        try {
            const res = await BarcodeService.pickingList();
            this.state.pickings = res.pickings || [];
        } catch (e) { this.state.error = 'Yükleme hatası'; }
        this.state.loading = false;
    }

    async selectPicking(id) {
        this.state.loading = true;
        try {
            const res = await BarcodeService.pickingDetail(id);
            if (res.error) { this.state.error = res.error; }
            else {
                this.state.picking = res.picking;
                this.state.lines = res.lines;
                this.state.view = 'detail';
            }
        } catch (e) { this.state.error = 'Detay hatası'; }
        this.state.loading = false;
    }

    onScanKey(ev) { if (ev.key === 'Enter') { ev.preventDefault(); this.onScan(); } }

    async onScan() {
        if (!this.state.scanInput.trim()) return;
        this.state.scanMsg = '';
        try {
            const res = await BarcodeService.pickingScan(this.state.picking.id, this.state.scanInput.trim(), 1);
            if (res.error) { this.state.scanMsg = res.error; this.state.scanOk = false; }
            else {
                this.state.scanMsg = res.product_name + ' → ' + res.done_qty + '/' + res.demand_qty;
                this.state.scanOk = true;
                // Satıtı güncelle
                for (const l of this.state.lines) {
                    if (l.product_id === undefined) continue;
                    const prod = await BarcodeService.pickingDetail(this.state.picking.id);
                    this.state.lines = prod.lines;
                    break;
                }
            }
        } catch (e) { this.state.scanMsg = 'Hata'; this.state.scanOk = false; }
        this.state.scanInput = '';
    }

    async onValidate() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const res = await BarcodeService.pickingValidate(this.state.picking.id);
            if (res.error) { this.state.error = res.error; }
            else {
                this.state.scanMsg = res.message;
                this.state.scanOk = true;
                setTimeout(() => { this.state.view = 'list'; this.loadList(); }, 1500);
            }
        } catch (e) { this.state.error = 'Doğrulama hatası'; }
        this.state.loading = false;
    }

    willUnmount() { if (this._unsub) this._unsub(); }
}
