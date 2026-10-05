/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { printTailorLabel } from "../label_print";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";

export class TailorOrderList extends Component {
    static template = "ugurlar_tailor.TailorOrderList";
    static props = {
        onNavigate: Function,
        scanner: { type: Object, optional: true },
        initialStatus: { type: String, optional: true },
    };

    statusOptions = [
        ["", _t("Tümü")],
        ["overdue", _t("⚠ Geciken")],
        ["waiting_approval", _t("Onay Bekleyen")],
        ["pending", _t("Bekliyor")],
        ["in_progress", _t("Terzide")],
        ["completed", _t("Hazır")],
        ["delivered", _t("Teslim")],
        ["cancelled", _t("İptal")],
    ];

    setup() {
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.state = useState({
            orders: [],
            total: 0,
            page: 1,
            limit: 20,
            search: "",
            statusFilter: this.props.initialStatus || "",
            loading: false,
        });

        // Hardware barcode scanner subscription
        if (this.props.scanner) {
            this._unsub = this.props.scanner.onScan(barcode => {
                this.state.search = barcode;
                this.state.page = 1;
                this.loadOrders();
            });
        }

        onMounted(() => this.loadOrders());

        onWillUnmount(() => {
            if (this._unsub) this._unsub();
        });
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
            this.notification.add(_t("Siparişler yüklenemedi: %(error)s", { error: e.message }), { type: "danger" });
        }
        this.state.loading = false;
    }

    async updateStatus(orderId, newStatus) {
        if (newStatus === "completed") {
            // Hazır ürünün mağazadaki yeri (raf/askı); boş bırakılabilir
            const location = window.prompt(_t("Raf / askı konumu (boş bırakılabilir):"), "");
            if (location === null) return;
            await this._doUpdate(orderId, newStatus, location);
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Durum Değişikliği"),
            body: _t("Siparişi '%(status)s' durumuna geçirmek istediğinize emin misiniz?", { status: this.getStatusLabel(newStatus) }),
            confirm: async () => {
                try {
                    const result = await rpc("/ugurlar_tailor/update_status", {
                        order_id: orderId,
                        status: newStatus,
                    });
                    if (result.success) {
                        this.notification.add(_t("Durum güncellendi!"), { type: "success" });
                        await this.loadOrders();
                    } else {
                        this.notification.add(result.error || _t("Durum güncellenemedi."), { type: "danger" });
                    }
                } catch (e) {
                    this.notification.add(_t("Durum güncelleme hatası: %(error)s", { error: e.message }), { type: "danger" });
                }
            },
            cancel: () => {},
        });
    }

    async _doUpdate(orderId, newStatus, location = null) {
        try {
            const result = await rpc("/ugurlar_tailor/update_status", { order_id: orderId, status: newStatus, location });
            if (result.success) {
                this.notification.add(_t("Durum güncellendi!"), { type: "success" });
                await this.loadOrders();
            } else {
                this.notification.add(result.error || _t("Durum güncellenemedi."), { type: "danger" });
            }
        } catch (e) {
            this.notification.add(_t("Durum güncelleme hatası: %(error)s", { error: e.message }), { type: "danger" });
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

    formatDate(value) {
        if (!value) return "";
        const [y, m, d] = String(value).slice(0, 10).split("-");
        return `${d}.${m}.${y}`;
    }

    getStatusLabel(status) {
        const labels = {
            waiting_approval: _t("Onay Bekliyor"),
            pending: _t("Bekliyor"),
            in_progress: _t("Terzide"),
            completed: _t("Hazır"),
            delivered: _t("Teslim"),
            cancelled: _t("İptal"),
        };
        return labels[status] || status;
    }

    getStatusClass(status) {
        const classes = {
            waiting_approval: "badge-waiting",
            pending: "badge-pending",
            in_progress: "badge-in-progress",
            completed: "badge-completed",
            delivered: "badge-delivered",
            cancelled: "badge-cancelled",
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

    async sendSms(order, number = "") {
        try {
            const res = await rpc("/ugurlar_tailor/send_sms", { order_id: order.id, number });
            if (res.success) {
                this.notification.add(
                    res.state === "test" ? _t("SMS test modunda kaydedildi (gönderilmedi).") : _t("SMS gönderildi."),
                    { type: "success" });
                return;
            }
            if (res.need_number) {
                const entered = window.prompt(_t("Müşteri cep telefonu (05xx xxx xx xx):"), "");
                if (entered) {
                    await this.sendSms(order, entered);
                }
                return;
            }
            this.notification.add(res.error || _t("SMS gönderilemedi."), { type: "danger" });
        } catch (e) {
            this.notification.add(_t("SMS hatası: %(error)s", { error: e.message }), { type: "danger" });
        }
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
            this.notification.add(_t("Etiket verisi alınamadı: %(error)s", { error: e.message }), { type: "danger" });
        }
    }

    // ── Kamera Barkod Tarayici ──
    scanCamera() {
        openCameraScanner((barcode) => {
            this.state.search = barcode;
            this.state.page = 1;
            this.loadOrders();
        }, { headerText: 'Fatura Barkodu Okut' });
    }

    async cancelOrder(orderId) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Sipariş İptali"),
            body: _t("Bu siparişi iptal etmek istediğinize emin misiniz?"),
            confirm: async () => {
                try {
                    const result = await rpc("/ugurlar_tailor/update_status", {
                        order_id: orderId,
                        status: "cancelled",
                    });
                    if (result.success) {
                        this.notification.add(_t("Sipariş iptal edildi!"), { type: "warning" });
                        await this.loadOrders();
                    } else {
                        this.notification.add(result.error || _t("Sipariş iptal edilemedi."), { type: "danger" });
                    }
                } catch (e) {
                    this.notification.add(_t("İptal hatası: %(error)s", { error: e.message }), { type: "danger" });
                }
            },
            cancel: () => {},
        });
    }
}
