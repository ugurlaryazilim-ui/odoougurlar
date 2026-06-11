/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { printGiftLabelOnly } from "../label_print";

export class TailorGiftLabel extends Component {
    static template = "ugurlar_tailor.TailorGiftLabel";
    static props = {
        onNavigate: Function,
        scanner: Object,
    };

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            step: 1,        // 1=fatura ara, 2=ürün seç, 3=başarı
            searchQuery: "",
            searching: false,
            invoices: [],
            selectedInvoice: null,
            selectedItems: {},   // barcode -> { selected: bool, gift_note: string }
            printing: false,
        });

        this.searchInputRef = useRef("giftSearchInput");

        // Scanner subscription
        this._unsub = this.props.scanner.onScan(barcode => {
            if (this.state.step === 1) {
                this.state.searchQuery = barcode;
                this.searchInvoice();
            }
        });

        onMounted(() => {
            if (this.searchInputRef.el) {
                this.searchInputRef.el.focus();
            }
        });

        onWillUnmount(() => {
            if (this._unsub) this._unsub();
        });
    }

    async searchInvoice() {
        const q = this.state.searchQuery.trim();
        if (q.length < 3) {
            this.notification.add(_t("En az 3 karakter giriniz."), { type: "warning" });
            return;
        }
        this.state.searching = true;
        try {
            const invoices = await rpc("/ugurlar_tailor/search_invoice", { search_term: q });
            this.state.invoices = invoices || [];
            if (this.state.invoices.length === 1) {
                await this.selectInvoice(this.state.invoices[0].invoice_no);
            } else if (this.state.invoices.length === 0) {
                this.notification.add(_t("Fatura bulunamadı."), { type: "warning" });
            }
        } catch (e) {
            this.notification.add(_t("Arama hatası: %(error)s", { error: e.message }), { type: "danger" });
        }
        this.state.searching = false;
    }

    async selectInvoice(invoiceNo) {
        try {
            const detail = await rpc("/ugurlar_tailor/invoice_detail", { invoice_no: invoiceNo });
            if (detail) {
                this.state.selectedInvoice = detail;
                this.state.step = 2;
                const selections = {};
                (detail.items || []).forEach((item) => {
                    selections[item.barcode] = {
                        selected: false,
                        gift_note: "",
                    };
                });
                this.state.selectedItems = selections;
            }
        } catch (e) {
            this.notification.add(_t("Fatura detayı alınamadı: %(error)s", { error: e.message }), { type: "danger" });
        }
    }

    toggleItem(barcode) {
        this.state.selectedItems[barcode].selected = !this.state.selectedItems[barcode].selected;
    }

    onGiftNoteChange(barcode, ev) {
        this.state.selectedItems[barcode].gift_note = ev.target.value;
    }

    get selectedCount() {
        return Object.values(this.state.selectedItems).filter(s => s.selected).length;
    }

    async printGiftLabels() {
        const invoice = this.state.selectedInvoice;
        const selectedItems = [];

        for (const item of invoice.items || []) {
            const sel = this.state.selectedItems[item.barcode];
            if (sel && sel.selected) {
                selectedItems.push({
                    name: `HDY-${invoice.invoice_no}`,
                    invoice_no: invoice.invoice_no,
                    customer_name: invoice.customer_name || "",
                    customer_phone: invoice.customer_code || "",
                    sales_person: invoice.sales_person || "",
                    product_code: item.product_code || item.barcode,
                    product_name: item.product_code || item.barcode,
                    product_barcode: item.barcode,
                    tailor_name: "",
                    services: [],
                    notes: sel.gift_note || "",
                    date: new Date().toLocaleDateString('tr-TR', {
                        day: '2-digit', month: '2-digit', year: 'numeric',
                        hour: '2-digit', minute: '2-digit'
                    }),
                });
            }
        }

        if (selectedItems.length === 0) {
            this.notification.add(_t("En az bir ürün seçiniz!"), { type: "warning" });
            return;
        }

        this.state.printing = true;
        try {
            printGiftLabelOnly(selectedItems);
            this.notification.add(
                _t("%(count)s hediye etiketi yazdırılıyor...", { count: selectedItems.length }),
                { type: "success" }
            );
            this.state.step = 3;
        } catch (e) {
            this.notification.add(_t("Yazdırma hatası: %(error)s", { error: e.message }), { type: "danger" });
        }
        this.state.printing = false;
    }

    goBack() {
        if (this.state.step === 3) {
            this.state.step = 1;
            this.state.searchQuery = "";
            this.state.invoices = [];
            this.state.selectedInvoice = null;
        } else if (this.state.step === 2) {
            this.state.step = 1;
            this.state.selectedInvoice = null;
        } else {
            this.props.onNavigate("main_menu");
        }
    }

    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            this.searchInvoice();
        }
    }
}
