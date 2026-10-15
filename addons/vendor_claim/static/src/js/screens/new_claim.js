/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";
import { readPhoto } from "@ugurlar_tailor/js/photo_utils";

/**
 * Yeni inceleme kaydı:
 *  1) fatura ara (yaz / okut) ya da "Faturasız"
 *  2) ürünü seç (dokun ya da ürün barkodunu okut), şikayet + fotoğraf
 *  3) kaydedildi → müşteri fişi yazdır
 */
export class VcNewClaim extends Component {
    static template = "vendor_claim.VcNewClaim";
    static props = { onNavigate: Function, scanner: Object };

    requestOptions = [
        ["inspect", _t("Sadece İnceleme")],
        ["repair", _t("Tamir")],
        ["replace", _t("Değişim")],
        ["refund", _t("Para İadesi")],
    ];

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            step: 1,
            query: "",
            searching: false,
            invoices: [],
            invoice: null,
            noInvoice: false,
            item: null,
            customerName: "",
            customerMobile: "",
            barcode: "",
            defect: "",
            request: "inspect",
            notes: "",
            photos: [],
            submitting: false,
            created: null,
        });
        this.searchRef = useRef("searchInput");
        this._unsub = this.props.scanner.onScan((code) => this.onScan(code));
        onMounted(() => this.searchRef.el?.focus());
        onWillUnmount(() => this._unsub && this._unsub());
    }

    // ── Okutma: 1. adımda fatura, 2. adımda ürün barkodu ──
    onScan(code) {
        if (this.state.step === 1 && !this.state.noInvoice) {
            this.state.query = code;
            return this.searchInvoice();
        }
        if (this.state.step === 2) {
            return this.selectByBarcode(code);
        }
    }

    scanCamera() {
        const header = this.state.step === 1 ? _t("Fatura Barkodu Okut") : _t("Ürün Barkodu Okut");
        openCameraScanner((code) => this.onScan(code), { headerText: header });
    }

    async searchInvoice() {
        const q = (this.state.query || "").trim();
        if (q.length < 3) {
            this.notification.add(_t("En az 3 karakter giriniz."), { type: "warning" });
            return;
        }
        this.state.searching = true;
        try {
            const res = await rpc("/vendor_claim/search_invoice", { search_term: q });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.state.invoices = res.invoices || [];
                if (this.state.invoices.length === 1) {
                    await this.selectInvoice(this.state.invoices[0].invoice_no);
                } else if (!this.state.invoices.length) {
                    this.notification.add(_t("Fatura bulunamadı."), { type: "warning" });
                }
            }
        } catch (e) {
            this.notification.add(_t("Arama hatası: %(error)s", { error: e.message }), { type: "danger" });
        }
        this.state.searching = false;
    }

    async selectInvoice(invoiceNo) {
        try {
            const res = await rpc("/vendor_claim/invoice_detail", { invoice_no: invoiceNo });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
                return;
            }
            this.state.invoice = res;
            this.state.customerName = res.customer_name || "";
            this.state.customerMobile = res.customer_mobile || this.state.customerMobile;
            this.state.item = res.items.length === 1 ? res.items[0] : null;
            this.state.step = 2;
            if (res.existing && res.existing.length) {
                this.notification.add(
                    _t("Bu faturaya ait %(n)s inceleme kaydı zaten var.", { n: res.existing.length }),
                    { type: "warning" }
                );
            }
        } catch (e) {
            this.notification.add(_t("Fatura detayı alınamadı: %(error)s", { error: e.message }), { type: "danger" });
        }
    }

    startNoInvoice() {
        this.state.noInvoice = true;
        this.state.invoice = null;
        this.state.item = null;
        this.state.step = 2;
    }

    selectItem(item) {
        this.state.item = item;
    }

    async selectByBarcode(code) {
        code = (code || this.state.barcode || "").trim();
        if (!code) return;
        this.state.barcode = "";
        if (this.state.invoice) {
            const item = this.state.invoice.items.find((i) => i.barcode === code);
            if (item) {
                this.state.item = item;
                return;
            }
            this.notification.add(_t("%(code)s bu faturada yok.", { code }), { type: "warning" });
            return;
        }
        try {
            const res = await rpc("/vendor_claim/product_lookup", { barcode: code });
            if (res.error) {
                this.notification.add(res.error, { type: "warning" });
                return;
            }
            this.state.item = { ...res, quantity: 1 };
        } catch (e) {
            this.notification.add(_t("Ürün aranamadı: %(error)s", { error: e.message }), { type: "danger" });
        }
    }

    onBarcodeKey(ev) {
        if (ev.key === "Enter") {
            this.selectByBarcode();
        }
    }

    async onPhoto(ev) {
        for (const file of ev.target.files || []) {
            if (this.state.photos.length >= 8) {
                this.notification.add(_t("En fazla 8 fotoğraf eklenebilir."), { type: "warning" });
                break;
            }
            try {
                this.state.photos.push(await readPhoto(file));
            } catch {
                this.notification.add(_t("Fotoğraf okunamadı."), { type: "warning" });
            }
        }
        ev.target.value = "";
    }

    removePhoto(idx) {
        this.state.photos.splice(idx, 1);
    }

    async submit() {
        const s = this.state;
        if (!s.item) {
            this.notification.add(_t("Ürünü seçin veya barkodunu okutun."), { type: "warning" });
            return;
        }
        if (!s.customerName.trim()) {
            this.notification.add(_t("Müşteri adını girin."), { type: "warning" });
            return;
        }
        if (!s.defect.trim()) {
            this.notification.add(_t("Ayıp / şikayet açıklamasını yazın."), { type: "warning" });
            return;
        }
        s.submitting = true;
        const inv = s.invoice || {};
        try {
            const res = await rpc("/vendor_claim/create", {
                data: {
                    no_invoice: s.noInvoice,
                    invoice_no: inv.invoice_no,
                    invoice_date: inv.invoice_date,
                    invoice_items: inv.items,
                    customer_code: inv.customer_code,
                    sales_person: inv.sales_person,
                    customer_name: s.customerName,
                    customer_mobile: s.customerMobile,
                    product_barcode: s.item.barcode,
                    product_code: s.item.product_code,
                    quantity: s.item.quantity,
                    defect_description: s.defect,
                    customer_request: s.request,
                    notes: s.notes,
                },
                photos: s.photos,
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                s.created = res;
                s.step = 3;
                this.notification.add(_t("%(name)s kaydedildi.", { name: res.name }), { type: "success" });
            }
        } catch (e) {
            this.notification.add(_t("Kayıt hatası: %(error)s", { error: e.message }), { type: "danger" });
        }
        s.submitting = false;
    }

    printSlip() {
        if (this.state.created) {
            window.open(this.state.created.slip_url, "_blank");
        }
    }

    openCreated() {
        this.props.onNavigate("claim_list", { openId: this.state.created.id });
    }

    restart() {
        Object.assign(this.state, {
            step: 1, query: "", invoices: [], invoice: null, noInvoice: false, item: null, customerName: "",
            customerMobile: "", barcode: "", defect: "", request: "inspect", notes: "", photos: [], created: null,
        });
    }

    goBack() {
        if (this.state.step === 2) {
            this.state.step = 1;
            this.state.noInvoice = false;
            return;
        }
        this.props.onNavigate("main_menu");
    }
}
