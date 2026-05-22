/** @odoo-module */
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Stok Konumları — özel list view controller.
 * Butonlar:
 *   📦 Raf Detay Dosyası  — lokasyon bilgilerini indirir
 *   📋 Ürün Listesi       — raflardaki ürün detaylarını indirir
 *   🚚 Transfer Siparişi  — depolar arası transfer wizard'ı açar
 * Aktif filtreleri (domain) export'a iletir.
 */
export class StockLocationListController extends ListController {
    setup() {
        super.setup();
        this.actionService = useService("action");
    }

    _getCurrentDomain() {
        const domain = this.model.root.domain || [];
        return JSON.stringify(domain);
    }

    onExportShelfDetail() {
        const domainStr = this._getCurrentDomain();
        const url = `/odoougurlar/shelf_detail_export?domain=${encodeURIComponent(domainStr)}`;
        this.actionService.doAction({
            type: "ir.actions.act_url",
            url: url,
            target: "self",
        });
    }

    onExportProductList() {
        const domainStr = this._getCurrentDomain();
        const url = `/odoougurlar/product_list_export?domain=${encodeURIComponent(domainStr)}`;
        this.actionService.doAction({
            type: "ir.actions.act_url",
            url: url,
            target: "self",
        });
    }

    onCreateTransfer() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "odoougurlar.transfer.wizard",
            name: "Transfer Siparişi Oluştur",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
        });
    }
}

// web.ListView'u inherit eden template
StockLocationListController.template = "odoougurlar.StockLocationListView";

// Custom view olarak kaydet
registry.category("views").add("stock_location_list", {
    ...listView,
    Controller: StockLocationListController,
});
