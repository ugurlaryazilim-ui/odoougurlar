/** @odoo-module **/

import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";
import { readPhoto } from "@ugurlar_tailor/js/photo_utils";
import { notifySms } from "@vendor_claim/js/sms_notice";

export const RESULT_OPTIONS = [
    ["repaired", _t("Tamir Edildi")],
    ["replaced", _t("Yenisiyle Değiştirildi")],
    ["refund", _t("İade Kabul (Para İadesi)")],
    ["rejected", _t("Ret (Kullanıcı Hatası)")],
];

/** Kayıt listesi + detay: durum ilerletme, not, fotoğraf, SMS, yazdırma. */
export class VcClaimList extends Component {
    static template = "vendor_claim.VcClaimList";
    static props = { onNavigate: Function, scanner: Object, initialStatus: { type: String, optional: true },
                     openId: { optional: true } };

    filters = [
        ["open", _t("Açık")],
        ["received", _t("Teslim Alındı")],
        ["sent", _t("Tedarikçide")],
        ["returned", _t("Geldi")],
        ["overdue", _t("Geciken")],
        ["delivered", _t("Teslim Edildi")],
        ["", _t("Tümü")],
    ];
    resultOptions = RESULT_OPTIONS;

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            status: this.props.initialStatus || "open",
            search: "",
            items: [],
            total: 0,
            loading: false,
            detail: null,
            busy: false,
            form: {},
            note: "",
            mobile: "",
        });
        this._unsub = this.props.scanner.onScan((code) => {
            this.state.search = code;
            this.state.detail = null;
            return this.load(true);
        });
        onWillStart(async () => {
            await this.load();
            if (this.props.openId) {
                await this.open(this.props.openId);
            }
        });
        onWillUnmount(() => this._unsub && this._unsub());
    }

    async load(autoOpen = false) {
        this.state.loading = true;
        try {
            const res = await rpc("/vendor_claim/list", { search: this.state.search, status: this.state.status });
            this.state.items = res.items || [];
            this.state.total = res.total || 0;
            if (autoOpen && this.state.items.length === 1) {
                await this.open(this.state.items[0].id);
            }
        } catch (e) {
            this.notification.add(_t("Liste alınamadı: %(error)s", { error: e.message }), { type: "danger" });
        }
        this.state.loading = false;
    }

    setStatus(status) {
        this.state.status = status;
        this.load();
    }

    onSearchKey(ev) {
        if (ev.key === "Enter") {
            this.load(true);
        }
    }

    scanCamera() {
        openCameraScanner((code) => {
            this.state.search = code;
            this.load(true);
        }, { headerText: _t("Takip No / Ürün Barkodu Okut") });
    }

    _setDetail(detail) {
        this.state.detail = detail;
        this.state.form = {
            out_carrier: detail.out_carrier, out_tracking: detail.out_tracking,
            in_carrier: detail.in_carrier, in_tracking: detail.in_tracking,
            result: detail.result, result_note: detail.result_note,
        };
        this.state.note = "";
        this.state.mobile = detail.customer_mobile;
    }

    async open(id) {
        try {
            const res = await rpc("/vendor_claim/detail", { claim_id: id });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
                return;
            }
            this._setDetail(res);
            window.scrollTo?.(0, 0);
        } catch (e) {
            this.notification.add(_t("Kayıt açılamadı: %(error)s", { error: e.message }), { type: "danger" });
        }
    }

    closeDetail() {
        this.state.detail = null;
        this.load();
    }

    async act(action, vals = {}, successMsg = "") {
        if (this.state.busy) return;
        this.state.busy = true;
        try {
            const res = await rpc("/vendor_claim/action", { claim_id: this.state.detail.id, action, vals });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this._setDetail(res);
                if (successMsg) {
                    this.notification.add(successMsg, { type: "success" });
                }
                notifySms(this.notification, res.sms);
            }
        } catch (e) {
            this.notification.add(_t("İşlem hatası: %(error)s", { error: e.message }), { type: "danger" });
        }
        this.state.busy = false;
    }

    sendToVendor() {
        const f = this.state.form;
        this.act("send", { out_carrier: f.out_carrier, out_tracking: f.out_tracking }, _t("Tedarikçiye gönderildi."));
    }

    markReturned() {
        const f = this.state.form;
        if (!f.result) {
            this.notification.add(_t("Tedarikçiden gelen sonucu seçin."), { type: "warning" });
            return;
        }
        this.act("return", { result: f.result, result_note: f.result_note, in_carrier: f.in_carrier,
                             in_tracking: f.in_tracking }, _t("İncelemeden geldi olarak işaretlendi."));
    }

    markDelivered() {
        this.act("deliver", {}, _t("Müşteriye teslim edildi."));
    }

    cancelClaim() {
        if (window.confirm(_t("Kayıt iptal edilecek. Emin misiniz?"))) {
            this.act("cancel", {}, _t("Kayıt iptal edildi."));
        }
    }

    addNote() {
        this.act("note", { note: this.state.note }, _t("Not eklendi."));
    }

    saveMobile() {
        this.act("mobile", { customer_mobile: this.state.mobile }, _t("Telefon kaydedildi."));
    }

    async onPhoto(ev) {
        const photos = [];
        for (const file of ev.target.files || []) {
            try {
                photos.push(await readPhoto(file));
            } catch {
                this.notification.add(_t("Fotoğraf okunamadı."), { type: "warning" });
            }
        }
        ev.target.value = "";
        if (photos.length) {
            await this.act("photo", { photos }, _t("Fotoğraf eklendi."));
        }
    }

    async sendSms() {
        // İdempotent olmayan iş: yanıt gelene kadar kilitli (çift dokunuşta iki SMS gitmesin, KK-B6)
        if (this.state.busy) return;
        this.state.busy = true;
        try {
            const res = await rpc("/vendor_claim/send_sms", { claim_id: this.state.detail.id });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                // Test modunda "SMS gönderildi" denmez (KK-B15): uyarı tipi
                this.notification.add(res.message, { type: res.sms?.state === "test" ? "warning" : "success" });
                await this.open(this.state.detail.id);
            }
        } catch (e) {
            this.notification.add(_t("SMS hatası: %(error)s", { error: e.message }), { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    print(report) {
        window.open(`/report/pdf/vendor_claim.${report}/${this.state.detail.id}`, "_blank");
    }

    openInBackend() {
        window.open(`/odoo/action-vendor_claim.action_vendor_claim/${this.state.detail.id}`, "_blank");
    }

    goBack() {
        if (this.state.detail) {
            this.closeDetail();
            return;
        }
        this.props.onNavigate("main_menu");
    }
}
