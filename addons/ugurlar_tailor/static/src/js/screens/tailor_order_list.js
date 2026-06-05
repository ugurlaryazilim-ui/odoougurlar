/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { printTailorLabel } from "../label_print";

export class TailorOrderList extends Component {
    static template = "ugurlar_tailor.TailorOrderList";
    static props = {
        onNavigate: Function,
        scanner: { type: Object, optional: true },
    };

    setup() {
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.state = useState({
            orders: [],
            total: 0,
            page: 1,
            limit: 20,
            search: "",
            statusFilter: "",
            loading: false,
        });

        onMounted(() => this.loadOrders());
    }

    async loadOrders() {
        this.state.loading = true;
        try {
            const result = await rpc("/ugurlar_tailor/orders", {
                status: this.state.statusFilter || false,
                search: this.state.search,
                page: this.state.page,
                limit: this.state.limit,
            });
            this.state.orders = result.orders || [];
            this.state.total = result.total || 0;
        } catch (e) {
            this.notification.add(_t("Siparisler yuklenemedi: %(error)s", { error: e.message }), { type: "danger" });
        }
        this.state.loading = false;
    }

    async updateStatus(orderId, newStatus) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Durum Degisikligi"),
            body: _t("Siparisi '%(status)s' durumuna gecirmek istediginize emin misiniz?", { status: this.getStatusLabel(newStatus) }),
            confirm: async () => {
                try {
                    const result = await rpc("/ugurlar_tailor/update_status", {
                        order_id: orderId,
                        status: newStatus,
                    });
                    if (result.success) {
                        this.notification.add(_t("Durum guncellendi!"), { type: "success" });
                        await this.loadOrders();
                    }
                } catch (e) {
                    this.notification.add(_t("Durum guncelleme hatasi: %(error)s", { error: e.message }), { type: "danger" });
                }
            },
            cancel: () => {},
        });
    }

    getNextStatus(currentStatus) {
        const flow = {
            pending: "in_progress",
            in_progress: "completed",
            completed: "delivered",
        };
        return flow[currentStatus] || null;
    }

    getStatusLabel(status) {
        const labels = {
            pending: _t("Bekliyor"),
            in_progress: _t("Terzide"),
            completed: _t("Hazir"),
            delivered: _t("Teslim"),
        };
        return labels[status] || status;
    }

    getStatusClass(status) {
        const classes = {
            pending: "badge-pending",
            in_progress: "badge-in-progress",
            completed: "badge-completed",
            delivered: "badge-delivered",
        };
        return classes[status] || "";
    }

    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            this.state.page = 1;
            this.loadOrders();
        }
    }

    onFilterChange(ev) {
        this.state.statusFilter = ev.target.value;
        this.state.page = 1;
        this.loadOrders();
    }

    prevPage() {
        if (this.state.page > 1) {
            this.state.page--;
            this.loadOrders();
        }
    }

    nextPage() {
        const maxPage = Math.ceil(this.state.total / this.state.limit);
        if (this.state.page < maxPage) {
            this.state.page++;
            this.loadOrders();
        }
    }

    get totalPages() {
        return Math.ceil(this.state.total / this.state.limit) || 1;
    }

    goBack() {
        this.props.onNavigate("main_menu");
    }

    async printLabel(orderId) {
        try {
            const data = await rpc("/ugurlar_tailor/label_data", { order_id: orderId });
            if (data.error) {
                this.notification.add(data.error, { type: "danger" });
                return;
            }
            printTailorLabel(data);
        } catch (e) {
            this.notification.add(_t("Etiket verisi alinamadi: %(error)s", { error: e.message }), { type: "danger" });
        }
    }
}
