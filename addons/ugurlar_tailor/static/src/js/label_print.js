/** @odoo-module **/

/**
 * Terzi etiket yazdirma — iframe + window.print() yontemi.
 * Barcode modulundeki yaklaşımla ayni.
 */
export function printTailorLabel(data) {
    const copies = [
        { title: 'TERZİ NÜSHASI', bg: '#e74c3c', note: 'Bu nüsha terzide kalır' },
        { title: 'MAĞAZA NÜSHASI', bg: '#2980b9', note: 'Ürünle birlikte mağazaya döner' },
        { title: 'MÜŞTERİ NÜSHASI', bg: '#27ae60', note: 'Bu nüsha müşteride kalır' },
    ];

    const servicesHtml = data.services.map(s =>
        `<div style="display:flex;justify-content:space-between;padding:1px 4px;">
            <span>${s.name}</span>
            <span>${s.price.toFixed(2)} TL</span>
        </div>`
    ).join('');

    const labelsHtml = copies.map(c => `
        <div class="label">
            <div class="label-hdr" style="background:${c.bg};">${c.title}</div>
            <div class="label-store">UĞURLAR</div>
            <div class="label-sub">Terzi Takip Sistemi</div>
            <hr class="label-div"/>
            <div class="label-r"><span class="ll">Sipariş No:</span><span class="vv" style="font-size:13px;font-weight:bold;">${data.name}</span></div>
            <div class="label-r"><span class="ll">Fatura No:</span><span class="vv">${data.invoice_no}</span></div>
            <hr class="label-div"/>
            <div class="label-r"><span class="ll">Müşteri:</span><span class="vv">${data.customer_name}</span></div>
            ${data.customer_phone ? `<div class="label-r"><span class="ll">Telefon:</span><span class="vv">${data.customer_phone}</span></div>` : ''}
            ${data.sales_person ? `<div class="label-r"><span class="ll">Satış Per.:</span><span class="vv">${data.sales_person}</span></div>` : ''}
            <hr class="label-div"/>
            <div class="label-r"><span class="ll">Ürün:</span><span class="vv">${data.product_code || data.product_name}</span></div>
            <div class="label-r"><span class="ll">Barkod:</span><span class="vv">${data.product_barcode}</span></div>
            <hr class="label-div"/>
            <div class="label-r"><span class="ll">Terzi:</span><span class="vv" style="font-weight:bold;font-size:12px;">${data.tailor_name}</span></div>
            <hr class="label-div"/>
            <div class="label-section">YAPILACAK İŞLEMLER</div>
            ${servicesHtml}
            <div class="label-total">TOPLAM: ${data.total_price.toFixed(2)} TL</div>
            <div class="label-dt">${data.date}</div>
            <div class="label-ft">${c.note}</div>
            ${data.notes ? `<hr class="label-div"/><div style="font-size:10px;"><b>Not:</b> ${data.notes}</div>` : ''}
        </div>
    `).join('');

    const html = `<!DOCTYPE html><html><head>
        <meta charset="utf-8">
        <title>Terzi Etiket — ${data.name}</title>
        <style>
            @page { size: 80mm auto; margin: 2mm; }
            * { margin:0; padding:0; box-sizing:border-box; }
            body { font-family: Arial, sans-serif; font-size: 11px; color: #000; }
            .label {
                width: 76mm;
                padding: 0;
                margin: 0 auto;
                page-break-after: always;
            }
            .label-hdr {
                text-align: center;
                padding: 6px 0;
                margin-bottom: 4px;
                color: #fff;
                font-weight: bold;
                font-size: 16px;
                letter-spacing: 1px;
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
            }
            .label-store {
                text-align: center;
                font-size: 14px;
                font-weight: bold;
                margin-bottom: 2px;
            }
            .label-sub {
                text-align: center;
                font-size: 10px;
                margin-bottom: 4px;
            }
            .label-div {
                border: none;
                border-top: 1px dashed #000;
                margin: 4px 0;
            }
            .label-r {
                overflow: hidden;
                padding: 1px 0;
                line-height: 1.4;
            }
            .label-r .ll {
                font-weight: bold;
                float: left;
                width: 80px;
            }
            .label-r .vv {
                margin-left: 85px;
            }
            .label-section {
                font-weight: bold;
                text-align: center;
                padding: 3px 0;
                font-size: 12px;
                clear: both;
            }
            .label-total {
                font-size: 14px;
                font-weight: bold;
                text-align: right;
                padding: 6px 0;
                border-top: 2px solid #000;
                border-bottom: 2px solid #000;
                margin: 4px 0;
            }
            .label-dt {
                text-align: center;
                font-size: 10px;
                margin-top: 4px;
            }
            .label-ft {
                text-align: center;
                font-size: 9px;
                color: #666;
                margin-top: 4px;
                font-style: italic;
            }
        </style>
    </head><body>
        ${labelsHtml}
    </body></html>`;

    // Barcode modulundeki gibi iframe ile yazdir
    let iframe = document.getElementById('tailor-print-iframe');
    if (!iframe) {
        iframe = document.createElement('iframe');
        iframe.id = 'tailor-print-iframe';
        iframe.style.position = 'fixed';
        iframe.style.right = '0';
        iframe.style.bottom = '0';
        iframe.style.width = '1px';
        iframe.style.height = '1px';
        iframe.style.opacity = '0.01';
        iframe.style.border = '0';
        iframe.style.pointerEvents = 'none';
        document.body.appendChild(iframe);
    }

    const doc = iframe.contentWindow.document;
    doc.open();
    doc.write(html);
    doc.close();

    setTimeout(() => {
        iframe.contentWindow.focus();
        iframe.contentWindow.print();
    }, 500);
}
