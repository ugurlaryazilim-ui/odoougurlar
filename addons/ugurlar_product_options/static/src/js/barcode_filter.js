/** @odoo-module */

import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, xml, useState, useRef, onMounted } from "@odoo/owl";

// ═══════════════════════════════════════════════════════
// Barkod Filtre Dialog — OWL Component
// ═══════════════════════════════════════════════════════

export class BarcodeFilterDialog extends Component {
    static template = xml`
        <div class="bf-overlay" t-on-click.stop="onOverlayClick">
            <div class="bf-dialog" t-on-click.stop="() => {}">
                <!-- Header -->
                <div class="bf-header">
                    <div class="bf-header-left">
                        <i class="fa fa-barcode bf-header-icon"/>
                        <span class="bf-header-title">Toplu Filtre</span>
                    </div>
                    <button class="bf-close-btn" t-on-click="onClose">
                        <i class="fa fa-times"/>
                    </button>
                </div>

                <!-- Field Selector -->
                <div class="bf-field-selector">
                    <button t-att-class="'bf-tab ' + (state.field === 'barcode' ? 'bf-tab-active' : '')"
                            t-on-click="() => this.selectField('barcode')">
                        <i class="fa fa-barcode"/> Barkod
                    </button>
                    <button t-att-class="'bf-tab ' + (state.field === 'default_code' ? 'bf-tab-active' : '')"
                            t-on-click="() => this.selectField('default_code')">
                        <i class="fa fa-tag"/> İç Referans
                    </button>
                </div>

                <!-- Textarea -->
                <div class="bf-body">
                    <textarea
                        t-ref="barcodeInput"
                        class="bf-textarea"
                        t-att-placeholder="state.field === 'barcode' ? 'Barkodları yapıştırın...\\nHer satıra bir barkod' : 'İç referansları yapıştırın...\\nHer satıra bir referans'"
                        t-on-input="onInput"
                        t-att-value="state.inputValue"
                        spellcheck="false"
                        autocomplete="off"
                    />
                    <div class="bf-counter" t-if="state.count > 0">
                        <span class="bf-count-badge">
                            <t t-out="state.count"/>
                        </span>
                        <span class="bf-count-label">
                            <t t-out="state.field === 'barcode' ? 'barkod' : 'referans'"/> girildi
                        </span>
                    </div>
                </div>

                <!-- Actions -->
                <div class="bf-actions">
                    <button class="bf-btn bf-btn-filter" t-on-click="onFilter"
                            t-att-disabled="state.count === 0">
                        <i class="fa fa-filter"/> Filtrele
                    </button>
                    <button class="bf-btn bf-btn-clear" t-on-click="onClear">
                        <i class="fa fa-eraser"/> Temizle
                    </button>
                </div>
            </div>
        </div>
    `;

    static props = {
        onFilter: Function,
        onClear: Function,
        onClose: Function,
        activeField: { type: String, optional: true },
    };

    setup() {
        this.inputRef = useRef("barcodeInput");
        this.state = useState({
            field: this.props.activeField || 'barcode',
            inputValue: '',
            count: 0,
        });

        onMounted(() => {
            // Otomatik focus
            if (this.inputRef.el) {
                this.inputRef.el.focus();
            }
        });
    }

    selectField(field) {
        this.state.field = field;
        this.state.inputValue = '';
        this.state.count = 0;
        if (this.inputRef.el) {
            this.inputRef.el.value = '';
            this.inputRef.el.focus();
        }
    }

    onInput(ev) {
        const value = ev.target.value;
        this.state.inputValue = value;
        const lines = value.split('\n').map(l => l.trim()).filter(l => l.length > 0);
        this.state.count = lines.length;
    }

    _getValues() {
        const value = this.inputRef.el ? this.inputRef.el.value : this.state.inputValue;
        return value.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    }

    onFilter() {
        const values = this._getValues();
        if (values.length > 0) {
            this.props.onFilter(this.state.field, values);
        }
    }

    onClear() {
        this.state.inputValue = '';
        this.state.count = 0;
        if (this.inputRef.el) {
            this.inputRef.el.value = '';
        }
        this.props.onClear();
    }

    onClose() {
        this.props.onClose();
    }

    onOverlayClick(ev) {
        if (ev.target.classList.contains('bf-overlay')) {
            this.onClose();
        }
    }
}


// ═══════════════════════════════════════════════════════
// Product List Controller — Barkod Filtre Butonu
// ═══════════════════════════════════════════════════════

export class ProductBarcodeListController extends ListController {
    static components = {
        ...ListController.components,
        BarcodeFilterDialog,
    };

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.dialogState = useState({
            show: false,
            activeField: 'barcode',
            filterActive: false,
            filterField: '',
            filterCount: 0,
        });
    }

    // ─── Dialog açma/kapama ───
    onOpenBarcodeFilter() {
        this.dialogState.show = true;
    }

    onCloseDialog() {
        this.dialogState.show = false;
    }

    // ─── Filtre uygula ───
    onApplyFilter(field, values) {
        this.dialogState.show = false;
        this.dialogState.filterActive = true;
        this.dialogState.filterField = field;
        this.dialogState.filterCount = values.length;

        // Ürün listesini filtrele
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            name: `Filtre: ${values.length} ${field === 'barcode' ? 'barkod' : 'referans'}`,
            views: [[false, "list"], [false, "form"]],
            domain: [[field, "in", values]],
            target: "current",
        });

        this.notification.add(
            `${values.length} ${field === 'barcode' ? 'barkod' : 'iç referans'} ile filtrelendi`,
            { type: "success" }
        );
    }

    // ─── Filtreyi temizle ───
    onClearFilter() {
        this.dialogState.show = false;
        this.dialogState.filterActive = false;
        this.dialogState.filterField = '';
        this.dialogState.filterCount = 0;

        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            name: "Ürün Varyantları",
            views: [[false, "list"], [false, "form"]],
            domain: [],
            target: "current",
        });
    }
}

ProductBarcodeListController.template = "ugurlar_product_options.ProductBarcodeListView";

// Custom view olarak kaydet
registry.category("views").add("product_barcode_list", {
    ...listView,
    Controller: ProductBarcodeListController,
});
