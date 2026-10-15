/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

export class VcMainMenu extends Component {
    static template = "vendor_claim.VcMainMenu";
    static props = { onNavigate: Function };

    setup() {
        this.stats = useState({ received: 0, sent: 0, returned: 0, overdue: 0 });
        onWillStart(async () => {
            try {
                Object.assign(this.stats, await rpc("/vendor_claim/stats", {}));
            } catch (e) {
                console.error("İnceleme sayaçları alınamadı:", e);
            }
        });
    }

    go(screen, params = {}) {
        this.props.onNavigate(screen, params);
    }
}
