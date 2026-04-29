/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class TailorNewOrder extends Component {
    static template = "ugurlar_tailor.TailorNewOrder";
    static props = {
        onNavigate: Function,
    };

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            step: 1,
            searchQuery: "",
            searching: false,
            invoices: [],
            selectedInvoice: null,
            services: [],
            tailors: [],
            itemSelections: {},
            submitting: false,
        });

        onMounted(async () => {
            await this.loadServices();
            await this.loadTailors();
        });
    }

    async loadServices() {
        try {
            this.state.services = await rpc("/ugurlar_tailor/services", {});
        } catch (e) {
            this.notification.add("Hizmetler yuklenemedi: " + e.message, { type: "danger" });
        }
    }

    async loadTailors() {
        try {
            this.state.tailors = await rpc("/ugurlar_tailor/tailors", {});
        } catch (e) {
            this.notification.add("Terziler yuklenemedi: " + e.message, { type: "danger" });
        }
    }

    async searchInvoice() {
        const q = this.state.searchQuery.trim();
        if (q.length < 3) {
            this.notification.add("En az 3 karakter giriniz.", { type: "warning" });
            return;
        }
        this.state.searching = true;
        try {
            const invoices = await rpc("/ugurlar_tailor/search_invoice", { search_term: q });
            this.state.invoices = invoices || [];
            if (this.state.invoices.length === 1) {
                await this.selectInvoice(this.state.invoices[0].invoice_no);
            } else if (this.state.invoices.length === 0) {
                this.notification.add("Fatura bulunamadi.", { type: "warning" });
            }
        } catch (e) {
            this.notification.add("Arama hatasi: " + e.message, { type: "danger" });
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
                        tailor_id: null,
                        service_ids: [],
                        notes: "",
                    };
                });
                this.state.itemSelections = selections;
            }
        } catch (e) {
            this.notification.add("Fatura detayi alinamadi: " + e.message, { type: "danger" });
        }
    }

    onTailorChange(barcode, ev) {
        const tailorId = parseInt(ev.target.value) || null;
        this.state.itemSelections[barcode].tailor_id = tailorId;
    }

    onServiceToggle(barcode, serviceId) {
        const sel = this.state.itemSelections[barcode];
        const idx = sel.service_ids.indexOf(serviceId);
        if (idx >= 0) {
            sel.service_ids.splice(idx, 1);
        } else {
            sel.service_ids.push(serviceId);
        }
    }

    onNotesChange(barcode, ev) {
        this.state.itemSelections[barcode].notes = ev.target.value;
    }

    getServicePrice(serviceId, tailorId) {
        if (tailorId) {
            const tailor = this.state.tailors.find((t) => t.id === tailorId);
            if (tailor && tailor.prices) {
                const tp = tailor.prices.find((p) => p.service_id === serviceId);
                if (tp) return tp.price;
            }
        }
        const svc = this.state.services.find((s) => s.id === serviceId);
        return svc ? svc.price : 0;
    }

    getItemTotal(barcode) {
        const sel = this.state.itemSelections[barcode];
        if (!sel) return 0;
        return sel.service_ids.reduce((sum, sid) => {
            return sum + this.getServicePrice(sid, sel.tailor_id);
        }, 0);
    }

    async submitOrders() {
        const invoice = this.state.selectedInvoice;
        const orders = [];

        for (const item of invoice.items || []) {
            const sel = this.state.itemSelections[item.barcode];
            if (!sel || sel.service_ids.length === 0) continue;
            if (!sel.tailor_id) {
                this.notification.add(
                    (item.product_code || item.barcode) + " icin terzi seciniz!",
                    { type: "warning" }
                );
                return;
            }

            const services = sel.service_ids.map((sid) => ({
                id: sid,
                price: this.getServicePrice(sid, sel.tailor_id),
            }));

            orders.push({
                invoice_no: invoice.invoice_no,
                barcode: item.barcode,
                product_code: item.product_code || item.barcode,
                product_name: item.product_code || item.barcode,
                customer_name: invoice.customer_name || "",
                customer_phone: invoice.customer_code || "",
                sales_person: invoice.sales_person || "",
                tailor_id: sel.tailor_id,
                notes: sel.notes || "",
                services: services,
            });
        }

        if (orders.length === 0) {
            this.notification.add("En az bir urun icin hizmet seciniz!", { type: "warning" });
            return;
        }

        this.state.submitting = true;
        try {
            const result = await rpc("/ugurlar_tailor/create_order", { orders });
            if (result.success) {
                this.notification.add(
                    result.orders.length + " siparis basariyla olusturuldu!",
                    { type: "success" }
                );
                setTimeout(() => this.props.onNavigate("main_menu"), 2000);
            } else {
                this.notification.add("Hata: " + (result.error || ""), { type: "danger" });
            }
        } catch (e) {
            this.notification.add("Siparis olusturma hatasi: " + e.message, { type: "danger" });
        }
        this.state.submitting = false;
    }

    goBack() {
        if (this.state.step === 2) {
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
