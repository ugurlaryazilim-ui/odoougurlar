/** @odoo-module */

import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onPatched, useState } from "@odoo/owl";

/**
 * Ürün Varyantları — Sütun Bazlı Barkod/Referans Filtre
 *
 * Sort ikonunun yanına filtre ikonu ekler (aynı hover davranışı).
 * Tıklayınca küçük dropdown açılır. Yapıştır → filtrele.
 * Textarea içeriği korunur. Temizle butonu filtre + içeriği sıfırlar.
 */

const FILTERABLE_FIELDS = ['barcode', 'default_code'];

export class ProductBarcodeListController extends ListController {
    setup() {
        super.setup();
        this.actionService = useService("action");
        this.notification = useService("notification");

        // Filtre state — alan bazlı textarea içeriklerini sakla
        this._filterTexts = {};    // { barcode: "123\n456", default_code: "X-1" }
        this._filterValues = {};   // { barcode: ['123','456'] }
        this._activeDropdown = null;
        this._onDocClickBound = this._onDocClick.bind(this);

        onMounted(() => this._injectFilterIcons());
        onPatched(() => this._injectFilterIcons());
    }

    // ═══════════════════════════════════════════════════
    // DOM Enjeksiyonu — Sort ikonunun yanına filtre ikonu
    // ═══════════════════════════════════════════════════

    _injectFilterIcons() {
        const el = this.rootRef?.el || document.querySelector('.o_list_view');
        if (!el) return;

        const headers = el.querySelectorAll('thead th[data-name]');

        headers.forEach(th => {
            const fieldName = th.dataset.name;
            if (!FILTERABLE_FIELDS.includes(fieldName)) return;
            if (th.querySelector('.bf-icon')) return;

            // Sort ikonunu bul
            const sortIcon = th.querySelector('.o_list_sortable_icon');

            // Filtre ikonu oluştur — sort ikonuyla aynı class yapısı
            const icon = document.createElement('i');
            icon.className = 'bf-icon fa fa-filter opacity-0 opacity-100-hover';
            icon.title = fieldName === 'barcode' ? 'Barkod Filtre' : 'İç Referans Filtre';

            // Aktif filtre varsa her zaman görünür yap
            if (this._filterValues[fieldName]?.length > 0) {
                icon.classList.remove('opacity-0', 'opacity-100-hover');
                icon.classList.add('bf-icon-active');
            }

            icon.addEventListener('click', (e) => {
                e.stopPropagation();
                e.preventDefault();
                this._toggleDropdown(fieldName, th);
            });

            // Sort ikonunun yanına ekle
            if (sortIcon) {
                sortIcon.parentNode.insertBefore(icon, sortIcon.nextSibling);
            } else {
                th.appendChild(icon);
            }

            // th hover'da filtre ikonunu da göster (sort ile aynı)
            th.addEventListener('mouseenter', () => {
                if (!icon.classList.contains('bf-icon-active')) {
                    icon.classList.remove('opacity-0');
                }
            });
            th.addEventListener('mouseleave', () => {
                if (!icon.classList.contains('bf-icon-active') && this._activeDropdown !== fieldName) {
                    icon.classList.add('opacity-0');
                }
            });
        });
    }

    // ═══════════════════════════════════════════════════
    // Dropdown
    // ═══════════════════════════════════════════════════

    _toggleDropdown(fieldName, thElement) {
        if (this._activeDropdown === fieldName) {
            this._closeDropdown();
            return;
        }
        this._closeDropdown();
        this._activeDropdown = fieldName;

        const dropdown = document.createElement('div');
        dropdown.className = 'bf-dropdown';
        dropdown.id = `bf-dropdown-${fieldName}`;

        const label = fieldName === 'barcode' ? 'Barkod' : 'İç Referans';
        const savedText = this._filterTexts[fieldName] || '';
        const hasFilter = this._filterValues[fieldName]?.length > 0;
        const count = this._filterValues[fieldName]?.length || 0;

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

        // Pozisyonla
        const thRect = thElement.getBoundingClientRect();
        dropdown.style.position = 'fixed';
        dropdown.style.top = `${thRect.bottom + 2}px`;
        dropdown.style.left = `${Math.max(thRect.left, 8)}px`;
        dropdown.style.zIndex = '99999';

        document.body.appendChild(dropdown);

        const textarea = dropdown.querySelector('.bf-dd-input');
        textarea.focus();

        // Kursor sona
        textarea.selectionStart = textarea.selectionEnd = textarea.value.length;

        // Paste → otomatik filtrele
        textarea.addEventListener('paste', () => {
            setTimeout(() => {
                this._applyFilter(fieldName, textarea);
            }, 100);
        });

        // Enter → filtrele (Shift+Enter yeni satır)
        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._applyFilter(fieldName, textarea);
            }
            if (e.key === 'Escape') {
                this._closeDropdown();
            }
        });

        // Filtrele butonu
        dropdown.querySelector('.bf-dd-filter').addEventListener('click', () => {
            this._applyFilter(fieldName, textarea);
        });

        // Temizle butonu
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
        // Kapanmadan önce textarea içeriğini kaydet
        const dropdown = document.querySelector('.bf-dropdown');
        if (dropdown && this._activeDropdown) {
            const textarea = dropdown.querySelector('.bf-dd-input');
            if (textarea) {
                this._filterTexts[this._activeDropdown] = textarea.value;
            }
        }

        this._activeDropdown = null;
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

        // State kaydet — textarea içeriği korunsun
        this._filterTexts[fieldName] = text;
        this._filterValues[fieldName] = values;

        this._closeDropdown();
        this._executeFilter();
    }

    _clearFilter(fieldName) {
        delete this._filterTexts[fieldName];
        delete this._filterValues[fieldName];

        this._closeDropdown();
        this._executeFilter();
    }

    _executeFilter() {
        const domain = [];
        for (const [field, values] of Object.entries(this._filterValues)) {
            if (values && values.length > 0) {
                domain.push([field, "in", values]);
            }
        }

        const hasFilter = domain.length > 0;
        const label = hasFilter
            ? `Filtre: ${Object.entries(this._filterValues).map(([f, v]) => `${v.length} ${f === 'barcode' ? 'barkod' : 'referans'}`).join(' + ')}`
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
            const total = Object.values(this._filterValues).reduce((s, v) => s + v.length, 0);
            this.notification.add(`${total} kayıt ile filtrelendi`, { type: "success" });
        }
    }
}

ProductBarcodeListController.template = "ugurlar_product_options.ProductBarcodeListView";

registry.category("views").add("product_barcode_list", {
    ...listView,
    Controller: ProductBarcodeListController,
});
