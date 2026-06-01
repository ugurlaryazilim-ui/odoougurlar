/** @odoo-module */

import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onPatched, useState } from "@odoo/owl";

/**
 * Ürün Varyantları — Sütun Bazlı Barkod/Referans Filtre
 *
 * Barkod ve İç Referans sütun başlıklarına küçük filtre ikonu ekler.
 * Tıklanınca sütunun altında küçük yapıştırma alanı açılır.
 * Yapıştırma/Enter ile otomatik filtreler.
 */

// Filtre eklenecek sütunlar
const FILTERABLE_FIELDS = ['barcode', 'default_code'];

export class ProductBarcodeListController extends ListController {
    setup() {
        super.setup();
        this.actionService = useService("action");
        this.notification = useService("notification");

        this.filterState = useState({
            activeField: null,     // Şu an açık dropdown'ın alanı
            filters: {},           // { barcode: ['123','456'], default_code: ['X-1'] }
        });

        // DOM'a filtre ikonlarını enjekte et
        onMounted(() => this._injectFilterIcons());
        onPatched(() => this._injectFilterIcons());
    }

    // ═══════════════════════════════════════════════════
    // DOM Enjeksiyonu — Sütun başlıklarına filtre ikonu
    // ═══════════════════════════════════════════════════

    _injectFilterIcons() {
        const el = this.rootRef?.el || document.querySelector('.o_list_view');
        if (!el) return;

        // Tüm th header'larını bul
        const headers = el.querySelectorAll('thead th[data-name]');

        headers.forEach(th => {
            const fieldName = th.dataset.name;
            if (!FILTERABLE_FIELDS.includes(fieldName)) return;

            // Zaten ikon varsa ekleme
            if (th.querySelector('.bf-icon')) return;

            // Filtre ikonu oluştur
            const icon = document.createElement('span');
            icon.className = 'bf-icon';
            icon.title = fieldName === 'barcode' ? 'Barkod Filtre' : 'İç Referans Filtre';
            icon.innerHTML = '<i class="fa fa-filter"></i>';

            // Aktif filtre varsa rengi değiştir
            if (this.filterState.filters[fieldName]?.length > 0) {
                icon.classList.add('bf-icon-active');
                icon.title += ` (${this.filterState.filters[fieldName].length} filtre)`;
            }

            // Tıklama olayı
            icon.addEventListener('click', (e) => {
                e.stopPropagation(); // Sort tetiklemesin
                this._toggleDropdown(fieldName, th);
            });

            // Sütun başlığının içine ekle (sort ikonunun yanına)
            const headerContent = th.querySelector('.o_column_sortable') || th;
            headerContent.style.position = 'relative';
            headerContent.appendChild(icon);
        });
    }

    // ═══════════════════════════════════════════════════
    // Dropdown — Yapıştırma alanı
    // ═══════════════════════════════════════════════════

