/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Ürün Varyantları — Sütun Bazlı Barkod/Referans Filtre
 *
 * ListRenderer'ı PATCH ederek filtre ikonu ve dropdown mantığını ekler.
 * Template extension ile sort ikonunun yanına filtre ikonu eklenir.
 * t-if sayesinde sadece barcode ve default_code sütunlarında görünür.
 */

const FILTERABLE_FIELDS = ['barcode', 'default_code'];

patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this.bfActionService = useService("action");
        this.bfNotification = useService("notification");
        this._bfActiveDropdown = null;
        this._bfFilterTexts = {};
        this._bfFilterValues = {};
        this._onBfDocClickBound = this._onBfDocClick.bind(this);
    },

    /**
     * Template'den çağrılır — bu sütun filtrelenebilir mi?
     */
    isBfFilterable(columnName) {
        return FILTERABLE_FIELDS.includes(columnName);
    },

    /**
     * Template'deki filtre ikonuna tıklayınca
     */
    onBfFilterClick(ev) {
        ev.stopPropagation();
        ev.preventDefault();
        const fieldName = ev.target.dataset.bfField;
        const th = ev.target.closest('th');
        if (fieldName && th) {
            this._bfToggleDropdown(fieldName, th);
        }
    },

    // ═══════════════════════════════════════════════════
    // Dropdown
    // ═══════════════════════════════════════════════════

    _bfToggleDropdown(fieldName, thElement) {
        if (this._bfActiveDropdown === fieldName) {
            this._bfCloseDropdown();
            return;
        }
        this._bfCloseDropdown();
        this._bfActiveDropdown = fieldName;

        const dropdown = document.createElement('div');
        dropdown.className = 'bf-dropdown';

        const label = fieldName === 'barcode' ? 'Barkod' : 'İç Referans';
        const savedText = this._bfFilterTexts[fieldName] || '';
        const hasFilter = this._bfFilterValues[fieldName]?.length > 0;
        const count = this._bfFilterValues[fieldName]?.length || 0;

        dropdown.innerHTML = `
            <div class="bf-dd-header">
                <span class="bf-dd-label"><i class="fa fa-filter"></i> ${label} Filtre</span>
                ${hasFilter ? `<span class="bf-dd-badge">${count}</span>` : ''}
            </div>
            <textarea class="bf-dd-input"
                      placeholder="Yapıştırın...\nHer satıra bir ${label.toLowerCase()}"
                      rows="6" spellcheck="false" autocomplete="off">${savedText}</textarea>
            <div class="bf-dd-actions">
                <button class="bf-dd-btn bf-dd-filter">
                    <i class="fa fa-filter"></i> Filtrele
                </button>
                <button class="bf-dd-btn bf-dd-clear" ${!hasFilter ? 'style="display:none"' : ''}>
                    <i class="fa fa-eraser"></i> Temizle
                </button>
            </div>
        `;

        const thRect = thElement.getBoundingClientRect();
        dropdown.style.position = 'fixed';
        dropdown.style.top = `${thRect.bottom + 2}px`;
        dropdown.style.left = `${Math.max(thRect.left, 8)}px`;
        dropdown.style.zIndex = '99999';

        document.body.appendChild(dropdown);

        const textarea = dropdown.querySelector('.bf-dd-input');
        textarea.focus();
        textarea.selectionStart = textarea.selectionEnd = textarea.value.length;

        // Paste → otomatik filtrele
        textarea.addEventListener('paste', () => {
            setTimeout(() => this._bfApplyFilter(fieldName, textarea), 100);
        });

        // Enter → filtrele
        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._bfApplyFilter(fieldName, textarea);
            }
            if (e.key === 'Escape') {
                this._bfCloseDropdown();
            }
        });

        dropdown.querySelector('.bf-dd-filter').addEventListener('click', () => {
            this._bfApplyFilter(fieldName, textarea);
        });
        dropdown.querySelector('.bf-dd-clear').addEventListener('click', () => {
            this._bfClearFilter(fieldName);
        });

        setTimeout(() => {
            document.addEventListener('click', this._onBfDocClickBound);
        }, 50);
    },

    _onBfDocClick(e) {
        const dropdown = document.querySelector('.bf-dropdown');
        if (dropdown && !dropdown.contains(e.target) && !e.target.closest('.bf-icon')) {
            this._bfCloseDropdown();
        }
    },

    _bfCloseDropdown() {
        const dropdown = document.querySelector('.bf-dropdown');
        if (dropdown && this._bfActiveDropdown) {
            const textarea = dropdown.querySelector('.bf-dd-input');
            if (textarea) {
                this._bfFilterTexts[this._bfActiveDropdown] = textarea.value;
            }
        }
        this._bfActiveDropdown = null;
        document.querySelectorAll('.bf-dropdown').forEach(el => el.remove());
        document.removeEventListener('click', this._onBfDocClickBound);
    },

    // ═══════════════════════════════════════════════════
    // Filtreleme
    // ═══════════════════════════════════════════════════

    _bfApplyFilter(fieldName, textarea) {
        const text = textarea.value;
        const values = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
        if (values.length === 0) return;

        this._bfFilterTexts[fieldName] = text;
        this._bfFilterValues[fieldName] = values;
        this._bfCloseDropdown();
        this._bfExecuteFilter();
    },

    _bfClearFilter(fieldName) {
        delete this._bfFilterTexts[fieldName];
        delete this._bfFilterValues[fieldName];
        this._bfCloseDropdown();
        this._bfExecuteFilter();
    },

    _bfExecuteFilter() {
        const domain = [];
        for (const [field, values] of Object.entries(this._bfFilterValues)) {
            if (values && values.length > 0) {
                domain.push([field, "in", values]);
            }
        }

        const hasFilter = domain.length > 0;
        const label = hasFilter
            ? `Filtre: ${Object.entries(this._bfFilterValues).map(([f, v]) => `${v.length} ${f === 'barcode' ? 'barkod' : 'referans'}`).join(' + ')}`
            : 'Ürün Varyantları';

        this.bfActionService.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            name: label,
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });

        if (hasFilter) {
            const total = Object.values(this._bfFilterValues).reduce((s, v) => s + v.length, 0);
            this.bfNotification.add(`${total} kayıt ile filtrelendi`, { type: "success" });
        }
    },
});

// js_class="product_barcode_list" için view kaydı (basit pass-through)
registry.category("views").add("product_barcode_list", listView);
