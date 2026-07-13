/** @odoo-module **/
import { Component, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";

export class CameraScannerAction extends Component {
    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");
        
        onMounted(() => {
            openCameraScanner(async (barcode) => {
                if (barcode && this.props.action.context.default_post_id) {
                    await this.orm.call("social.media.post", "action_add_barcode", [this.props.action.context.default_post_id, barcode]);
                }
                this.actionService.doAction({ type: "ir.actions.act_window_close" });
                // We need to trigger a reload of the underlying form view
                // In Odoo, closing a dialog usually reloads the parent if configured, or we can use actionService
                this.actionService.doAction({ type: "ir.actions.client", tag: "reload" });
            });
        });
    }
}
CameraScannerAction.template = "social_media_ai_manager.CameraScannerAction";
registry.category("actions").add("social_media.camera_scanner", CameraScannerAction);
