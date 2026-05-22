/** @odoo-module */
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Stok Konumları — özel list view controller.
 * "Yeni" butonunun yanında "📦 Raf Detay Dosyası" butonu gösterir.
 */
export class StockLocationListController extends ListController {
    setup() {
        super.setup();
        this.actionService = useService("action");
    }

    async onExportShelfDetail() {
        this.actionService.doAction({
            type: "ir.actions.act_url",
            url: "/odoougurlar/shelf_detail_export",
            target: "self",
        });
    }
}

// Custom view olarak kaydet
registry.category("views").add("stock_location_list", {
    ...listView,
    Controller: StockLocationListController,
    buttonTemplate: "odoougurlar.StockLocationListButtons",
});
