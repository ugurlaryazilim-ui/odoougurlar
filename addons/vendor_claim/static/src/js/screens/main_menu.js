/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

export class VcMainMenu extends Component {
    static template = "vendor_claim.VcMainMenu";
    static props = { onNavigate: Function };

    setup() {
        this.notification = useService("notification");
        this.stats = useState({ received: 0, sent: 0, returned: 0, overdue: 0 });
        onWillStart(async () => {
            try {
                const res = await rpc("/vendor_claim/stats", {});
                if (res.error) {
                    throw new Error(res.error);
                }
                Object.assign(this.stats, res);
            } catch (e) {
                // Hata "0 kayıt var" gibi görünmesin: sayaçlar "-" olur ve kullanıcı uyarılır (KK-B22)
                console.error("İnceleme sayaçları alınamadı:", e);
                Object.assign(this.stats, { received: "-", sent: "-", returned: "-", overdue: "-" });
                this.notification.add(_t("Sayaçlar alınamadı: %(error)s", { error: e.message }), { type: "warning" });
            }
        });
    }

    go(screen, params = {}) {
        this.props.onNavigate(screen, params);
    }
}
