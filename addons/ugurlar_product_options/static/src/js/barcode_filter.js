/** @odoo-module */

import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Ürün Varyantları — Sütun Bazlı Barkod/Referans Filtre
 *
 * ListRenderer template inheritance ile filtre ikonunu
 * sort ikonunun yanına ekler. DOM enjeksiyonu yerine
 * Odoo'nun OWL render ağacına dahil olur.
 */

const FILTERABLE_FIELDS = ['barcode', 'default_code'];

export class ProductFilterListRenderer extends ListRenderer {
    static template = "ugurlar_product_options.ProductFilterListRenderer";

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.notification = useService("notification");
        this._bfActiveDropdown = null;
        this._bfFilterTexts = {};
        this._bfFilterValues = {};
        this._onDocClickBound = this._onDocClick.bind(this);
    }

    /**
     * Template'den çağrılır — bu sütun filtrelenebilir mi?
     */
    isBfFilterable(columnName) {
        return FILTERABLE_FIELDS.includes(columnName);
    }

    /**
     * Template'deki filtre ikonuna tıklayınca
     */
    onBfFilterClick(ev) {
        ev.stopPropagation();
        ev.preventDefault();
        const fieldName = ev.target.dataset.bfField;
        const th = ev.target.closest('th');
        if (fieldName && th) {
            this._toggleDropdown(fieldName, th);
        }
    }

    // ═══════════════════════════════════════════════════
    // Dropdown
    // ═══════════════════════════════════════════════════

    _toggleDropdown(fieldName, thElement) {
        if (this._bfActiveDropdown === fieldName) {
            this._closeDropdown();
            return;
        }
        this._closeDropdown();
        this._bfActiveDropdown = fieldName;

        const dropdown = document.createElement('div');
        dropdown.className = 'bf-dropdown';
        dropdown.id = `bf-dropdown-${fieldName}`;

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

        // Pozisyonla — th altında
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
            setTimeout(() => this._applyFilter(fieldName, textarea), 100);
        });

        // Enter → filtrele
        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._applyFilter(fieldName, textarea);
            }
            if (e.key === 'Escape') {
                this._closeDropdown();
            }
        });

        // Butonlar
        dropdown.querySelector('.bf-dd-filter').addEventListener('click', () => {
            this._applyFilter(fieldName, textarea);
        });
        dropdown.querySelector('.bf-dd-clear').addEventListener('click', () => {
            this._clearFilter(fieldName);
        });

        // Dışarı tıkla → kapat
        setTimeout(() => {
            document.addEventListener('click', this._onDocClickBound);
        }, 50);
    }

    _onDocClick(e) {
        const dropdown = document.querySelector('.bf-dropdown');
        if (dropdown && !dropdown.contains(e.target) && !e.target.closest('.bf-icon')) {
            this._closeDropdown();
        }
    }

    _closeDropdown() {
        const dropdown = document.querySelector('.bf-dropdown');
        if (dropdown && this._bfActiveDropdown) {
            const textarea = dropdown.querySelector('.bf-dd-input');
            if (textarea) {
                this._bfFilterTexts[this._bfActiveDropdown] = textarea.value;
            }
        }
        this._bfActiveDropdown = null;
        document.querySelectorAll('.bf-dropdown').forEach(el => el.remove());
        document.removeEventListener('click', this._onDocClickBound);
    }

    // ═══════════════════════════════════════════════════
    // Filtreleme
    // ═══════════════════════════════════════════════════

    _applyFilter(fieldName, textarea) {
        const text = textarea.value;
        const values = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
        if (values.length === 0) return;

        this._bfFilterTexts[fieldName] = text;
        this._bfFilterValues[fieldName] = values;
        this._closeDropdown();
        this._executeFilter();
    }

    _clearFilter(fieldName) {
        delete this._bfFilterTexts[fieldName];
        delete this._bfFilterValues[fieldName];
        this._closeDropdown();
        this._executeFilter();
    }

    _executeFilter() {
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

        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            name: label,
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });

        if (hasFilter) {
            const total = Object.values(this._bfFilterValues).reduce((s, v) => s + v.length, 0);
            this.notification.add(`${total} kayıt ile filtrelendi`, { type: "success" });
        }
    }
}

registry.category("views").add("product_barcode_list", {
    ...listView,
    Renderer: ProductFilterListRenderer,
});
