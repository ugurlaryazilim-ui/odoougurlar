/** @odoo-module **/
/**
 * Ürün sayfasında varyant değiştiğinde SKU ve Barkod bilgisini günceller.
 *
 * _get_combination_info() override'ı ile gelen default_code ve barcode
 * değerlerini #variant_sku_value ve #variant_barcode_value elementlerine yazar.
 */
import publicWidget from '@web/legacy/js/public/public_widget';

const WebsiteSaleWidget = publicWidget.registry.WebsiteSale;
if (WebsiteSaleWidget) {
    WebsiteSaleWidget.include({
        _onChangeCombination(ev, $parent, combination) {
            this._super.apply(this, arguments);

            // SKU güncelle
            const $sku = $parent.find('#variant_sku_value');
            if ($sku.length) {
                $sku.text(combination.default_code || '-');
            }

            // Barkod güncelle
            const $barcode = $parent.find('#variant_barcode_value');
            if ($barcode.length) {
                $barcode.text(combination.barcode || '-');
            }
        },
    });
}
