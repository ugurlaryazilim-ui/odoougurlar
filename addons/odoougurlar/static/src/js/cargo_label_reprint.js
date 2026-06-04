/** @odoo-module **/

import { Component, xml, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

/**
 * Kargo Etiketi Yeniden Yazdırma — Client Action
 *
 * sale.order form'undan çağrılır, packing_label_data API'sini kullanarak
 * aynı şablon ile etiketi tarayıcıda render edip window.print() ile yazdırır.
 * packing.js ile birebir aynı çıktıyı üretir.
 */
class CargoLabelReprint extends Component {
    static template = xml`
        <div class="ea-overlay" t-on-click.stop="onOverlayClick">
            <div class="ea-dialog" t-on-click.stop="() => {}">
                <div class="ea-dialog-icon">🏷️</div>
                <h3 class="ea-dialog-title">Kargo Etiketi</h3>
                <p class="ea-dialog-subtitle" t-if="state.pickingName">
                    <t t-esc="state.pickingName"/>
                </p>
                <p class="ea-dialog-info" t-if="state.status === 'loading'">
                    Etiket verisi yükleniyor...
                </p>
                <p class="ea-dialog-info" t-if="state.status === 'printing'">
                    Etiket yazdırma penceresi açıldı.<br/>
                    Yazdırma tamamlandıktan sonra bu pencere kapanacak.
                </p>
                <p class="ea-dialog-info text-danger" t-if="state.status === 'error'">
                    <t t-esc="state.errorMsg"/>
                </p>
                <div class="ea-dialog-actions">
                    <button class="ea-btn ea-btn-open" t-on-click="onPrintAgain"
                            t-if="state.status === 'printing'">
                        <i class="fa fa-print"/> Tekrar Yazdır
                    </button>
                    <button class="ea-btn ea-btn-close" t-on-click="onClose">
                        <i class="fa fa-arrow-left"/> Siparişe Dön
                    </button>
                </div>
            </div>
        </div>
    `;

    static props = ["*"];

    setup() {
        const action = this.props.action || {};
        const params = action.params || {};
        this.pickingId = params.picking_id || 0;

        this.state = useState({
            status: 'loading',
            pickingName: '',
            errorMsg: '',
        });

        this._lastHtml = '';

        onMounted(() => {
            this._loadAndPrint();
        });
    }

    async _loadAndPrint() {
        try {
            // 1. Label verisini çek (packing.js ile aynı API)
            const data = await rpc('/ugurlar_barcode/api/packing_label_data', {
                picking_id: this.pickingId,
            });

            if (data.error) {
                this.state.status = 'error';
                this.state.errorMsg = data.error;
                return;
            }

            this.state.pickingName = data.picking_name || '';

            // 2. Etiket şablonunu bul
            let template = null;
            try {
                const res = await rpc('/ugurlar_barcode/api/label_template_list', {});
                const ct = (res.templates || []).filter(t => t.name.startsWith('Kargo'));
                if (ct.length > 0) template = ct[0];
            } catch (e) { /* varsayılan */ }

            // 3. HTML oluştur (packing.js ile birebir aynı mantık)
            let html;
            if (template && template.elements && template.elements.length > 0) {
                html = this._buildTemplateHtml(template, data);
            } else {
                html = this._buildDefaultHtml(data);
            }

            this._lastHtml = html;
            this.state.status = 'printing';
            this._printViaWindow(html);

        } catch (e) {
            this.state.status = 'error';
            this.state.errorMsg = 'Etiket verisi alınamadı: ' + (e.message || e);
        }
    }

    // ─── packing.js _getFieldValue birebir kopyası ───
    _getFieldValue(type, data) {
        const map = {
            order_number:      data.order_number || data.origin || '',
            picking_name:      data.picking_name || '',
            origin:            data.origin || '',
            marketplace:       data.marketplace_name || '',
            customer_name:     data.customer_name || data.partner_name || '',
            partner_phone:     data.partner_phone || '',
            shipping_address:  data.shipping_address || data.partner_address || '',
            shipping_city:     data.shipping_city || '',
            shipping_district: data.shipping_district || '',
            cargo_tracking:    data.cargo_tracking || '',
            cargo_provider:    data.cargo_provider || '',
            total_qty:         (data.total_qty || 0) + ' adet',
            total_items:       (data.total_items || 0) + ' çeşit',
            date_today:        new Date().toLocaleDateString('tr-TR'),
            nebim_invoice_no:  data.nebim_invoice_no || '',
            nebim_invoice_date: data.nebim_invoice_date || '',
        };
        return map[type] !== undefined ? map[type] : '';
    }

    // ─── packing.js _renderCargoTemplate birebir kopyası ───
    _buildTemplateHtml(template, data) {
        const wMm = template.width_mm;
        const hMm = template.height_mm;

        let elementsHtml = '';
        for (const el of template.elements) {
            const x = el.x, y = el.y, w = el.width, h = el.height;
            const fs = el.fontSize || 9, fw = el.fontWeight || 'normal';
            const ta = el.textAlign || 'left', color = el.color || '#000000';
            const bgColor = el.bgColor || 'transparent', rotation = el.rotation || 0;
            let content = '';

            if (el.type === 'line') {
                const lineH = Math.max(h, 0.3);
                elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${lineH}mm; background:${color}; transform:rotate(${rotation}deg);"></div>`;
                continue;
            }
            if (el.type === 'box') {
                const bw = el.borderWidth || 1;
                elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; border:${bw}px solid ${color}; background:${bgColor}; transform:rotate(${rotation}deg);"></div>`;
                continue;
            }
            if (el.type === 'cargo_barcode') {
                const bv = data.cargo_tracking || '';
                if (bv) {
                    const enc = encodeURIComponent(bv), iW = Math.round(w*12), iH = Math.round(h*12);
                    elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; transform:rotate(${rotation}deg); text-align:center;"><img src="/report/barcode/Code128/${enc}?width=${iW}&height=${iH}&humanreadable=1" style="width:100%;height:100%;object-fit:contain;image-rendering:pixelated;" onerror="this.style.display='none'" /></div>`;
                }
                continue;
            }
            if (el.type === 'cargo_qr_code') {
                const qv = el.content || data.cargo_tracking || '';
                if (qv) {
                    elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; transform:rotate(${rotation}deg);"><img src="/report/barcode/?type=QR&value=${encodeURIComponent(qv)}&width=${Math.round(w*12)}&height=${Math.round(h*12)}" style="width:100%;height:100%;object-fit:contain;" /></div>`;
                }
                continue;
            }
            if (el.type === 'item_list') {
                const items = data.items || [];
                let tbl = '<table style="width:100%;border-collapse:collapse;font-size:inherit;"><thead><tr style="border-bottom:0.3mm solid #333;"><th style="text-align:left;padding:0 0.5mm;">#</th><th style="text-align:left;padding:0 0.5mm;">Ürün</th><th style="text-align:right;padding:0 0.5mm;">Adet</th><th style="text-align:left;padding:0 0.5mm;">Barkod</th></tr></thead><tbody>';
                items.forEach((item, idx) => { tbl += `<tr><td style="padding:0 0.5mm;">${idx+1}</td><td style="padding:0 0.5mm;">${item.product_name}</td><td style="text-align:right;padding:0 0.5mm;">${item.qty}</td><td style="padding:0 0.5mm;">${item.barcode}</td></tr>`; });
                tbl += '</tbody></table>';
                elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; font-size:${fs}pt; font-weight:${fw}; overflow:hidden; color:${color}; background:${bgColor}; transform:rotate(${rotation}deg);">${tbl}</div>`;
                continue;
            }
            if (el.type === 'custom_text' || el.type === 'sender_name') {
                content = el.content || '';
            } else {
                content = this._getFieldValue(el.type, data);
            }
            elementsHtml += `<div style="position:absolute; left:${x}mm; top:${y}mm; width:${w}mm; height:${h}mm; font-size:${fs}pt; font-weight:${fw}; text-align:${ta}; color:${color}; background:${bgColor}; transform:rotate(${rotation}deg); overflow:hidden; line-height:1.3; display:flex; align-items:center; ${ta === 'center' ? 'justify-content:center;' : ta === 'right' ? 'justify-content:flex-end;' : ''}">${content}</div>`;
        }

        return `<!DOCTYPE html><html><head>
            <meta charset="utf-8">
            <title>Kargo Etiketi ${wMm}x${hMm}mm</title>
            <style>
                @page { size: ${wMm}mm ${hMm}mm; margin: 0; }
                * { margin: 0; padding: 0; box-sizing: border-box; }
                html, body { margin: 0; padding: 0; }
                body {
                    width: ${wMm}mm; height: ${hMm}mm;
                    font-family: Arial, Helvetica, sans-serif;
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }
                .label {
                    position: relative;
                    width: ${wMm}mm; height: ${hMm}mm;
                    overflow: hidden;
                }
                img { image-rendering: pixelated; image-rendering: -moz-crisp-edges; }
                @media print {
                    @page { size: ${wMm}mm ${hMm}mm; margin: 0; }
                    html, body { width: ${wMm}mm; height: ${hMm}mm; overflow: hidden; }
                    .label { overflow: hidden; page-break-after: avoid; }
                }
            </style>
        </head><body>
            <div class="label">${elementsHtml}</div>
        </body></html>`;
    }

    // ─── Varsayılan etiket (şablon yoksa) ───
    _buildDefaultHtml(data) {
        const cargoBarcode = data.cargo_tracking || '';
        const barcodeHtml = cargoBarcode
            ? `<div style="text-align:center; margin:2mm 0;">
                 <img src="/report/barcode/Code128/${encodeURIComponent(cargoBarcode)}?width=840&height=200&humanreadable=1"
                     style="width:70mm; height:18mm; display:inline-block; object-fit:contain; image-rendering:-webkit-crisp-edges; image-rendering:pixelated;" />
               </div>`
            : '';

        const itemsHtml = (data.items || []).map(i =>
            `<tr><td>${i.product_name}</td><td style="text-align:center;">${i.qty}</td><td style="text-align:center;">${i.barcode}</td></tr>`
        ).join('');

        return `<!DOCTYPE html><html><head>
            <meta charset="utf-8">
            <title>Kargo Etiketi — ${data.picking_name || ''}</title>
            <style>
                @page { size: 100mm 150mm; margin: 3mm; }
                * { margin:0; padding:0; box-sizing:border-box; }
                body { font-family: Arial, sans-serif; font-size: 11px; }
                .label { width: 94mm; padding: 4mm; }
                .header { display:flex; justify-content:space-between; border-bottom:2px solid #000; padding-bottom:4px; margin-bottom:6px; }
                .header h2 { font-size:14px; margin:0; }
                .info-grid { display:grid; grid-template-columns:1fr 1fr; gap:4px 12px; margin-bottom:6px; }
                .info-label { font-weight:bold; font-size:9px; color:#666; text-transform:uppercase; }
                .info-value { font-size:11px; }
                .cargo-section { text-align:center; border:2px solid #000; padding:6px; margin:6px 0; }
                .cargo-section .tracking { font-size:16px; font-weight:bold; letter-spacing:1px; }
                table { width:100%; border-collapse:collapse; margin-top:4px; }
                th, td { border:1px solid #ccc; padding:3px 4px; font-size:9px; }
                th { background:#f0f0f0; }
                @media print {
                    @page { size: 100mm 150mm; margin: 3mm; }
                }
            </style>
        </head><body>
        <div class="label">
            <div class="header"><h2>${data.cargo_provider || 'KARGO'}</h2><span>${data.picking_name || ''}</span></div>
            <div class="info-grid">
                <div><div class="info-label">Sipariş No</div><div class="info-value">${data.order_number || data.origin || ''}</div></div>
                <div><div class="info-label">Müşteri</div><div class="info-value">${data.customer_name || data.partner_name || ''}</div></div>
                <div><div class="info-label">Tel</div><div class="info-value">${data.partner_phone || '-'}</div></div>
                <div><div class="info-label">Adet</div><div class="info-value">${data.total_qty || 0} ürün</div></div>
            </div>
            <div><div class="info-label">Adres</div><div class="info-value" style="font-size:10px;">${data.shipping_address || data.partner_address || ''}</div></div>
            <div class="cargo-section">
                ${barcodeHtml}
                <div class="tracking">${cargoBarcode}</div>
            </div>
            <table>
                <thead><tr><th>Ürün</th><th>Adet</th><th>Barkod</th></tr></thead>
                <tbody>${itemsHtml}</tbody>
            </table>
        </div>
        </body></html>`;
    }

    // ─── packing.js _printViaWindow birebir kopyası ───
    _printViaWindow(html) {
        const win = window.open('', '_blank', 'width=800,height=600');
        if (!win) {
            // Popup engellenmiş — iframe ile yazdır
            this._printViaIframe(html);
            return;
        }
        win.document.write(html);
        win.document.close();

        const tryPrint = () => {
            const imgs = win.document.querySelectorAll('img');
            const allLoaded = Array.from(imgs).every(img => img.complete && img.naturalHeight > 0);
            if (allLoaded || imgs.length === 0) {
                win.focus();
                win.print();
                // Print dialog kapandıktan sonra otomatik kapat
                setTimeout(() => {
                    try { win.close(); } catch (e) {}
                }, 500);
            } else {
                setTimeout(tryPrint, 200);
            }
        };
        setTimeout(tryPrint, 600);
    }

    _printViaIframe(html) {
        const old = document.getElementById('ub-reprint-iframe');
        if (old) old.parentNode.removeChild(old);

        const iframe = document.createElement('iframe');
        iframe.id = 'ub-reprint-iframe';
        iframe.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;opacity:0;pointer-events:none;z-index:-9999;';
        document.body.appendChild(iframe);

        const doc = iframe.contentWindow.document;
        doc.open();
        doc.write(html);
        doc.close();

        const tryPrint = () => {
            const imgs = doc.querySelectorAll('img');
            const allLoaded = Array.from(imgs).every(img => img.complete && img.naturalHeight > 0);
            if (allLoaded || imgs.length === 0) {
                iframe.contentWindow.focus();
                iframe.contentWindow.print();
                setTimeout(() => {
                    try { iframe.parentNode.removeChild(iframe); } catch (e) {}
                }, 500);
            } else {
                setTimeout(tryPrint, 200);
            }
        };
        setTimeout(tryPrint, 600);
    }

    onPrintAgain() {
        if (this._lastHtml) {
            this._printViaWindow(this._lastHtml);
        }
    }

    onClose() {
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

registry.category("actions").add("cargo_label_reprint", CargoLabelReprint);
