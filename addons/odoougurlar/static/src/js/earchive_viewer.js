/** @odoo-module **/

import { Component, xml, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

/**
 * E-Arşiv Fatura Görüntüleyici
 *
 * Fatura PDF'ini modal overlay içinde iframe ile gösterir.
 * Yazdır butonu ile PDF'i popup pencerede açıp print dialog tetikler.
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
                        <button class="ea-btn ea-btn-download" t-on-click="onDownload">
                            <i class="fa fa-download"/> İndir
                        </button>
                        <button class="ea-btn ea-btn-close" t-on-click="onClose">
                            <i class="fa fa-times"/> Kapat
                        </button>
                    </div>
                </div>

                <!-- Loading -->
                <div class="ea-loading" t-if="state.loading">
                    <i class="fa fa-spinner fa-spin fa-3x"/>
                    <p>Fatura yükleniyor...</p>
                </div>

                <!-- PDF iframe -->
                <div class="ea-body" t-att-class="{ 'ea-hidden': state.loading }">
                    <iframe
                        t-att-src="state.pdfUrl"
                        class="ea-iframe"
                        t-on-load="onIframeLoad"
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

        // E-arşiv portal URL'sinden PDF URL'sini türet
        const invoiceUrl = params.invoice_url || '';
        let pdfUrl = invoiceUrl;

        // Portal sayfasından doğrudan PDF viewer URL'sine dönüştür
        // view-pdf-earchive.xhtml?webValidationKey=XXX → pdf/goruntule linkini doğrudan kullanamayız
        // Bunun yerine portal URL'sini iframe'de gösteriyoruz
        // Kullanıcı "PDF Görüntüle" butonuna tıklayacak

        this.state = useState({
            invoiceUrl: invoiceUrl,
            pdfUrl: pdfUrl,
            einvoiceNumber: params.einvoice_number || '',
            loading: true,
        });
    }

    onIframeLoad() {
        this.state.loading = false;
    }

    onPrint() {
        // Cross-origin PDF olduğu için iframe.print() çalışmaz
        // Yeni popup pencere açıp print dialog tetikliyoruz
        const url = this.state.invoiceUrl;
        const printWindow = window.open(url, '_blank',
            'width=900,height=700,scrollbars=yes,resizable=yes,menubar=no,toolbar=no'
        );

        if (printWindow) {
            // PDF yüklendikten sonra print dialog aç
            printWindow.addEventListener('load', () => {
                setTimeout(() => {
                    try {
                        printWindow.print();
                    } catch (e) {
                        // Cross-origin durumunda kullanıcı manuel yazdırsın
                        console.warn('Print cross-origin engeli:', e);
                    }
                }, 1500);
            });

            // Print bittikten sonra pencereyi kapat
            printWindow.addEventListener('afterprint', () => {
                printWindow.close();
            });
        }
    }

    onDownload() {
        // PDF'i yeni sekmede aç (indirme için)
        window.open(this.state.invoiceUrl, '_blank');
    }

    onClose() {
        // Odoo action manager ile geri dön
        this.props.action?.onClose?.();
        // Fallback: history back
        window.history.back();
    }

    onOverlayClick(ev) {
        // Overlay'e tıklayınca kapat (modal dışına tıklama)
        if (ev.target.classList.contains('ea-overlay')) {
            this.onClose();
        }
    }
}

// Client action olarak kaydet
registry.category("actions").add("earchive_viewer", EArchiveViewer);
