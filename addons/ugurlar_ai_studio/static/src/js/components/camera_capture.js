/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";

export class CameraCapture extends Component {
    static template = "ugurlar_ai_studio.CameraCapture";
    static props = {
        onCapture: { type: Function },
        facingMode: { type: String, optional: true },
    };

    setup() {
        this.videoRef = useRef("video");
        this.state = useState({ active: false, error: null });

        onMounted(() => this.start());
        onWillUnmount(() => this.stop());
    }

    async start() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: this.props.facingMode || "environment",
                    width: { ideal: 1920 },
                    height: { ideal: 1440 },
                },
            });
            if (this.videoRef.el) {
                this.videoRef.el.srcObject = stream;
            }
            this.stream = stream;
            this.state.active = true;
        } catch (e) {
            this.state.error = "Kamera erişilemedi";
        }
    }

    stop() {
        if (this.stream) {
            this.stream.getTracks().forEach(t => t.stop());
        }
    }

    capture() {
        if (!this.videoRef.el) return;
        const v = this.videoRef.el;
        const c = document.createElement("canvas");
        c.width = v.videoWidth;
        c.height = v.videoHeight;
        c.getContext("2d").drawImage(v, 0, 0);
        const dataUrl = c.toDataURL("image/jpeg", 0.92);
        this.props.onCapture(dataUrl.split(",")[1], dataUrl);
    }
}
