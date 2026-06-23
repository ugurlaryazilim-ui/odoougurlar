/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class ScanScreen extends Component {
    static template = "ugurlar_ai_studio.ScanScreen";
    static props = {
        dashboardStats: { type: Object },
        onProductFound: { type: Function },
        onGoToHistory: { type: Function },
        onGoToBatchReview: { type: Function },
    };

    setup() {
        this.notification = useService("notification");

        this.state = useState({
            query: "",
            searching: false,
            results: [],
            showResults: false,
        });
    }

    async _jsonRpc(url, params = {}) {
        const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ jsonrpc: "2.0", method: "call", params }),
        });
        const data = await response.json();
        if (data.error) {
            throw new Error(data.error.data?.message || data.error.message || "RPC Error");
        }
        return data.result;
    }

    async onInputChange(ev) {
        this.state.query = ev.target.value;
    }

    async onKeyDown(ev) {
        if (ev.key === "Enter") {
            await this.searchProduct();
        }
    }

    async searchProduct() {
        const query = this.state.query.trim();
        if (!query) return;

        this.state.searching = true;
        this.state.showResults = false;

        try {
            const res = await this._jsonRpc("/ai_studio/find_product", { query });
            if (res.found && res.products.length === 1) {
                this.props.onProductFound(res.products[0]);
            } else if (res.found && res.products.length > 1) {
                this.state.results = res.products;
                this.state.showResults = true;
            } else {
                this.notification.add(_t("Urun bulunamadi."), { type: "warning" });
            }
        } catch (e) {
            this.notification.add(_t("Arama hatasi."), { type: "danger" });
        } finally {
            this.state.searching = false;
        }
    }

    selectProduct(product) {
        this.props.onProductFound(product);
    }

    clearSearch() {
        this.state.query = "";
        this.state.results = [];
        this.state.showResults = false;
    }
}
