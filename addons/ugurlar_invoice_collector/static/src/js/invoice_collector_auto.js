/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { onMounted, onPatched } from "@odoo/owl";

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);

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
                    
                    if (this._autoDownloadTimer) {
                        clearTimeout(this._autoDownloadTimer);
                    }
                    this._autoDownloadTimer = setTimeout(() => {
                        const btn = document.querySelector("button[name='action_download_zip']");
                        if (btn) {
                            btn.click();
                        }
                    }, 400);
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
