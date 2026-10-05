/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { TailorMainMenu } from "./screens/tailor_main_menu";
import { TailorNewOrder } from "./screens/tailor_new_order";
import { TailorOrderList } from "./screens/tailor_order_list";
import { TailorGiftLabel } from "./screens/tailor_gift_label";
import { TailorStoreItem } from "./screens/tailor_store_item";
import { TailorBarcodeScanner } from "./tailor_scanner";

export class TailorAction extends Component {
    static template = "ugurlar_tailor.TailorAction";
    static components = { TailorMainMenu, TailorNewOrder, TailorOrderList, TailorGiftLabel, TailorStoreItem };

    setup() {
        this.notification = useService("notification");
        this.scanner = new TailorBarcodeScanner();
        this.state = useState({
            screen: "main_menu",
            listStatus: "",
        });

        onMounted(() => {
            this.scanner.start();
        });

        onWillUnmount(() => {
            this.scanner.stop();
        });
    }

    switchScreen(screen, params = {}) {
        // Sayaç kartından gelince liste o duruma süzülü açılır
        this.state.listStatus = params.status || "";
        this.state.screen = screen;
    }
}

registry.category("actions").add("ugurlar_tailor.TailorAction", TailorAction);
