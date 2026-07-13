/** @odoo-module **/

import { CharField } from "@web/views/fields/char/char_field";
import { registry } from "@web/core/registry";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";

export class CameraBarcodeField extends CharField {
    startScanning() {
        openCameraScanner((barcode) => {
            if (barcode) {
                // Update the field value and trigger onchange
                this.props.update(barcode);
            }
        });
    }
}

CameraBarcodeField.template = "social_media_ai_manager.CameraBarcodeField";

registry.category("fields").add("camera_barcode", CameraBarcodeField);
