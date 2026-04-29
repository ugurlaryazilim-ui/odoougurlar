/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { printTailorLabel, printMultipleTailorLabels } from "../label_print";

export class TailorNewOrder extends Component {
    static template = "ugurlar_tailor.TailorNewOrder";
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
            invoices: [],
            selectedInvoice: null,
            services: [],
            tailors: [],
            itemSelections: {},
            submitting: false,
        });

        this.searchInputRef = useRef("searchInput");

        // Scanner subscription (el terminali / keyboard wedge)
        this._unsub = this.props.scanner.onScan(barcode => {
            if (this.state.step === 1) {
                this.state.searchQuery = barcode;
                this.searchInvoice();
            }
        });

        onMounted(async () => {
            await this.loadServices();
            await this.loadTailors();
            if (this.searchInputRef.el) {
                this.searchInputRef.el.focus();
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
                // Tum siparislerin etiket verisini topla, tek seferde yazdir
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
                setTimeout(() => this.props.onNavigate("main_menu"), 3000);
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

    scanCamera() {
        const overlay = document.createElement('div');
        overlay.className = 'tailor-camera-overlay';
        overlay.innerHTML = `
            <div class="tailor-camera-controls">
                <button class="tailor-camera-close">&times;</button>
                <div id="tailor-camera-reader" style="width:100%"></div>
                <div class="tailor-camera-status">Fatura barkodunu kameraya gösterin...</div>
            </div>
        `;
        document.body.appendChild(overlay);
        overlay.querySelector('.tailor-camera-close').onclick = () => { overlay.remove(); };

        const readerEl = overlay.querySelector('#tailor-camera-reader');
        const statusEl = overlay.querySelector('.tailor-camera-status');

        const onDetected = (code) => {
            this.state.searchQuery = code;
            this.searchInvoice();
        };

        // iOS Safari'de BarcodeDetector YOK — doğrudan Html5Qrcode kullan
        // Android Chrome'da BarcodeDetector VAR — onu dene, hata olursa fallback
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
                statusEl.textContent = 'Kamera erişim hatası';
            });
        } else {
            // Html5Qrcode — iOS + tüm tarayıcılarda çalışır
            this._startHtml5QrScanner(readerEl, statusEl, overlay, onDetected);
        }
    }

    async _startHtml5QrScanner(readerEl, statusEl, overlay, onDetected) {
        try {
            if (!window.Html5Qrcode) {
                statusEl.textContent = 'Tarayıcı yükleniyor...';
                const s = document.createElement('script');
                s.src = 'https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js';
                document.head.appendChild(s);
                await new Promise((resolve, reject) => {
                    s.onload = resolve;
                    s.onerror = () => reject(new Error('CDN yüklenemedi'));
                    setTimeout(() => reject(new Error('Zaman aşımı')), 10000);
                });
            }

            // Kamera listesini al
            let cameraId = null;
            try {
                const cameras = await Html5Qrcode.getCameras();
                if (cameras && cameras.length > 0) {
                    // Arka kamerayı tercih et
                    const backCam = cameras.find(c =>
                        /back|rear|environment/i.test(c.label)
                    );
                    cameraId = backCam ? backCam.id : cameras[cameras.length - 1].id;
                }
            } catch (e) {
                // getCameras başarısız olursa facingMode ile devam et
            }

            const scanner = new Html5Qrcode('tailor-camera-reader');
            const config = { fps: 10, qrbox: { width: 250, height: 150 } };
            const successCb = (code) => {
                scanner.stop().catch(() => {});
                overlay.remove();
                onDetected(code);
            };

            if (cameraId) {
                await scanner.start(cameraId, config, successCb, () => {});
            } else {
                await scanner.start(
                    { facingMode: 'environment' },
                    config,
                    successCb,
                    () => {}
                );
            }

            overlay.querySelector('.tailor-camera-close').onclick = () => {
                scanner.stop().catch(() => {});
                overlay.remove();
            };
        } catch (e) {
            console.error('Html5Qrcode hatası:', e);
            statusEl.textContent = 'Kamera başlatılamadı. Lütfen kamera izni verin ve tekrar deneyin.';
        }
    }
}
