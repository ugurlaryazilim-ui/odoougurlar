/** @odoo-module **/
/**
 * Ürün sayfasında SKU ve Barkod bilgisini gösterir.
 *
 * Odoo 19'da website_sale `Interaction` API kullanır.
 * VariantMixin._onChangeCombination callback'i ile çalışır.
 *
 * Variant değiştiğinde (renk/beden):
 *   1. _getCombinationInfo → /website_sale/get_combination_info RPC çağrısı
 *   2. _onChangeCombination(ev, parent, combinationInfo) çağrılır
 *   3. Bu patch, combinationInfo'dan default_code ve barcode okur
 *   4. DOM elementlerini günceller
 */
import { Interaction } from '@web/public/interaction';
import { registry } from '@web/core/registry';
import { rpc } from '@web/core/network/rpc';

// ── Ayarları cache'le ──
let _settingsCache = null;
async function getSettings() {
    if (_settingsCache === null) {
        try {
            _settingsCache = await rpc('/ek_ozellikler/product_settings', {});
        } catch {
            _settingsCache = { show_sku: false, show_barcode: false };
        }
    }
    return _settingsCache;
}

/**
 * Ürün sayfasına SKU/Barkod bölümü ekleyen Interaction.
 *
 * .oe_website_sale selector'ı ile ürün sayfasında aktif olur.
 * _onChangeCombination callback'ine hook olarak çalışır.
 */
export class ProductSkuBarcode extends Interaction {
    static selector = '#product_detail .js_product';

    setup() {
        this.skuBarcodeContainer = null;
        this.settingsLoaded = false;
        this.showSku = false;
        this.showBarcode = false;
    }

    async start() {
        const settings = await getSettings();
        this.showSku = settings.show_sku;
        this.showBarcode = settings.show_barcode;
        this.settingsLoaded = true;

        if (!this.showSku && !this.showBarcode) return;

        // İlk değeri almak için mevcut variant bilgisini çek
        this._createContainer();
        this._fetchInitialData();
    }

    /**
     * Fiyatın altına SKU/Barkod container'ını ekler.
     */
    _createContainer() {
        const priceSection =
            this.el.querySelector('.product_price') ||
            this.el.querySelector('[name="product_price"]') ||
            this.el.querySelector('.oe_price')?.closest('div');

        if (!priceSection) return;

        // Zaten ekli mi kontrol et
        if (this.el.querySelector('#product_sku_barcode_section')) return;

        const container = document.createElement('div');
        container.id = 'product_sku_barcode_section';
        container.className = 'mt-2 mb-2';
        container.style.cssText = 'font-size: 0.85rem; color: #666;';

        if (this.showSku) {
            const skuDiv = document.createElement('div');
            skuDiv.className = 'd-flex align-items-center gap-1 mb-1';
            skuDiv.innerHTML =
                '<span class="fw-bold" style="color:#555;">SKU:</span>' +
                '<span id="variant_sku_value" class="text-dark">-</span>';
            container.appendChild(skuDiv);
        }

        if (this.showBarcode) {
            const barcodeDiv = document.createElement('div');
            barcodeDiv.className = 'd-flex align-items-center gap-1';
            barcodeDiv.innerHTML =
                '<span class="fw-bold" style="color:#555;">Barkod:</span>' +
                '<span id="variant_barcode_value" class="text-dark">-</span>';
            container.appendChild(barcodeDiv);
        }

        // Fiyat bölümünün parent section'ının sonuna ekle
        const priceParent = priceSection.closest(
            '.o_wsale_product_details_content_section_price'
        );
        if (priceParent) {
            priceParent.appendChild(container);
        } else {
            priceSection.after(container);
        }

        this.skuBarcodeContainer = container;
    }

    /**
     * İlk yüklemede mevcut variant'ın bilgisini çeker.
     */
    async _fetchInitialData() {
        const productIdInput = this.el.querySelector('input.product_id');
        const templateIdInput = this.el.querySelector('input.product_template_id');
        if (!productIdInput || !templateIdInput) return;

        try {
            const combinationInfo = await rpc('/website_sale/get_combination_info', {
                product_template_id: parseInt(templateIdInput.value),
                product_id: parseInt(productIdInput.value),
                combination: [],
                add_qty: 1,
            });
            this._updateValues(combinationInfo);
        } catch {
            // Sessizce geç
        }
    }

    /**
     * SKU ve barkod değerlerini günceller.
     */
    _updateValues(combinationInfo) {
        if (!this.skuBarcodeContainer) return;

        if (this.showSku) {
            const skuEl = this.skuBarcodeContainer.querySelector('#variant_sku_value');
            if (skuEl) {
                skuEl.textContent = combinationInfo.default_code || '-';
            }
        }
        if (this.showBarcode) {
            const barcodeEl = this.skuBarcodeContainer.querySelector('#variant_barcode_value');
            if (barcodeEl) {
                barcodeEl.textContent = combinationInfo.barcode || '-';
            }
        }
    }
}

registry
    .category('public.interactions')
    .add('ek_ozellikler.product_sku_barcode', ProductSkuBarcode);

// ── VariantMixin patch: variant değiştiğinde SKU/Barkod güncelle ──
import VariantMixin from '@website_sale/js/variant_mixin';
const _originalOnChangeCombination = VariantMixin._onChangeCombination;

VariantMixin._onChangeCombination = function (ev, parent, combinationInfo) {
    // Orijinal fonksiyonu çağır
    if (_originalOnChangeCombination) {
        _originalOnChangeCombination.apply(this, arguments);
    }

    // SKU/Barkod güncelle
    if (!parent) return;
    const container = parent.querySelector
        ? parent.querySelector('#product_sku_barcode_section')
        : parent.find?.('#product_sku_barcode_section')?.[0];
    if (!container || !combinationInfo) return;

    const skuEl = container.querySelector('#variant_sku_value');
    if (skuEl) {
        skuEl.textContent = combinationInfo.default_code || '-';
    }
    const barcodeEl = container.querySelector('#variant_barcode_value');
    if (barcodeEl) {
        barcodeEl.textContent = combinationInfo.barcode || '-';
    }
};
