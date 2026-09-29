/** @odoo-module **/
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";
import { aisRpc } from "../rpc_utils";

import { Component, useState } from "@odoo/owl";
import { useAutofocus, useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class ScanScreen extends Component {
    static template = "ugurlar_ai_studio.ScanScreen";
    static props = {
        dashboardStats: { type: Object },
        userRole: { type: String, optional: true },
        onProductFound: { type: Function },
        onGoToHistory: { type: Function },
        onGoToBatchReview: { type: Function },
    };

    setup() {
        this.notification = useService("notification");
        // Ekrana her dönüşte odak: klavye kamalı barkod okuyucu boşluğa yazmasın
        useAutofocus({ refName: "searchInput" });

        this.state = useState({
            query: "",
            searching: false,
            results: [],
            showResults: false,
        });
    }

    async _jsonRpc(url, params = {}) {
        return aisRpc(url, params);
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
        // Bazı okuyucular CR+LF gönderir: ikinci Enter aramayı tekrarlamasın
        if (!query || this.state.searching) return;

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
                this.notification.add(res.error || _t("Ürün bulunamadı."), {
                    type: res.error ? "danger" : "warning", sticky: false,
                });
            }
        } catch (e) {
            this.notification.add(e.message || _t("Arama hatası."), { type: "danger", sticky: false });
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

    startCameraScan() {
        openCameraScanner(async (barcode) => {
            this.state.query = barcode;
            await this.searchProduct();
        });
    }
}
