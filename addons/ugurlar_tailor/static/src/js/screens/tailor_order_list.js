/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class TailorOrderList extends Component {
    static template = "ugurlar_tailor.TailorOrderList";
    static props = {
        onNavigate: Function,
    };

    setup() {
        this.notification = useService("notification");
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
            this.notification.add("Siparisler yuklenemedi: " + e.message, { type: "danger" });
        }
        this.state.loading = false;
    }

    async updateStatus(orderId, newStatus) {
        try {
            const result = await rpc("/ugurlar_tailor/update_status", {
                order_id: orderId,
                status: newStatus,
            });
            if (result.success) {
                this.notification.add("Durum guncellendi!", { type: "success" });
                await this.loadOrders();
            }
        } catch (e) {
            this.notification.add("Durum guncelleme hatasi: " + e.message, { type: "danger" });
        }
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
            pending: "Bekliyor",
            in_progress: "Terzide",
            completed: "Hazir",
            delivered: "Teslim",
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

    printLabel(orderId) {
        const url = `/report/pdf/ugurlar_tailor.report_tailor_label/${orderId}`;
        window.open(url, "_blank");
    }
}
