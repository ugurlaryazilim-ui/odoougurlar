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
