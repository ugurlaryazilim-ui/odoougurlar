/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useInputField } from "@web/views/fields/input_field_hook";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { openCameraScanner } from "@ugurlar_barcode/js/camera_scanner";

export class CameraBarcodeField extends Component {
    setup() {
        useInputField({ getValue: () => this.props.record.data[this.props.name] || "", refName: "input" });
    }

    startScanning() {
        openCameraScanner((barcode) => {
            if (barcode) {
                this.props.record.update({ [this.props.name]: barcode });
            }
        });
    }
}

CameraBarcodeField.template = "social_media_ai_manager.CameraBarcodeField";
CameraBarcodeField.props = { ...standardFieldProps };

registry.category("fields").add("camera_barcode", CameraBarcodeField);
