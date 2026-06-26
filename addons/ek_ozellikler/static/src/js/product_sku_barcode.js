/** @odoo-module **/
/**
 * Ürün sayfasında SKU ve Barkod bilgisini gösterir.
 *
 * Template/xpath kullanmadan, pure JS ile DOM'a ekler.
 * Variant değiştiğinde (renk/beden) dinamik günceller.
 *
 * Ayarlar: /ek_ozellikler/product_settings JSON endpoint'inden okunur.
 */
import publicWidget from '@web/legacy/js/public/public_widget';
import { rpc } from '@web/core/network/rpc';

// Ayarları cache'le — sayfa başına 1 RPC yeterli
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

// ── WebsiteSale widget'ını genişlet ──
const WebsiteSaleWidget = publicWidget.registry.WebsiteSale;
if (WebsiteSaleWidget) {
    WebsiteSaleWidget.include({
        /**
         * Variant değiştiğinde çağrılır (ilk yüklemede de).
         * SKU/Barkod container'ını oluştur (yoksa) ve güncelle.
         */
        async _onChangeCombination(ev, $parent, combination) {
            this._super.apply(this, arguments);

            const settings = await getSettings();
            if (!settings.show_sku && !settings.show_barcode) {
                return;
            }

            // Container'ı bul veya oluştur
            let container = $parent[0].querySelector('#product_sku_barcode_section');
            if (!container) {
                container = this._createSkuBarcodeContainer(
                    $parent[0], settings
                );
            }
            if (!container) return;

            // Değerleri güncelle
            if (settings.show_sku) {
                const skuEl = container.querySelector('#variant_sku_value');
                if (skuEl) {
                    skuEl.textContent = combination.default_code || '-';
                }
            }
            if (settings.show_barcode) {
                const barcodeEl = container.querySelector('#variant_barcode_value');
                if (barcodeEl) {
                    barcodeEl.textContent = combination.barcode || '-';
                }
            }
        },

        /**
         * SKU/Barkod container'ını DOM'a ekler.
         * Fiyatın altına veya varyant seçicinin altına yerleşir.
         */
        _createSkuBarcodeContainer(parentEl, settings) {
            // Ekleme noktasını bul — en uygun yeri seç
            const insertTarget =
                parentEl.querySelector('[itemprop="offers"]') ||
                parentEl.querySelector('.product_price') ||
                parentEl.querySelector('.o_product_price') ||
                parentEl.querySelector('.oe_price_h4')?.parentElement ||
                parentEl.querySelector('form[action*="/shop/cart/update"]');

            if (!insertTarget) return null;

            // Container oluştur
            const container = document.createElement('div');
            container.id = 'product_sku_barcode_section';
            container.className = 'mb-2 mt-1';
            container.style.cssText = 'font-size: 0.85rem; color: #666;';

            if (settings.show_sku) {
                const skuDiv = document.createElement('div');
                skuDiv.className = 'd-flex align-items-center gap-1 mb-1';
                skuDiv.innerHTML =
                    '<span class="fw-bold" style="color:#555;">SKU:</span>' +
                    '<span id="variant_sku_value" class="text-dark">-</span>';
                container.appendChild(skuDiv);
            }

            if (settings.show_barcode) {
                const barcodeDiv = document.createElement('div');
                barcodeDiv.className = 'd-flex align-items-center gap-1';
                barcodeDiv.innerHTML =
                    '<span class="fw-bold" style="color:#555;">Barkod:</span>' +
                    '<span id="variant_barcode_value" class="text-dark">-</span>';
                container.appendChild(barcodeDiv);
            }

            // Fiyatın hemen sonrasına ekle
            insertTarget.after(container);
            return container;
        },
    });
}
