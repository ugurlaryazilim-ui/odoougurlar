/** @odoo-module **/

import { Component, xml, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

/**
 * E-Arşiv Fatura Görüntüleyici
 *
 * Fatura PDF'ini modal overlay içinde doğrudan gösterir.
 * Odoo proxy controller üzerinden PDF çekilir (cross-origin sorununu çözer).
 */
class EArchiveViewer extends Component {
    static template = xml`
        <div class="ea-overlay" t-on-click.stop="onOverlayClick">
            <div class="ea-modal" t-on-click.stop="() => {}">
                <!-- Header -->
                <div class="ea-header">
                    <div class="ea-header-left">
                        <i class="fa fa-file-pdf-o ea-header-icon"/>
                        <span class="ea-header-title">E-Arşiv Fatura</span>
                        <span class="ea-header-subtitle" t-if="state.einvoiceNumber">
                            <t t-esc="state.einvoiceNumber"/>
                        </span>
                    </div>
                    <div class="ea-header-actions">
                        <button class="ea-btn ea-btn-print" t-on-click="onPrint">
                            <i class="fa fa-print"/> Yazdır
                        </button>
                        <button class="ea-btn ea-btn-close" t-on-click="onClose">
                            <i class="fa fa-times"/> Kapat
                        </button>
                    </div>
                </div>

                <!-- Loading -->
                <div class="ea-loading" t-if="state.loading">
                    <i class="fa fa-spinner fa-spin fa-3x"/>
                    <p>Fatura PDF yükleniyor...</p>
                </div>

                <!-- Error -->
                <div class="ea-error" t-if="state.error">
                    <i class="fa fa-exclamation-triangle fa-3x"/>
                    <p><t t-esc="state.error"/></p>
                    <button class="ea-btn ea-btn-print" t-on-click="onOpenExternal">
                        <i class="fa fa-external-link"/> Harici Bağlantıda Aç
                    </button>
                </div>

                <!-- PDF iframe -->
                <div class="ea-body" t-att-class="{ 'ea-hidden': state.loading || state.error }">
                    <iframe
                        t-att-src="state.proxyUrl"
                        class="ea-iframe"
                        t-on-load="onIframeLoad"
                        t-ref="pdfFrame"
                        frameborder="0"
                        allowfullscreen="true"
                    />
                </div>
            </div>
        </div>
    `;

    static props = ["*"];

    setup() {
        const action = this.props.action || {};
        const params = action.params || {};

        const invoiceUrl = params.invoice_url || '';
        const einvoiceNumber = params.einvoice_number || '';

        // Odoo proxy controller üzerinden PDF çek
        // Bu sayede cross-origin ve cookie sorunları yaşanmaz
        const proxyUrl = invoiceUrl
            ? `/odoougurlar/earchive_pdf?url=${encodeURIComponent(invoiceUrl)}`
            : '';

        this.state = useState({
            invoiceUrl: invoiceUrl,
            proxyUrl: proxyUrl,
            einvoiceNumber: einvoiceNumber,
            loading: true,
            error: '',
        });
    }

    onIframeLoad() {
        this.state.loading = false;
    }

    onPrint() {
        // Proxy URL same-origin olduğu için iframe.print() çalışır
        const iframe = document.querySelector('.ea-iframe');
        if (iframe) {
            try {
                iframe.contentWindow.focus();
                iframe.contentWindow.print();
            } catch (e) {
                // Fallback: yeni pencerede aç ve yazdır
                console.warn('iframe print hatası, popup açılıyor:', e);
                const printWin = window.open(this.state.proxyUrl, '_blank',
                    'width=900,height=700,scrollbars=yes,resizable=yes');
                if (printWin) {
                    printWin.addEventListener('load', () => {
                        setTimeout(() => {
                            try { printWin.print(); } catch (e2) { /* kullanıcı manuel yazdırsın */ }
                        }, 1000);
                    });
                    printWin.addEventListener('afterprint', () => printWin.close());
                }
            }
        }
    }

    onOpenExternal() {
        window.open(this.state.invoiceUrl, '_blank');
    }

    onClose() {
        // Odoo breadcrumb'a geri dön
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

// Client action olarak kaydet
registry.category("actions").add("earchive_viewer", EArchiveViewer);
