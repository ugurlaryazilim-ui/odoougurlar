/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { printTailorSlips } from "../label_print";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";

/**
 * Toplu barkod işlemi: hedef durum seçilir, sipariş barkodları (etiketteki TRZ-xxxxx ya da ürün
 * barkodu) art arda okutulur, liste tek tuşla ilerletilir. "Terzide" yapılınca terzi teslim fişi basılır.
 */
export class TailorBulk extends Component {
    static template = "ugurlar_tailor.TailorBulk";
    static props = {
        onNavigate: Function,
        scanner: Object,
    };

    targets = [
        ["in_progress", _t("Terziye Gönder (Terzide)")],
        ["completed", _t("Terziden Döndü (Hazır)")],
        ["delivered", _t("Müşteriye Teslim")],
    ];

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            target: "in_progress",
            code: "",
            items: [],
            location: "",
            busy: false,
            results: null,
        });
        this.inputRef = useRef("bulkInput");
        this._unsub = this.props.scanner.onScan((code) => this.addCode(code));
        onMounted(() => this.inputRef.el?.focus());
        onWillUnmount(() => this._unsub && this._unsub());
    }

    async addCode(code) {
        code = (code || this.state.code || "").trim();
        this.state.code = "";
        if (!code) return;
        try {
            const res = await rpc("/ugurlar_tailor/find_order", { code });
            if (res.error) {
                this.notification.add(res.error, { type: "warning" });
                return;
            }
            if (this.state.items.find((i) => i.id === res.id)) {
                this.notification.add(_t("%(name)s zaten listede.", { name: res.name }), { type: "warning" });
                return;
            }
            this.state.items.push(res);
            this.state.results = null;
        } catch (e) {
            this.notification.add(_t("Arama hatası: %(error)s", { error: e.message }), { type: "danger" });
        }
        this.inputRef.el?.focus();
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            this.addCode();
        }
    }

    remove(id) {
        this.state.items = this.state.items.filter((i) => i.id !== id);
    }

    resultFor(id) {
        return (this.state.results || []).find((r) => r.id === id);
    }

    async apply() {
        if (!this.state.items.length) return;
        this.state.busy = true;
        try {
            const res = await rpc("/ugurlar_tailor/bulk_status", {
                order_ids: this.state.items.map((i) => i.id),
                status: this.state.target,
                location: this.state.target === "completed" ? this.state.location : null,
            });
            this.state.results = res.results || [];
            const okCount = this.state.results.filter((r) => r.ok).length;
            const failCount = this.state.results.length - okCount;
            this.notification.add(
                _t("%(ok)s sipariş güncellendi%(fail)s", {
                    ok: okCount,
                    fail: failCount ? _t(", %(n)s sipariş güncellenemedi", { n: failCount }) : "",
                }),
                { type: failCount ? "warning" : "success" }
            );
            if (res.slips && res.slips.length) {
                printTailorSlips(res.slips);
            }
            // Başarılı olanlar listeden çıkar; hatalılar sebebiyle kalır
            this.state.items = this.state.items.filter((i) => !this.resultFor(i.id)?.ok);
        } catch (e) {
            this.notification.add(_t("Toplu işlem hatası: %(error)s", { error: e.message }), { type: "danger" });
        }
        this.state.busy = false;
    }

    scanCamera() {
        openCameraScanner((code) => this.addCode(code), { headerText: _t("Sipariş Barkodu Okut") });
    }

    goBack() {
        this.props.onNavigate("main_menu");
    }
}
