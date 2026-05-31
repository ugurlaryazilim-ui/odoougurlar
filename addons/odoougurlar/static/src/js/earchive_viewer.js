/** @odoo-module **/

import { Component, xml, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

/**
 * E-Arşiv Fatura Görüntüleyici
 *
 * Fatura portalını kontrollü popup pencerede açar.
 * JSF portal session sorunlarını önlemek için doğrudan tarayıcı penceresi kullanılır.
 */
class EArchiveViewer extends Component {
    static template = xml`
        <div class="ea-overlay" t-on-click.stop="onOverlayClick">
            <div class="ea-dialog" t-on-click.stop="() => {}">
                <div class="ea-dialog-icon">📄</div>
                <h3 class="ea-dialog-title">E-Arşiv Fatura</h3>
                <p class="ea-dialog-subtitle" t-if="state.einvoiceNumber">
                    <t t-esc="state.einvoiceNumber"/>
                </p>
                <p class="ea-dialog-info" t-if="state.opened">
                    Fatura yeni pencerede açıldı.<br/>
                    "PDF Görüntüle" butonuna tıklayarak yazdırabilirsiniz.
                </p>
                <p class="ea-dialog-info" t-if="!state.opened">
                    Fatura penceresi açılıyor...
                </p>
                <div class="ea-dialog-actions">
                    <button class="ea-btn ea-btn-open" t-on-click="onOpenAgain"
                            t-if="state.opened">
                        <i class="fa fa-external-link"/> Tekrar Aç
                    </button>
                    <button class="ea-btn ea-btn-close" t-on-click="onClose">
                        <i class="fa fa-arrow-left"/> Faturaya Dön
                    </button>
                </div>
            </div>
        </div>
    `;

    static props = ["*"];

    setup() {
        const action = this.props.action || {};
        const params = action.params || {};

        this.invoiceUrl = params.invoice_url || '';

        this.state = useState({
            einvoiceNumber: params.einvoice_number || '',
            opened: false,
        });

        // Popup'ı hemen aç
        if (this.invoiceUrl) {
            this._openPopup();
        }
    }

    _openPopup() {
        // Ekran boyutuna göre pencere boyutu
        const w = Math.min(950, window.innerWidth - 100);
        const h = Math.min(750, window.innerHeight - 100);
        const left = (window.innerWidth - w) / 2 + window.screenX;
        const top = (window.innerHeight - h) / 2 + window.screenY;

        this._popup = window.open(
            this.invoiceUrl,
            'earchive_invoice',
            `width=${w},height=${h},left=${left},top=${top},` +
            'scrollbars=yes,resizable=yes,menubar=no,toolbar=no,location=no,status=no'
        );

        if (this._popup) {
            this._popup.focus();
            this.state.opened = true;
        } else {
            // Popup blocker aktif — yeni sekmede aç
            window.open(this.invoiceUrl, '_blank');
            this.state.opened = true;
        }
    }

    onOpenAgain() {
        if (this._popup && !this._popup.closed) {
            this._popup.focus();
        } else {
            this._openPopup();
        }
    }

    onClose() {
        // Popup'ı kapat
        if (this._popup && !this._popup.closed) {
            this._popup.close();
        }

        // Odoo'ya geri dön
        const actionService = this.env.services.action;
        if (actionService) {
            actionService.restore();
        } else {
            window.history.back();
        }
    }

    onOverlayClick(ev) {
        if (ev.target.classList.contains('ea-overlay')) {
            this.onClose();
        }
    }
}

registry.category("actions").add("earchive_viewer", EArchiveViewer);
