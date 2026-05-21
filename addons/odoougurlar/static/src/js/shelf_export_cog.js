/** @odoo-module */
import { registry } from "@web/core/registry";
import { Component, xml } from "@odoo/owl";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

/**
 * Raf Detay Dosyası — CogMenu (çark menüsü) öğesi.
 * stock.location list view'ında kayıt seçmeden her zaman görünür.
 */
class ShelfDetailExport extends Component {
    static template = xml`
        <DropdownItem onSelected.bind="onExport">
            📦 Raf Detay Dosyası
        </DropdownItem>
    `;
    static components = { DropdownItem };

    onExport() {
        // Controller endpoint'ine yönlendir — doğrudan Excel indir
        this.env.services.action.doAction({
            type: 'ir.actions.act_url',
            url: '/odoougurlar/shelf_detail_export',
            target: 'self',
        });
    }
}

// CogMenu registry'sine ekle — sadece stock.location modelinde göster
registry.category("cogMenu").add("shelf_detail_export", {
    Component: ShelfDetailExport,
    groupNumber: 4,
    isDisplayed: (env) => {
        return env.config && env.config.resModel === "stock.location";
    },
});