    _toggleDropdown(fieldName, thElement) {
        // Aynı alan açıksa kapat
        if (this.filterState.activeField === fieldName) {
            this._closeDropdown();
            return;
        }

        // Önce açık olanı kapat
        this._closeDropdown();

        this.filterState.activeField = fieldName;

        // Dropdown oluştur
        const dropdown = document.createElement('div');
        dropdown.className = 'bf-dropdown';
        dropdown.id = `bf-dropdown-${fieldName}`;

        const label = fieldName === 'barcode' ? 'Barkod' : 'İç Referans';
        const activeFilter = this.filterState.filters[fieldName];
        const hasFilter = activeFilter && activeFilter.length > 0;

        dropdown.innerHTML = `
            <div class="bf-dd-header">
                <span class="bf-dd-label"><i class="fa fa-filter"></i> ${label} Filtre</span>
                ${hasFilter ? `<span class="bf-dd-badge">${activeFilter.length}</span>` : ''}
            </div>
            <textarea class="bf-dd-input" 
                      placeholder="Yapıştırın...\nHer satıra bir ${label.toLowerCase()}"
                      rows="5" spellcheck="false" autocomplete="off">${hasFilter ? activeFilter.join('\n') : ''}</textarea>
            <div class="bf-dd-actions">
                <button class="bf-dd-btn bf-dd-filter" ${!hasFilter ? '' : ''}>
                    <i class="fa fa-filter"></i> Filtrele
                </button>
                <button class="bf-dd-btn bf-dd-clear" ${!hasFilter ? 'style="display:none"' : ''}>
                    <i class="fa fa-times"></i>
                </button>
            </div>
        `;

        // Dropdown'ı pozisyonla — sütun başlığının altına
        const thRect = thElement.getBoundingClientRect();
        const listView = document.querySelector('.o_list_view') || document.body;
        const listRect = listView.getBoundingClientRect();

        dropdown.style.position = 'fixed';
        dropdown.style.top = `${thRect.bottom + 4}px`;
        dropdown.style.left = `${Math.max(thRect.left, 8)}px`;
        dropdown.style.zIndex = '99999';

        document.body.appendChild(dropdown);

        // Textarea'ya focus
        const textarea = dropdown.querySelector('.bf-dd-input');
        textarea.focus();
        if (hasFilter) {
            textarea.select();
        }

        // Paste event — yapıştırınca otomatik filtrele
        textarea.addEventListener('paste', () => {
            setTimeout(() => {
                this._applyFilterFromTextarea(fieldName, textarea);
            }, 100);
        });

        // Enter ile filtrele (Shift+Enter yeni satır)
        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._applyFilterFromTextarea(fieldName, textarea);
            }
            if (e.key === 'Escape') {
                this._closeDropdown();
            }
        });

        // Filtrele butonu
        dropdown.querySelector('.bf-dd-filter').addEventListener('click', () => {
            this._applyFilterFromTextarea(fieldName, textarea);
        });

        // Temizle butonu
        dropdown.querySelector('.bf-dd-clear').addEventListener('click', () => {
            this._clearFieldFilter(fieldName);
        });

        // Dışarı tıklayınca kapat
        setTimeout(() => {
            document.addEventListener('click', this._onDocClick = (e) => {
                if (!dropdown.contains(e.target) && !e.target.closest('.bf-icon')) {
                    this._closeDropdown();
                }
            });
        }, 50);
    }

    _closeDropdown() {
        this.filterState.activeField = null;
        const existing = document.querySelectorAll('.bf-dropdown');
        existing.forEach(el => el.remove());
        if (this._onDocClick) {
            document.removeEventListener('click', this._onDocClick);
            this._onDocClick = null;
        }
    }

    // ═══════════════════════════════════════════════════
    // Filtreleme
    // ═══════════════════════════════════════════════════

    _applyFilterFromTextarea(fieldName, textarea) {
        const value = textarea.value;
        const values = value.split('\n').map(l => l.trim()).filter(l => l.length > 0);

        if (values.length === 0) return;

        // Filtre state güncelle
        this.filterState.filters[fieldName] = values;
        this._closeDropdown();

        // Domain oluştur — tüm aktif filtreleri birleştir
        const domain = this._buildDomain();
        const label = fieldName === 'barcode' ? 'barkod' : 'iç referans';

        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            name: `Filtre: ${values.length} ${label}`,
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });

        this.notification.add(
            `${values.length} ${label} ile filtrelendi`,
            { type: "success" }
        );
    }

    _clearFieldFilter(fieldName) {
        delete this.filterState.filters[fieldName];
        this._closeDropdown();

        const domain = this._buildDomain();

        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            name: "Ürün Varyantları",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    _buildDomain() {
        const domain = [];
        for (const [field, values] of Object.entries(this.filterState.filters)) {
            if (values && values.length > 0) {
                domain.push([field, "in", values]);
            }
        }
        return domain;
    }
}

ProductBarcodeListController.template = "ugurlar_product_options.ProductBarcodeListView";

// Custom view olarak kaydet
registry.category("views").add("product_barcode_list", {
    ...listView,
    Controller: ProductBarcodeListController,
});
