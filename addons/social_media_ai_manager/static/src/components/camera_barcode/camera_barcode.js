/** @odoo-module **/

import { CharField } from "@web/views/fields/char/char_field";
import { registry } from "@web/core/registry";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";
import { xml } from "@odoo/owl";

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

CameraBarcodeField.template = xml`
<div class="d-flex align-items-center w-100">
    <t t-call="web.CharField"/>
    <button type="button" class="btn btn-primary ms-2 flex-shrink-0" t-on-click="startScanning" title="Kamera ile Barkod Okut">
        <i class="fa fa-camera"></i> Oku
    </button>
</div>
`;

registry.category("fields").add("camera_barcode", CameraBarcodeField);
