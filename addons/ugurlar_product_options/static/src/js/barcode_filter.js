/** @odoo-module */

import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";

/**
 * Ürün Varyantları — Sütun Bazlı Barkod/Referans Filtre
 *
 * ListController extend + DOM enjeksiyonu + MutationObserver.
 * Sort ikonunun yanına filtre ikonu ekler.
 * MutationObserver ile Odoo re-render'larda ikonun kaybolmasını engeller.
 */

const FILTERABLE_FIELDS = ['barcode', 'default_code'];

export class ProductBarcodeListController extends ListController {
    setup() {
        super.setup();
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.orm = useService("orm");

        this._bfActiveDropdown = null;
        // sessionStorage'dan filtre state'ini yükle (doAction sonrası korunur)
        this._bfFilterTexts = this._bfLoadState('bfTexts') || {};
        this._bfFilterValues = this._bfLoadState('bfValues') || {};
        this._onDocClickBound = this._onDocClick.bind(this);
        this._observer = null;

        onMounted(() => {
            this._injectFilterIcons();
            this._startObserver();
        });
        onPatched(() => this._injectFilterIcons());
        onWillUnmount(() => this._stopObserver());
    }

    // ═══════════════════════════════════════════════════
    // MutationObserver — Odoo re-render'larda ikonu koru
    // ═══════════════════════════════════════════════════

    _startObserver() {
        const el = this._getListEl();
        if (!el) return;
        const thead = el.querySelector('thead');
        if (!thead) return;

        this._observer = new MutationObserver(() => {
            this._injectFilterIcons();
        });
        this._observer.observe(thead, { childList: true, subtree: true });
    }

    _stopObserver() {
        if (this._observer) {
            this._observer.disconnect();
            this._observer = null;
        }
    }

    _getListEl() {
        return this.rootRef?.el || document.querySelector('.o_list_view');
    }

    // ═══════════════════════════════════════════════════
    // DOM Enjeksiyonu — Sort ikonunun yanına filtre ikonu
    // ═══════════════════════════════════════════════════

