/** @odoo-module **/

import { Component, useState, useRef, onMounted } from "@odoo/owl";

export class ImageComparison extends Component {
    static template = "ugurlar_ai_studio.ImageComparison";
    static props = {
        originalSrc: { type: String },
        generatedSrc: { type: String },
        mode: { type: String, optional: true }, // side, slider, overlay
    };

    setup() {
        this.sliderRef = useRef("slider");
        this.state = useState({
            position: 50,
            overlayOpacity: 0.5,
            isDragging: false,
        });
    }

    onSliderInput(ev) {
        this.state.position = ev.target.value;
    }

    onOpacityInput(ev) {
        this.state.overlayOpacity = ev.target.value / 100;
    }

    get mode() {
        return this.props.mode || "side";
    }

    get clipStyle() {
        return `clip-path: inset(0 ${100 - this.state.position}% 0 0)`;
    }
}
