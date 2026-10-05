/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

export class TailorMainMenu extends Component {
    static template = "ugurlar_tailor.TailorMainMenu";
    static props = {
        onNavigate: Function,
    };

    setup() {
        this.stats = useState({ waiting_approval: 0, pending: 0, in_progress: 0, completed: 0, overdue: 0 });
        onWillStart(async () => {
            try {
                Object.assign(this.stats, await rpc("/ugurlar_tailor/stats", {}));
            } catch (e) {
                console.error("Terzi sayaçları alınamadı:", e);
            }
        });
    }

    onNewOrder() {
        this.props.onNavigate("new_order");
    }

    onOrderList() {
        this.props.onNavigate("order_list");
    }

    onGiftLabel() {
        this.props.onNavigate("gift_label");
    }

    onStoreItem() {
        this.props.onNavigate("store_item");
    }
}
