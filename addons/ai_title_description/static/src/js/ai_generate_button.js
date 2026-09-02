/** @odoo-module */
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class AIGenerateButton extends Component {
    static template = "ai_title_description.AIGenerateButton";
    static props = { ...standardFieldProps };

    setup() {
        this.action = useService("action");
        this.state = useState({ isGenerating: false });
    }

    async onClickGenerate() {
        this.state.isGenerating = true;
        try {
            const resId = this.props.record.resId;
            const result = await this.props.record.model.orm.call(
                "product.template",
                "action_open_ai_title_wizard",
                [resId]
            );
            await this.action.doAction(result);
        } catch (error) {
            // Error handled by framework
        } finally {
            this.state.isGenerating = false;
        }
    }
}

registry.category("fields").add("ai_generate_button", {
    component: AIGenerateButton,
});