    _injectFilterIcons() {
        const el = this._getListEl();
        if (!el) return;

        const headers = el.querySelectorAll('thead th[data-name]');

        headers.forEach(th => {
            const fieldName = th.dataset.name;
            if (!FILTERABLE_FIELDS.includes(fieldName)) return;
            if (th.querySelector('.bf-icon')) return;

            const sortIcon = th.querySelector('.o_list_sortable_icon');
            if (!sortIcon) return;

            // Filtre ikonu — sort ikonuyla aynı parent div içinde
            const icon = document.createElement('i');
            icon.className = 'bf-icon fa fa-filter';
            icon.dataset.bfField = fieldName;
            icon.title = fieldName === 'barcode' ? 'Barkod Filtre' : 'İç Referans Filtre';

            // Sort ikonu position:absolute right:0.25rem kullanıyor
            // Filtre ikonunu da absolute yap, sort ikonunun SOLUNA yerleştir
            icon.style.setProperty('opacity', '1', 'important');
            icon.style.setProperty('visibility', 'visible', 'important');
            icon.style.setProperty('display', 'inline-block', 'important');
            icon.style.setProperty('font-size', '14px', 'important');
            icon.style.setProperty('color', '#888', 'important');
            icon.style.setProperty('cursor', 'pointer', 'important');
            icon.style.setProperty('z-index', '2', 'important');
            icon.style.setProperty('position', 'absolute', 'important');
            icon.style.setProperty('right', '1.5rem', 'important');
            icon.style.setProperty('top', '50%', 'important');
            icon.style.setProperty('transform', 'translateY(-50%)', 'important');
            icon.style.setProperty('padding', '2px 4px', 'important');

            if (this._bfFilterValues[fieldName]?.length > 0) {
                icon.classList.add('bf-icon-active');
                icon.style.setProperty('color', '#714B67', 'important');
                icon.style.setProperty('background', 'rgba(113, 75, 103, 0.15)', 'important');
                icon.style.setProperty('border-radius', '3px', 'important');
            }

            icon.addEventListener('click', (e) => {
                e.stopPropagation();
                e.preventDefault();
                this._toggleDropdown(fieldName, th);
            });

            // th'ye ekle (position:relative olan element — absolute için referans)
            th.appendChild(icon);
        });
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

        const label = fieldName === 'barcode' ? 'Barkod' : 'İç Referans';
        const savedText = this._bfFilterTexts[fieldName] || '';
        const hasFilter = this._bfFilterValues[fieldName]?.length > 0;
        const count = this._bfFilterValues[fieldName]?.length || 0;
        const hasAnyData = hasFilter || savedText.trim().length > 0;

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
                <button class="bf-dd-btn bf-dd-export">
                    <i class="fa fa-file-excel-o"></i> Dışa Aktar
                </button>
                <button class="bf-dd-btn bf-dd-clear" ${!hasAnyData ? 'style="display:none"' : ''}>
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

        textarea.addEventListener('paste', () => {
            setTimeout(() => this._applyFilter(fieldName, textarea), 100);
        });

        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._applyFilter(fieldName, textarea);
            }
            if (e.key === 'Escape') {
                this._closeDropdown();
            }
        });

        dropdown.querySelector('.bf-dd-filter').addEventListener('click', () => {
            this._applyFilter(fieldName, textarea);
        });
        dropdown.querySelector('.bf-dd-export').addEventListener('click', () => {
            this._applyFilterAndExport(fieldName, textarea);
        });
        dropdown.querySelector('.bf-dd-clear').addEventListener('click', () => {
            this._clearFilter(fieldName);
        });

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
                this._bfSaveState('bfTexts', this._bfFilterTexts);
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
        this._bfSaveState('bfTexts', this._bfFilterTexts);
        this._bfSaveState('bfValues', this._bfFilterValues);
        this._closeDropdown();
        this._executeFilter();
    }

    _clearFilter(fieldName) {
        delete this._bfFilterTexts[fieldName];
        delete this._bfFilterValues[fieldName];
        this._bfSaveState('bfTexts', this._bfFilterTexts);
        this._bfSaveState('bfValues', this._bfFilterValues);
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

    // ═══════════════════════════════════════════════════
    // sessionStorage — doAction sonrası state korunur
    // ═══════════════════════════════════════════════════

    _bfSaveState(key, data) {
        try {
            sessionStorage.setItem(`bf_${key}`, JSON.stringify(data));
        } catch (e) { /* quota aşımı vb. */ }
    }

    _bfLoadState(key) {
        try {
            const raw = sessionStorage.getItem(`bf_${key}`);
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            return null;
        }
    }

    // ═══════════════════════════════════════════════════
    // Filtrele & Dışa Aktar (doğrudan XLSX indirme)
    // ═══════════════════════════════════════════════════

    async _applyFilterAndExport(fieldName, textarea) {
        const text = textarea.value;
        const values = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
        if (values.length === 0) {
            this.notification.add('Lütfen en az bir değer girin', { type: 'warning' });
            return;
        }

        // State'i kaydet
        this._bfFilterTexts[fieldName] = text;
        this._bfFilterValues[fieldName] = values;
        this._bfSaveState('bfTexts', this._bfFilterTexts);
        this._bfSaveState('bfValues', this._bfFilterValues);

        this._closeDropdown();

        // Domain oluştur
        const domain = [];
        for (const [field, vals] of Object.entries(this._bfFilterValues)) {
            if (vals && vals.length > 0) {
                domain.push([field, "in", vals]);
            }
        }

        this.notification.add(
            `${values.length} ${fieldName === 'barcode' ? 'barkod' : 'referans'} ile dışa aktarılıyor...`,
            { type: 'info' }
        );

        try {
            // 1. ORM ile eşleşen ID'leri bul
            const ids = await this.orm.search('product.product', domain);

            if (ids.length === 0) {
                this.notification.add('Eşleşen ürün bulunamadı', { type: 'warning' });
                return;
            }

            // 2. Export alanları
            const exportFields = [
                { name: 'default_code', label: 'İç Referans', type: 'char' },
                { name: 'barcode', label: 'Barkod', type: 'char' },
                { name: 'name', label: 'Adı', type: 'char' },
                { name: 'product_template_variant_value_ids', label: 'Varyant Değerleri', type: 'many2many' },
                { name: 'list_price', label: 'Satış Fiyatı', type: 'monetary' },
                { name: 'standard_price', label: 'Maliyet', type: 'monetary' },
                { name: 'qty_available', label: 'Stokta', type: 'float' },
                { name: 'virtual_available', label: 'Öngörülen', type: 'float' },
            ];

            // 3. Form submission ile XLSX indir
            const exportData = JSON.stringify({
                model: 'product.product',
                fields: exportFields,
                ids: ids,
                domain: [],
                groupby: [],
                context: {},
                import_compat: false,
            });

            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/web/export/xlsx';
            form.style.display = 'none';

            const dataInput = document.createElement('input');
            dataInput.type = 'hidden';
            dataInput.name = 'data';
            dataInput.value = exportData;
            form.appendChild(dataInput);

            // CSRF token
            const csrfMeta = document.querySelector('meta[name="csrf-token"]');
            const csrfCookie = document.cookie.split(';').find(c => c.trim().startsWith('csrf_token='));
            const csrfToken = csrfMeta?.content
                || (csrfCookie ? csrfCookie.split('=')[1] : '')
                || (window.odoo?.csrf_token || '');

            if (csrfToken) {
                const csrfInput = document.createElement('input');
                csrfInput.type = 'hidden';
                csrfInput.name = 'csrf_token';
                csrfInput.value = csrfToken;
                form.appendChild(csrfInput);
            }

            document.body.appendChild(form);
            form.submit();
            setTimeout(() => document.body.removeChild(form), 2000);

            this.notification.add(
                `${ids.length} ürün Excel'e aktarılıyor...`,
                { type: 'success' }
            );

        } catch (e) {
            console.error('[BarcodeFilter] Export error:', e);
            this.notification.add(
                `Dışa aktarma hatası: ${e.message || 'Bilinmeyen hata'}`,
                { type: 'danger' }
            );
        }
    }
}


registry.category("views").add("product_barcode_list", {
    ...listView,
    Controller: ProductBarcodeListController,
});
