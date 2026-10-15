/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";
import { RESULT_OPTIONS } from "./claim_list";

/**
 * Toplu işlem: hedef seçilir, takip no (INC-...) ya da ürün barkodları art arda okutulur,
 * hepsi tek tuşla ilerletilir (ör. aynı kargoyla giden ürünler → "Tedarikçiye gönderildi").
 */
export class VcBulk extends Component {
    static template = "vendor_claim.VcBulk";
    static props = { onNavigate: Function, scanner: Object };

    targets = [
        ["send", _t("Tedarikçiye Gönderildi")],
        ["return", _t("İncelemeden Geldi")],
        ["deliver", _t("Müşteriye Teslim")],
    ];
    resultOptions = RESULT_OPTIONS;

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            target: "send",
            code: "",
            items: [],
            carrier: "",
            tracking: "",
            result: "",
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
            const res = await rpc("/vendor_claim/find", { code });
            if (res.error) {
                this.notification.add(res.error, { type: "warning" });
            } else if (this.state.items.find((i) => i.id === res.id)) {
                this.notification.add(_t("%(name)s zaten listede.", { name: res.name }), { type: "warning" });
            } else {
                this.state.items.push(res);
                this.state.results = null;
            }
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
        const s = this.state;
        if (!s.items.length) return;
        if (s.target === "return" && !s.result) {
            this.notification.add(_t("Tedarikçiden gelen sonucu seçin."), { type: "warning" });
            return;
        }
        const vals = s.target === "send"
            ? { out_carrier: s.carrier, out_tracking: s.tracking }
            : s.target === "return"
                ? { in_carrier: s.carrier, in_tracking: s.tracking, result: s.result }
                : {};
        s.busy = true;
        try {
            const res = await rpc("/vendor_claim/bulk", {
                claim_ids: s.items.map((i) => i.id), action: s.target, vals,
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                s.results = res.results || [];
                const ok = s.results.filter((r) => r.ok).length;
                const fail = s.results.length - ok;
                this.notification.add(
                    _t("%(ok)s kayıt güncellendi%(fail)s", {
                        ok, fail: fail ? _t(", %(n)s kayıt güncellenemedi", { n: fail }) : "",
                    }),
                    { type: fail ? "warning" : "success" }
                );
                // Başarılı olanlar listeden çıkar; hatalılar sebebiyle kalır
                s.items = s.items.filter((i) => !this.resultFor(i.id)?.ok);
            }
        } catch (e) {
            this.notification.add(_t("Toplu işlem hatası: %(error)s", { error: e.message }), { type: "danger" });
        }
        s.busy = false;
    }

    scanCamera() {
        openCameraScanner((code) => this.addCode(code), { headerText: _t("Takip No / Ürün Barkodu Okut") });
    }

    goBack() {
        this.props.onNavigate("main_menu");
    }
}
