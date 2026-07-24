/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";

/**
 * Fatura Arşiv Sihirbazı — Zero-Click Auto Streaming
 * 
 * State="downloading" olduğunda action_download_zip butonunu otomatik tıklar.
 * Çoklu tetikleme koruması: _isProcessing kilidi ile eşzamanlı çalışmayı engeller.
 */
patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);

        this._invoiceCollectorProcessing = false;
        this._autoDownloadTimer = null;

        const checkAutoDownload = () => {
            if (this.props.resModel !== "ugurlar.invoice.collector") {
                return;
            }

            const record = this.model.root;
            if (!record || !record.data || record.data.state !== "downloading") {
                this._invoiceCollectorProcessing = false;
                return;
            }

            // Zaten çalışıyorsa tekrar tetikleme (çoklu tetikleme koruması)
            if (this._invoiceCollectorProcessing) {
                return;
            }

            if (this._autoDownloadTimer) {
                clearTimeout(this._autoDownloadTimer);
            }

            this._autoDownloadTimer = setTimeout(() => {
                // Tekrar kontrol et — timer sırasında durum değişmiş olabilir
                const currentRecord = this.model.root;
                if (!currentRecord || !currentRecord.data || currentRecord.data.state !== "downloading") {
                    this._invoiceCollectorProcessing = false;
                    return;
                }

                if (this._invoiceCollectorProcessing) {
                    return;
                }

                const btn = document.querySelector("button[name='action_download_zip']");
                if (btn && !btn.disabled) {
                    this._invoiceCollectorProcessing = true;
                    btn.click();
                    // Butona tıklandıktan sonra kilidi 3 saniye sonra kaldır
                    // (sunucu yanıtı gelince onPatched tetiklenecek)
                    setTimeout(() => {
                        this._invoiceCollectorProcessing = false;
                    }, 3000);
                }
            }, 800);
        };

        onMounted(() => {
            checkAutoDownload();
        });

        onPatched(() => {
            checkAutoDownload();
        });

        onWillUnmount(() => {
            if (this._autoDownloadTimer) {
                clearTimeout(this._autoDownloadTimer);
            }
            this._invoiceCollectorProcessing = false;
        });
    }
});
