/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";
import { readPhoto } from "@ugurlar_tailor/js/photo_utils";
import { notifySms } from "@vendor_claim/js/sms_notice";

/**
 * Yeni inceleme kaydı:
 *  1) fatura ara (yaz / okut) ya da "Faturasız"
 *  2) ürünleri seç (dokun / bırak ya da barkodunu okut); seçilen HER ürün için ayrı şikayet, talep, fotoğraf
 *  3) kaydedildi → tek müşteri fişi yazdır (ürün başına ayrı kayıt ve takip no; müşteriye tek SMS)
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
            // Seçilen ürünler: {key, item, defect, request, photos}.
            // key: faturada "inv:<satır sırası>", faturasızda "bc:<barkod>"
            sel: [],
            customerName: "",
            customerMobile: "",
            barcode: "",
            notes: "",
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
            this.state.sel = [];
            if (res.items.length === 1) {
                this.addSel("inv:0", res.items[0]); // tek ürünlü faturada ürün otomatik seçili
            }
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
        this.state.sel = [];
        this.state.step = 2;
    }

    // ── Ürün seçimi ──
    getSel(key) {
        return this.state.sel.find((e) => e.key === key);
    }

    addSel(key, item) {
        this.state.sel.push({ key, item: { ...item }, defect: "", request: "inspect", photos: [] });
    }

    /** Fatura ürün kartına dokunma: seç / bırak. */
    toggleItem(index) {
        const key = "inv:" + index;
        const found = this.getSel(key);
        if (found) {
            this.state.sel.splice(this.state.sel.indexOf(found), 1);
        } else {
            this.addSel(key, this.state.invoice.items[index]);
        }
    }

    /** Faturasız akış: okutulan ürünü listeden çıkar. */
    removeSel(entry) {
        this.state.sel.splice(this.state.sel.indexOf(entry), 1);
    }

    async selectByBarcode(code) {
        code = (code || this.state.barcode || "").trim();
        if (!code) return;
        this.state.barcode = "";
        if (this.state.invoice) {
            // Aynı barkod faturada birden çok satırsa henüz seçilmemiş ilk satır seçilir
            const rows = this.state.invoice.items.map((i, n) => (i.barcode === code ? n : -1)).filter((n) => n >= 0);
            if (!rows.length) {
                this.notification.add(_t("%(code)s bu faturada yok.", { code }), { type: "warning" });
                return;
            }
            const free = rows.find((n) => !this.getSel("inv:" + n));
            if (free === undefined) {
                this.notification.add(_t("%(code)s zaten seçili.", { code }), { type: "info" });
                return;
            }
            this.addSel("inv:" + free, this.state.invoice.items[free]);
            return;
        }
        try {
            const res = await rpc("/vendor_claim/product_lookup", { barcode: code });
            if (res.error) {
                this.notification.add(res.error, { type: "warning" });
                return;
            }
            const key = "bc:" + res.barcode;
            if (this.getSel(key)) {
                this.notification.add(_t("%(code)s zaten listede.", { code }), { type: "info" });
                return;
            }
            this.addSel(key, { ...res, quantity: 1 });
        } catch (e) {
            this.notification.add(_t("Ürün aranamadı: %(error)s", { error: e.message }), { type: "danger" });
        }
    }

    onBarcodeKey(ev) {
        if (ev.key === "Enter") {
            this.selectByBarcode();
        }
    }

    async onPhoto(entry, ev) {
        for (const file of ev.target.files || []) {
            if (entry.photos.length >= 8) {
                this.notification.add(_t("Ürün başına en fazla 8 fotoğraf eklenebilir."), { type: "warning" });
                break;
            }
            try {
                entry.photos.push(await readPhoto(file));
            } catch {
                this.notification.add(_t("Fotoğraf okunamadı."), { type: "warning" });
            }
        }
        ev.target.value = "";
    }

    removePhoto(entry, idx) {
        entry.photos.splice(idx, 1);
    }

    async submit() {
        const s = this.state;
        if (!s.sel.length) {
            this.notification.add(_t("En az bir ürün seçin veya barkodunu okutun."), { type: "warning" });
            return;
        }
        if (!s.customerName.trim()) {
            this.notification.add(_t("Müşteri adını girin."), { type: "warning" });
            return;
        }
        const missing = s.sel.find((e) => !e.defect.trim());
        if (missing) {
            const product = missing.item.product_name || missing.item.product_code || missing.item.barcode;
            this.notification.add(_t("%(product)s için ayıp / şikayet açıklamasını yazın.", { product }), {
                type: "warning",
            });
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
                    notes: s.notes,
                },
                items: s.sel.map((e) => ({
                    product_barcode: e.item.barcode,
                    product_code: e.item.product_code,
                    quantity: e.item.quantity,
                    defect_description: e.defect,
                    customer_request: e.request,
                    photos: e.photos,
                })),
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                s.created = res;
                s.step = 3;
                const n = (res.claims || []).length;
                this.notification.add(
                    n > 1 ? _t("%(n)s kayıt kaydedildi.", { n }) : _t("%(name)s kaydedildi.", { name: res.name }),
                    { type: "success" }
                );
                notifySms(this.notification, res.sms);
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

    openCreated(claimId) {
        this.props.onNavigate("claim_list", { openId: claimId || this.state.created.id });
    }

    restart() {
        Object.assign(this.state, {
            step: 1,
            query: "",
            invoices: [],
            invoice: null,
            noInvoice: false,
            sel: [],
            customerName: "",
            customerMobile: "",
            barcode: "",
            notes: "",
            created: null,
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
