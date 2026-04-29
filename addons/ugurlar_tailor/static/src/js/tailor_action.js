/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { TailorMainMenu } from "./screens/tailor_main_menu";
import { TailorNewOrder } from "./screens/tailor_new_order";
import { TailorOrderList } from "./screens/tailor_order_list";

export class TailorAction extends Component {
    static template = "ugurlar_tailor.TailorAction";
    static components = { TailorMainMenu, TailorNewOrder, TailorOrderList };

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            screen: "main_menu",
        });
    }

    switchScreen(screen) {
        this.state.screen = screen;
    }
}

registry.category("actions").add("ugurlar_tailor.TailorAction", TailorAction);
