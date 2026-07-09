/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { printMultipleTailorLabels } from "../label_print";

export class TailorStoreItem extends Component {
    static template = "ugurlar_tailor.TailorStoreItem";
    static props = {
        onNavigate: Function,
        scanner: Object,
    };

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            step: 1,
            searchQuery: "",
            searching: false,
            items: [], // { barcode, product_code, product_name, tailor_id, service_ids, notes }
            services: [],
            tailors: [],
            submitting: false,
            createdCount: 0,
        });

        this.storeSearchInputRef = useRef("storeSearchInput");

        // Scanner subscription
        this._unsub = this.props.scanner.onScan(barcode => {
            if (this.state.step === 1) {
                this.state.searchQuery = barcode;
                this.searchProduct();
            }
        });

        onMounted(async () => {
            await this.loadServices();
            await this.loadTailors();
            if (this.storeSearchInputRef.el) {
                this.storeSearchInputRef.el.focus();
            }
        });

        onWillUnmount(() => {
            if (this._unsub) this._unsub();
        });
    }

    async loadServices() {
        try {
            this.state.services = await rpc("/ugurlar_tailor/services", {});
        } catch (e) {
            this.notification.add(_t("Hizmetler yuklenemedi: %(error)s", { error: e.message }), { type: "danger" });
        }
    }

    async loadTailors() {
        try {
            this.state.tailors = await rpc("/ugurlar_tailor/tailors", {});
        } catch (e) {
            this.notification.add(_t("Terziler yuklenemedi: %(error)s", { error: e.message }), { type: "danger" });
        }
    }

    async searchProduct() {
        const q = this.state.searchQuery.trim();
        if (q.length < 3) {
            this.notification.add(_t("En az 3 karakter giriniz."), { type: "warning" });
            return;
        }

        // Cift eklemeyi onle
        if (this.state.items.find(i => i.barcode === q)) {
            this.notification.add(_t("Bu urun zaten listeye eklendi."), { type: "warning" });
            this.state.searchQuery = "";
            return;
        }

        this.state.searching = true;
        try {
            const product = await rpc("/ugurlar_tailor/search_product", { barcode: q });
            if (product) {
                this.state.items.push({
                    barcode: product.barcode,
                    product_code: product.product_code,
                    product_name: product.product_name,
                    tailor_id: null,
                    service_ids: [],
                    notes: "",
                });
                this.state.searchQuery = "";
                if (this.storeSearchInputRef.el) {
                    this.storeSearchInputRef.el.focus();
                }
            } else {
                this.notification.add(_t("Urun bulunamadi."), { type: "warning" });
            }
        } catch (e) {
            this.notification.add(_t("Arama hatasi: %(error)s", { error: e.message }), { type: "danger" });
        }
        this.state.searching = false;
    }

    removeItem(barcode) {
        this.state.items = this.state.items.filter(i => i.barcode !== barcode);
    }

    onTailorChange(barcode, ev) {
        const tailorId = parseInt(ev.target.value) || null;
        const item = this.state.items.find(i => i.barcode === barcode);
        if (item) {
            item.tailor_id = tailorId;
            item.service_ids = [];
        }
    }

    onServiceToggle(barcode, serviceId) {
        const item = this.state.items.find(i => i.barcode === barcode);
        if (!item) return;
        const idx = item.service_ids.indexOf(serviceId);
        if (idx >= 0) {
            item.service_ids.splice(idx, 1);
        } else {
            item.service_ids.push(serviceId);
        }
    }

    onNotesChange(barcode, ev) {
        const item = this.state.items.find(i => i.barcode === barcode);
        if (item) {
            item.notes = ev.target.value;
        }
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

    getTailorServices(tailorId) {
        if (!tailorId) return [];
        const tailor = this.state.tailors.find((t) => t.id === tailorId);
        if (!tailor || !tailor.prices || tailor.prices.length === 0) return [];
        const serviceIds = tailor.prices.map((p) => p.service_id);
        return this.state.services.filter((s) => serviceIds.includes(s.id));
    }

    getItemTotal(barcode) {
        const item = this.state.items.find(i => i.barcode === barcode);
        if (!item) return 0;
        return item.service_ids.reduce((sum, sid) => {
            return sum + this.getServicePrice(sid, item.tailor_id);
        }, 0);
    }

    async submitOrders() {
        const orders = [];

        for (const item of this.state.items) {
            if (item.service_ids.length === 0) continue;
            if (!item.tailor_id) {
                this.notification.add(
                    _t("%(product)s icin terzi seciniz!", { product: item.product_name || item.barcode }),
                    { type: "warning" }
                );
                return;
            }

            const services = item.service_ids.map((sid) => ({
                id: sid,
                price: this.getServicePrice(sid, item.tailor_id),
            }));

            orders.push({
                invoice_no: "", // Reyon isleminde fatura yok
                barcode: item.barcode,
                product_code: item.product_code || item.barcode,
                product_name: item.product_name || item.barcode,
                customer_name: "MAĞAZA (REYON)",
                customer_phone: "",
                sales_person: "",
                tailor_id: item.tailor_id,
                notes: item.notes || "",
                services: services,
            });
        }

        if (orders.length === 0) {
            this.notification.add(_t("En az bir urun icin hizmet seciniz!"), { type: "warning" });
            return;
        }

        this.state.submitting = true;
        try {
            const result = await rpc("/ugurlar_tailor/create_order", { orders });
            if (result.success) {
                this.notification.add(
                    _t("%(count)s siparis basariyla olusturuldu!", { count: result.orders.length }),
                    { type: "success" }
                );
                
                const labelDataArray = [];
                for (const order of result.orders) {
                    try {
                        const data = await rpc("/ugurlar_tailor/label_data", { order_id: order.id });
                        if (data && !data.error) {
                            labelDataArray.push(data);
                        }
                    } catch (e) {
                        console.error("Etiket verisi alinamadi:", e);
                    }
                }
                if (labelDataArray.length > 0) {
                    printMultipleTailorLabels(labelDataArray);
                }
                
                this.state.createdCount = result.orders.length;
                this.state.step = 2;
            } else {
                this.notification.add(_t("Hata: %(error)s", { error: result.error || "" }), { type: "danger" });
            }
        } catch (e) {
            this.notification.add(_t("Siparis olusturma hatasi: %(error)s", { error: e.message }), { type: "danger" });
        }
        this.state.submitting = false;
    }

    goBack() {
        if (this.state.step === 2) {
            this.state.step = 1;
            this.state.searchQuery = "";
            this.state.items = [];
        } else {
            this.props.onNavigate("main_menu");
        }
    }

    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            this.searchProduct();
        }
    }

    scanCamera() {
        this.notification.add(_t("Kamera tarama reyon ekraninda yakinda aktif olacak."), { type: "info" });
    }
}
