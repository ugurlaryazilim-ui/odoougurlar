/** @odoo-module **/
import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";

export class CameraScannerAction extends Component {
    static template = "social_media_ai_manager.CameraScannerAction";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            scannedProducts: [],
            scanning: true,
            lastError: null,
        });

        onMounted(() => {
            this.scanProduct();
        });
    }

    scanProduct() {
        const postId = this.props.action.context.default_post_id;
        if (!postId) return;

        this.state.scanning = true;
        this.state.lastError = null;

        openCameraScanner(async (barcode) => {
            if (barcode && postId) {
                const result = await this.orm.call(
                    "social.media.post",
                    "action_add_barcode",
                    [postId, barcode]
                );

                if (result.success) {
                    this.state.scannedProducts.push(result.product_name);
                    this.state.lastError = null;
                } else {
                    this.state.lastError = result.message;
                }

                // Re-open scanner for the next product after a short delay
                setTimeout(() => this.scanProduct(), 400);
            } else {
                this.state.scanning = false;
            }
        }, { headerText: 'Ürün Barkodu Okut' });
    }

    scanAgain() {
        this.scanProduct();
    }

    closeAndReload() {
        this.actionService.doAction({ type: "ir.actions.act_window_close" });
        window.location.reload();
    }
}

registry.category("actions").add("social_media.camera_scanner", CameraScannerAction);
