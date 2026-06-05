/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
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

    // ── Kamera Barkod Tarayici ──
    scanCamera() {
        const overlay = document.createElement('div');
        overlay.className = 'tailor-camera-overlay';
        overlay.innerHTML = `
            <div class="tailor-camera-controls">
                <button class="tailor-camera-close">&times;</button>
                <div id="tailor-camera-reader-list" style="width:100%"></div>
                <div class="tailor-camera-status">Fatura barkodunu kameraya gösterin...</div>
            </div>
        `;
        document.body.appendChild(overlay);
        overlay.querySelector('.tailor-camera-close').onclick = () => { overlay.remove(); };

        const readerEl = overlay.querySelector('#tailor-camera-reader-list');
        const statusEl = overlay.querySelector('.tailor-camera-status');

        const onDetected = (code) => {
            this.state.search = code;
            this.state.page = 1;
            this.loadOrders();
        };

        const useBarcodeDetector = ('BarcodeDetector' in window) && !/iPhone|iPad|iPod/i.test(navigator.userAgent);

        if (useBarcodeDetector) {
            navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment' }
            }).then(async (stream) => {
                const video = document.createElement('video');
                video.srcObject = stream;
                video.setAttribute('playsinline', 'true');
                video.setAttribute('autoplay', 'true');
                video.muted = true;
                video.style.width = '100%';
                video.style.borderRadius = '8px';
                readerEl.appendChild(video);
                await video.play();

                const detector = new BarcodeDetector({ formats: ['ean_13', 'ean_8', 'code_128', 'code_39', 'qr_code'] });
                const scan = async () => {
                    if (!document.body.contains(overlay)) {
                        stream.getTracks().forEach(t => t.stop());
                        return;
                    }
                    try {
                        const barcodes = await detector.detect(video);
                        if (barcodes.length > 0) {
                            stream.getTracks().forEach(t => t.stop());
                            overlay.remove();
                            onDetected(barcodes[0].rawValue);
                            return;
                        }
                    } catch (e) {}
                    requestAnimationFrame(scan);
                };
                scan();
            }).catch(() => {
                statusEl.textContent = _t('Kamera erisim hatasi');
            });
        } else {
            this._startHtml5QrScanner(readerEl, statusEl, overlay, onDetected);
        }
    }

    async _startHtml5QrScanner(readerEl, statusEl, overlay, onDetected) {
        try {
            if (!window.Html5Qrcode) {
                statusEl.textContent = _t('Tarayici yukleniyor...');
                const s = document.createElement('script');
                s.src = 'https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js';
                document.head.appendChild(s);
                await new Promise((resolve, reject) => {
                    s.onload = resolve;
                    s.onerror = () => reject(new Error(_t('CDN yuklenemedi')));
                    setTimeout(() => reject(new Error(_t('Zaman asimi'))), 10000);
                });
            }

            statusEl.textContent = _t('Kamera baslatiliyor...');

            const scanner = new Html5Qrcode('tailor-camera-reader-list');
            const config = { fps: 10, qrbox: { width: 250, height: 150 }, aspectRatio: 1.0 };
            const successCb = (code) => {
                scanner.stop().catch(() => {});
                overlay.remove();
                onDetected(code);
            };

            await scanner.start(
                { facingMode: 'environment' },
                config,
                successCb,
                () => {}
            );

            overlay.querySelector('.tailor-camera-close').onclick = () => {
                scanner.stop().catch(() => {});
                overlay.remove();
            };
        } catch (e) {
            console.error('Html5Qrcode hatası:', e);
            statusEl.textContent = _t('Kamera baslatilamadi: %(error)s', { error: e.message || e });
        }
    }
}
