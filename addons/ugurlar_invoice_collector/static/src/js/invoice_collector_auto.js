/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onPatched } from "@odoo/owl";

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        this.notification = useService("notification");

        const checkAutoDownload = () => {
            if (this.props.resModel === "ugurlar.invoice.collector") {
                const record = this.model.root;
                if (record && record.data && record.data.state === "downloading") {
                    // Bekleyen fatura sayısını kontrol et
                    // processed_count ve total_found_invoices üzerinden
                    const processed = record.data.processed_count || 0;
                    const total = record.data.total_found_invoices || 0;
                    const pendingCount = record.data.pending_count || 0;
                    
                    // Eğer hâlâ bekleyen fatura varsa otomatik tetikle
                    // pending_count alanı yoksa progress_text'ten anla
                    const progressText = record.data.progress_text || '';
                    const hasPending = pendingCount > 0 || 
                                       (total > 0 && processed < total) ||
                                       progressText.includes('Bekleyen');
                    
                    if (!hasPending) {
                        // Bekleyen fatura yok — otomatik tetikleme yapma
                        return;
                    }
                    
                    // NEDEN: iş cron'da işleniyorsa sunucu adımı atlayıp formu aynen döndürür; ilerleme
                    // olmadan 400 ms'de bir yeniden basmak sunucuyu boşuna yorar (A4 Ö-3). İlerleme
                    // yoksa bekleme süresi katlanır (5 sn → 30 sn), ilerleme görülünce 400 ms'ye döner.
                    if (this._autoLastProcessed === processed) {
                        this._autoDelay = Math.min((this._autoDelay || 2500) * 2, 30000);
                        if (!this._autoBusyNotified) {
                            this._autoBusyNotified = true;
                            this.notification.add(
                                "Faturalar arka planda işleniyor; ekran kendiliğinden güncellenecek.",
                                { type: "info" }
                            );
                        }
                    } else {
                        this._autoDelay = 400;
                        this._autoBusyNotified = false;
                    }
                    this._autoLastProcessed = processed;

                    if (this._autoDownloadTimer) {
                        clearTimeout(this._autoDownloadTimer);
                    }
                    this._autoDownloadTimer = setTimeout(() => {
                        const btn = document.querySelector("button[name='action_download_zip']");
                        if (btn) {
                            btn.click();
                        }
                    }, this._autoDelay);
                }
            }
        };

        onMounted(() => {
            checkAutoDownload();
        });

        onPatched(() => {
            checkAutoDownload();
        });
    }
});
