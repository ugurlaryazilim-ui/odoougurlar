/** @odoo-module **/

import { Component } from "@odoo/owl";

export class TailorMainMenu extends Component {
    static template = "ugurlar_tailor.TailorMainMenu";
    static props = {
        onNavigate: Function,
    };

    onNewOrder() {
        this.props.onNavigate("new_order");
    }

    onOrderList() {
        this.props.onNavigate("order_list");
    }
}
