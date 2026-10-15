/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { TailorBarcodeScanner } from "@ugurlar_tailor/js/tailor_scanner";
import { VcMainMenu } from "./screens/main_menu";
import { VcNewClaim } from "./screens/new_claim";
import { VcClaimList } from "./screens/claim_list";
import { VcBulk } from "./screens/bulk";

/** Tedarikçi İnceleme mobil ekranı (terzi mobil ekranıyla aynı yapı). */
export class VendorClaimAction extends Component {
    static template = "vendor_claim.VendorClaimAction";
    static components = { VcMainMenu, VcNewClaim, VcClaimList, VcBulk };
    static props = ["*"];

    setup() {
        // El terminali (keyboard wedge) okutmaları; ekranlar onScan ile abone olur
        this.scanner = new TailorBarcodeScanner();
        this.state = useState({ screen: "main_menu", listStatus: "", openId: null });
        onMounted(() => this.scanner.start());
        onWillUnmount(() => this.scanner.stop());
    }

    switchScreen(screen, params = {}) {
        this.state.listStatus = params.status || "";
        this.state.openId = params.openId || null;
        this.state.screen = screen;
    }
}

registry.category("actions").add("vendor_claim.VendorClaimAction", VendorClaimAction);
