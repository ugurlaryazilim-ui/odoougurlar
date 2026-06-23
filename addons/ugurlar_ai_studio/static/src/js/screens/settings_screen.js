/** @odoo-module **/

import { Component, useState } from "@odoo/owl";

export class SettingsScreen extends Component {
    static template = "ugurlar_ai_studio.SettingsScreen";
    static props = {
        productInfo: { type: Object },
        presets: { type: Array },
        promptTemplates: { type: Array },
        onStartProcessing: { type: Function },
        onBackToScan: { type: Function },
    };

    setup() {
        this.state = useState({
            selectedPresetId: null,
            category: "auto",
            qualityMode: "balanced",
            extraPrompt: "",
            selectedTemplateId: null,
        });
    }

    selectPreset(presetId) {
        this.state.selectedPresetId = presetId;
    }

    get selectedPreset() {
        return this.props.presets.find(p => p.id === this.state.selectedPresetId);
    }

    get estimatedCost() {
        const base = 0.075;
        const multiplier = this.state.qualityMode === "quality" ? 1.5 :
                           this.state.qualityMode === "performance" ? 0.7 : 1.0;
        return (base * multiplier).toFixed(3);
    }

    onTemplateChange(ev) {
        const id = parseInt(ev.target.value);
        this.state.selectedTemplateId = id || null;
        if (id) {
            const tmpl = this.props.promptTemplates.find(t => t.id === id);
            if (tmpl) {
                this.state.extraPrompt = tmpl.prompt_text;
            }
        }
    }

    startProcessing() {
        if (!this.state.selectedPresetId) return;
        this.props.onStartProcessing({
            presetId: this.state.selectedPresetId,
            category: this.state.category,
            qualityMode: this.state.qualityMode,
            extraPrompt: this.state.extraPrompt,
            promptTemplateId: this.state.selectedTemplateId,
        });
    }
}
