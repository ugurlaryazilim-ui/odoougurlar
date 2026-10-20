import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { TextField, textField } from "@web/views/fields/text/text_field";
import { insertToken } from "@sms_system/js/placeholder_utils";

/**
 * SMS metni alanı: metin kutusunun altında yer tutucu "çipleri" ({ad} gibi) gösterir.
 * Çipe tıklanınca imlecin olduğu yere eklenir; çip metin kutusuna sürüklenip bırakılabilir.
 * Çipler yalnız düzenlenebilir durumda görünür (salt okunurda TextField yalnız metni gösterir).
 *
 * Kullanım: <field name="body" widget="sms_placeholder_text"
 *                  options="{'placeholders': [{'label': 'Ad', 'value': 'ad'}]}"/>
 * Yer tutucu listesi sunucu kodunun çözebildiği adlarla sınırlı olmalıdır (görünümde verilir).
 */
export class SmsPlaceholderTextField extends TextField {
    static template = "sms_system.SmsPlaceholderTextField";
    static props = {
        ...TextField.props,
        placeholders: { type: Array, optional: true },
    };
    static defaultProps = {
        ...TextField.defaultProps,
        placeholders: [],
    };

    setup() {
        super.setup();
        // Metin kutusu odak kaybedince son imleç/seçim (çipe tıklamak kutunun odağını alır).
        this.lastSelection = null;
    }

    get chips() {
        return this.props.placeholders.map((p) => ({
            label: p.label,
            token: `{${p.value}}`,
        }));
    }

    async onBlur() {
        await super.onBlur();
        const el = this.textareaRef.el;
        if (el) {
            this.lastSelection = { start: el.selectionStart, end: el.selectionEnd };
        }
    }

    get currentSelection() {
        const el = this.textareaRef.el;
        if (el && document.activeElement === el) {
            return { start: el.selectionStart, end: el.selectionEnd };
        }
        return this.lastSelection || { start: null, end: null };
    }

    async onChipClick(token) {
        const el = this.textareaRef.el;
        if (!el) {
            return;
        }
        const { start, end } = this.currentSelection;
        const { value, caret } = insertToken(el.value, token, start, end);
        el.value = value;
        await this.props.record.update({ [this.props.name]: value });
        el.focus();
        el.setSelectionRange(caret, caret);
        this.lastSelection = { start: caret, end: caret };
    }

    onChipKeydown(ev, token) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.onChipClick(token);
        }
    }

    onChipDragStart(ev, token) {
        ev.dataTransfer.setData("text/plain", token);
        ev.dataTransfer.effectAllowed = "copy";
    }

    /**
     * Metin kutusu bırakılan metni kendisi ekler; ekleme bittikten sonra değeri kayda yansıtırız
     * (aksi halde değer ancak odak kaybında kayda geçer ve önizleme geç güncellenir).
     */
    onDrop() {
        setTimeout(() => {
            const el = this.textareaRef.el;
            if (el && el.value !== (this.props.record.data[this.props.name] || "")) {
                this.props.record.update({ [this.props.name]: el.value });
            }
        }, 0);
    }
}

export const smsPlaceholderTextField = {
    ...textField,
    component: SmsPlaceholderTextField,
    displayName: _t("SMS Text with Placeholders"),
    extractProps(fieldInfo, dynamicInfo) {
        return {
            ...textField.extractProps(fieldInfo, dynamicInfo),
            placeholders: fieldInfo.options?.placeholders || [],
        };
    },
};

registry.category("fields").add("sms_placeholder_text", smsPlaceholderTextField);
