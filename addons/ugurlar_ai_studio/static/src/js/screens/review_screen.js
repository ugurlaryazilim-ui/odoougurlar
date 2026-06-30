/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class ReviewScreen extends Component {
    static template = "ugurlar_ai_studio.ReviewScreen";
    static props = {
        sessionId: { type: Number },
        generations: { type: Array },
        rejectReasons: { type: Array },
        onApproveGeneration: { type: Function },
        onRejectGeneration: { type: Function },
        onCompleteSession: { type: Function },
        onBackToScan: { type: Function },
    };

    setup() {
        this.orm = useService("orm");

        this.state = useState({
            currentIndex: 0,
            showRejectModal: false,
            selectedReasonId: null,
            revisionPrompt: "",
            compareMode: "side", // side, slider, overlay
            sliderPosition: 50,
            isPrimary: false,
            isSaving: false,
        });
    }

    get currentGen() {
        const doneGens = this.doneGenerations;
        return doneGens[this.state.currentIndex] || null;
    }

    get doneGenerations() {
        return this.props.generations.filter(g => g.state === "done");
    }

    get allApproved() {
        return this.doneGenerations.every(g => g.is_approved);
    }

    get approvedCount() {
        return this.doneGenerations.filter(g => g.is_approved).length;
    }

    get totalCount() {
        return this.doneGenerations.length;
    }

    getTypeLabel(type) {
        return { front: _t("Ön Yüz"), back: _t("Arka Yüz"), detail: _t("Detay") }[type] || type;
    }

    nextGeneration() {
        if (this.state.currentIndex < this.doneGenerations.length - 1) {
            this.state.currentIndex++;
        }
    }

    prevGeneration() {
        if (this.state.currentIndex > 0) {
            this.state.currentIndex--;
        }
    }

    setCompareMode(mode) {
        this.state.compareMode = mode;
    }

    onSliderChange(ev) {
        this.state.sliderPosition = ev.target.value;
    }

    // --- Onay ---
    async approve() {
        const gen = this.currentGen;
        if (!gen) return;
        await this.props.onApproveGeneration(gen.id, this.state.isPrimary);
        this.state.isPrimary = false;
        if (this.state.currentIndex < this.doneGenerations.length - 1) {
            this.nextGeneration();
        }
    }

    // --- Red ---
    openRejectModal() {
        this.state.showRejectModal = true;
        this.state.selectedReasonId = null;
        this.state.revisionPrompt = "";
    }

    closeRejectModal() {
        this.state.showRejectModal = false;
    }

    selectReason(reasonId) {
        this.state.selectedReasonId = reasonId;
        const reason = this.props.rejectReasons.find(r => r.id === reasonId);
        if (reason && reason.suggested_prompt) {
            this.state.revisionPrompt = reason.suggested_prompt;
        }
    }

    async submitRejection() {
        const gen = this.currentGen;
        if (!gen) return;
        await this.props.onRejectGeneration(
            gen.id,
            this.state.selectedReasonId,
            this.state.revisionPrompt
        );
        this.closeRejectModal();
    }

    // --- Tamamla ---
    async completeSession() {
        if (this.state.isSaving) return;
        this.state.isSaving = true;
        try {
            await this.props.onCompleteSession();
        } finally {
            this.state.isSaving = false;
        }
    }
}
