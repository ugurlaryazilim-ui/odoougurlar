/** @odoo-module **/
/**
 * Fatura no alanı: kamera ile barkod okutma + Enter ile getirme.
 *
 * Kamera bileşeni ugurlar_barcode'dan (openCameraScanner) çalışma anında alınır;
 * sanal_pos'un o modüle bağımlılığı yoktur. Modül kurulu değilse kamera düğmesi
 * görünmez, alan normal metin kutusu gibi çalışır.
 *
 * Seçenek: ``fetch_method`` — okutma/Enter sonrası çağrılacak "type=object" düğme
 * metodu (ör. action_fetch_invoice). Çağrı, formdaki düğmeye basmakla aynı yoldan
 * (env.onClickViewButton) gider: kayıt önce kaydedilir, sonra metot çalışır.
 */
import { registry } from "@web/core/registry";
import { pick } from "@web/core/utils/objects";
import { CharField, charField } from "@web/views/fields/char/char_field";

const SCANNER_MODULE = "@ugurlar_barcode/js/camera_scanner";

function getCameraScanner() {
    const mod = window.odoo?.loader?.modules?.get(SCANNER_MODULE);
    return mod && typeof mod.openCameraScanner === "function" ? mod.openCameraScanner : null;
}

export class SanalPosScanCharField extends CharField {
    static template = "sanal_pos.ScanCharField";
    static props = {
        ...CharField.props,
        fetchMethod: { type: String, optional: true },
    };

    get canScan() {
        return !this.props.readonly && Boolean(getCameraScanner());
    }

    async _applyAndFetch(rawValue) {
        const value = (rawValue || "").trim();
        if (!value) {
            return;
        }
        const record = this.props.record;
        if (record.data[this.props.name] !== value) {
            await record.update({ [this.props.name]: value });
        }
        if (this.props.fetchMethod) {
            await this.env.onClickViewButton({
                clickParams: { type: "object", name: this.props.fetchMethod },
                getResParams: () =>
                    pick(record, "context", "evalContext", "resModel", "resId", "resIds"),
            });
        }
    }

    onScanClick() {
        const openCameraScanner = getCameraScanner();
        if (!openCameraScanner) {
            return;
        }
        openCameraScanner((code) => this._applyAndFetch(code), {
            headerText: "Fatura Barkodu Okut",
        });
    }

    onKeydown(ev) {
        // El terminali (klavye gibi yazar + Enter) ya da elle yazıp Enter
        if (ev.key === "Enter" && this.props.fetchMethod) {
            ev.preventDefault();
            ev.stopPropagation();
            this._applyAndFetch(this.input.el.value);
        }
    }
}

export const sanalPosScanCharField = {
    ...charField,
    component: SanalPosScanCharField,
    extractProps: (fieldInfo, dynamicInfo) => ({
        ...charField.extractProps(fieldInfo, dynamicInfo),
        fetchMethod: fieldInfo.options.fetch_method || undefined,
    }),
};

registry.category("fields").add("sanal_pos_scan_char", sanalPosScanCharField);
