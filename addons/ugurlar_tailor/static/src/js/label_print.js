/** @odoo-module **/

/**
 * Terzi etiket yazdirma — iframe + window.print() yontemi.
 * 
 * Yapi:
 *   - Her siparis icin: 1x Terzi nushasi + 1x Magaza nushasi
 *   - Tum siparisler icin: 1x Musteri OZET nushasi (tek etiket)
 */

/** Etikete giden her metin kaçışlanır: not / müşteri adı vb. HTML olarak çalışmasın (XSS). */
function esc(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

/** Sipariş no barkodu: ürün terziden dönünce okutulup durum tek dokunuşla ilerletilir. */
function _barcodeImg(value) {
    if (!value) return '';
    const src = `/report/barcode/?barcode_type=Code128&value=${encodeURIComponent(value)}&width=600&height=120&humanreadable=0`;
    return `<div style="text-align:center;margin-top:6px;"><img src="${src}" style="width:70mm;height:14mm;" alt=""/></div>`;
}

function _buildOrderLabel(data, copyType) {
    const config = {
        terzi: {
            title: 'TERZİ NÜSHASI',
            line1: '1. Nüsha terzide kalacak',
            line2: 'Lütfen terzi işlemi bittikten sonra bir nüsha sizde bir nüsha ürün ile birlikte mağazaya gönderiniz.',
        },
        magaza: {
            title: 'MAĞAZA NÜSHASI',
            line1: '2. Nüsha ürünle birlikte mağazaya geri gidecek',
            line2: 'Lütfen terzi işlemi bittikten sonra bir nüsha sizde bir nüsha ürün ile birlikte mağazaya gönderiniz.',
        },
    };

    const c = config[copyType];

    const servicesHtml = data.services.map(s =>
        `<div style="padding:1px 4px;">• ${esc(s.name)}</div>`
    ).join('');

    return `
        <div class="label">
            <div class="label-hdr">${c.title}</div>
            <div class="label-store">UĞURLAR</div>
            <div class="label-sub">Terzi Takip Sistemi</div>
            <hr class="label-div"/>
            <div class="label-r"><span class="ll">Sipariş No:</span><span class="vv" style="font-size:13px;font-weight:bold;">${esc(data.name)}</span></div>
            <div class="label-r"><span class="ll">Fatura No:</span><span class="vv">${esc(data.invoice_no)}</span></div>
            ${data.promised_date ? `<div class="label-r"><span class="ll">Teslim:</span><span class="vv" style="font-weight:bold;">${esc(data.promised_date)}</span></div>` : ''}
            <hr class="label-div"/>
            <div class="label-r"><span class="ll">Müşteri:</span><span class="vv">${esc(data.customer_name)}</span></div>
            ${data.customer_phone ? `<div class="label-r"><span class="ll">Müşteri No:</span><span class="vv">${esc(data.customer_phone)}</span></div>` : ''}
            ${data.sales_person ? `<div class="label-r"><span class="ll">Satış Per.:</span><span class="vv">${esc(data.sales_person)}</span></div>` : ''}
            <hr class="label-div"/>
            <div class="label-r"><span class="ll">Ürün:</span><span class="vv">${esc(data.product_code || data.product_name)}</span></div>
            <div class="label-r"><span class="ll">Barkod:</span><span class="vv">${esc(data.product_barcode)}</span></div>
            <hr class="label-div"/>
            <div class="label-r"><span class="ll">Terzi:</span><span class="vv" style="font-weight:bold;font-size:12px;">${esc(data.tailor_name)}</span></div>
            <hr class="label-div"/>
            <div class="label-section">YAPILACAK İŞLEMLER</div>
            ${servicesHtml}
            <hr class="label-div"/>
            ${_barcodeImg(data.name)}
            <div class="label-dt">${esc(data.date)}</div>
            <div class="label-note-main">${c.line1}</div>
            <div class="label-note-sub">${c.line2}</div>
            <div class="label-thanks">TEŞEKKÜR EDERİZ</div>
            ${data.notes ? `<hr class="label-div"/><div style="font-size:10px;"><b>Not:</b> ${esc(data.notes)}</div>` : ''}
        </div>
    `;
}

function _buildGiftLabel(data, company) {
    // Mağaza adı/adres/telefon şirket kaydından gelir (koda gömülü değil)
    const store = (company && company.name) || 'UĞURLAR';
    const address = company && company.address ? esc(company.address) : '';
    const phone = company && company.phone ? `Tel: ${esc(company.phone)}` : '';
    return `
        <div class="label">
            <div class="label-hdr" style="border-bottom:3px double #000;font-size:20px;letter-spacing:2px;">* HEDİYE FİŞİ *</div>
            <div class="label-store">${esc(store.toLocaleUpperCase('tr-TR'))}</div>
            <div style="text-align:center;font-size:9px;font-weight:600;line-height:1.4;margin-bottom:4px;">
                ${address}${address && phone ? '<br/>' : ''}${phone}
            </div>
            <hr class="label-div"/>
            <div style="text-align:center;font-size:14px;font-weight:900;padding:6px 4px;line-height:1.4;">
                Bu ürün size hediye edilmiştir.
            </div>
            <hr class="label-div"/>
            <div class="label-r"><span class="ll">Fiş No:</span><span class="vv" style="font-size:13px;font-weight:bold;">${esc(data.name)}</span></div>
            <div class="label-r"><span class="ll">Fatura No:</span><span class="vv">${esc(data.invoice_no)}</span></div>
            <hr class="label-div"/>
            <div class="label-r"><span class="ll">Ürün:</span><span class="vv">${esc(data.product_code || data.product_name)}</span></div>
            <div class="label-r"><span class="ll">Barkod:</span><span class="vv">${esc(data.product_barcode)}</span></div>
            <hr class="label-div"/>
            <div class="label-dt">${esc(data.date)}</div>
            <div style="margin-top:10px;padding:6px 4px;border:2px solid #000;border-radius:4px;">
                <div style="text-align:center;font-size:13px;font-weight:900;margin-bottom:4px;">DEĞİŞİM KOŞULLARI</div>
                <div style="font-size:11px;font-weight:600;line-height:1.5;">
                    * Değişim için bu fiş ile mağazamıza başvurunuz.<br/>
                    * Değişim süresi: Teslim tarihinden itibaren 14 gündür.<br/>
                    * Ürün kullanılmamış ve etiketli olmalıdır.
                </div>
            </div>
            ${data.notes ? `<hr class="label-div"/><div style="text-align:center;font-size:14px;font-weight:900;padding:6px 0;letter-spacing:1px;">${esc(data.notes)}</div>` : `<div style="text-align:center;font-size:18px;font-weight:900;margin-top:12px;padding:8px 0;letter-spacing:2px;">MUTLU GÜNLER DİLERİZ</div>`}
        </div>
    `;
}

function _buildCustomerSummaryLabel(dataArray) {
    // Musteri bilgisi ilk siparisten alinir (hepsi ayni musteri)
    const first = dataArray[0];

    // Her urun icin islemler listesi
    const itemsHtml = dataArray.map(d => {
        const svcs = d.services.map(s => `• ${esc(s.name)}`).join('<br/>');
        return `
            <div style="margin-bottom:8px; padding:6px; border:2px dashed #000; border-radius:4px;">
                <div style="font-weight:900;font-size:14px;">${esc(d.product_code || d.product_name)}</div>
                <div style="font-size:12px;font-weight:600;">(${esc(d.product_barcode)})</div>
                <div style="font-size:13px;font-weight:800;margin-top:3px;">Terzi: ${esc(d.tailor_name)}</div>
                <div style="font-size:12px;font-weight:600;margin-top:3px;">${svcs}</div>
            </div>
        `;
    }).join('');

    return `
        <div class="label">
            <div class="label-hdr">MÜŞTERİ NÜSHASI</div>
            <div class="label-store">UĞURLAR</div>
            <div class="label-sub">Terzi Takip Sistemi</div>
            <hr class="label-div"/>
            <div class="label-r"><span class="ll">Sipariş No:</span><span class="vv" style="font-size:13px;font-weight:bold;">${esc(dataArray.map(d => d.name).join(', '))}</span></div>
            <div class="label-r"><span class="ll">Fatura No:</span><span class="vv">${esc(first.invoice_no)}</span></div>
            <hr class="label-div"/>
            <div class="label-r"><span class="ll">Müşteri:</span><span class="vv">${esc(first.customer_name)}</span></div>
            ${first.customer_phone ? `<div class="label-r"><span class="ll">Müşteri No:</span><span class="vv">${esc(first.customer_phone)}</span></div>` : ''}
            ${first.sales_person ? `<div class="label-r"><span class="ll">Satış Per.:</span><span class="vv">${esc(first.sales_person)}</span></div>` : ''}
            <hr class="label-div"/>
            <div class="label-section">SİPARİŞ ÖZETİ (${dataArray.length} ürün)</div>
            ${itemsHtml}
            <hr class="label-div"/>
            ${first.promised_date ? `<div class="label-r" style="text-align:center;font-weight:900;font-size:14px;">Teslim: ${esc(first.promised_date)}</div>` : ''}
            <div class="label-dt">${esc(first.date)}</div>
            <div class="label-note-main">3. Nüsha müşteride kalacak</div>
            <div class="label-note-sub">İşlemler bittiğinde ürünlerinizi mağazamızdan teslim alabilirsiniz.</div>
            <div class="label-thanks">TEŞEKKÜR EDERİZ</div>
        </div>
    `;
}

function _printHtml(labelsHtml, title) {
    const html = `<!DOCTYPE html><html><head>
        <meta charset="utf-8">
        <title>${esc(title)}</title>
        <style>
            @page { size: 80mm auto; margin: 2mm; }
            * { margin:0; padding:0; box-sizing:border-box; }
            body {
                font-family: Arial, Helvetica, sans-serif;
                font-size: 13px;
                color: #000;
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
                text-rendering: geometricPrecision;
                -webkit-font-smoothing: none;
            }
            .label {
                width: 76mm;
                padding: 0;
                margin: 0 auto;
                page-break-after: always;
            }
            .label-hdr {
                text-align: center;
                padding: 8px 0;
                margin-bottom: 4px;
                color: #000;
                font-weight: 900;
                font-size: 18px;
                letter-spacing: 1px;
                border-bottom: 3px solid #000;
            }
            .label-store {
                text-align: center;
                font-size: 16px;
                font-weight: 900;
                margin-bottom: 2px;
            }
            .label-sub {
                text-align: center;
                font-size: 12px;
                font-weight: 600;
                margin-bottom: 4px;
            }
            .label-div {
                border: none;
                border-top: 2px dashed #000;
                margin: 5px 0;
            }
            .label-r {
                overflow: hidden;
                padding: 2px 0;
                line-height: 1.5;
                font-size: 13px;
            }
            .label-r .ll {
                font-weight: 800;
                float: left;
                width: 85px;
            }
            .label-r .vv {
                margin-left: 90px;
                font-weight: 600;
            }
            .label-section {
                font-weight: 900;
                text-align: center;
                padding: 4px 0;
                font-size: 14px;
                clear: both;
            }
            .label-dt {
                text-align: center;
                font-size: 12px;
                font-weight: 600;
                margin-top: 6px;
            }
            .label-note-main {
                text-align: center;
                font-size: 14px;
                font-weight: 900;
                margin-top: 10px;
                padding: 4px 0;
            }
            .label-note-sub {
                text-align: center;
                font-size: 11px;
                font-weight: 600;
                color: #000;
                padding: 2px 8px;
                line-height: 1.4;
            }
            .label-thanks {
                text-align: center;
                font-size: 16px;
                font-weight: 900;
                margin-top: 10px;
                padding: 6px 0;
                letter-spacing: 2px;
            }
            @media print {
                body { -webkit-print-color-adjust: exact !important; }
            }
        </style>
    </head><body>
        ${labelsHtml}
    </body></html>`;

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

    // Barkod görselleri yüklenmeden yazdırılırsa etikette boş kalır: yüklenmelerini bekle (en fazla 4 sn)
    const images = Array.from(doc.images || []);
    const loaded = images.map((img) => img.complete ? Promise.resolve() : new Promise((res) => {
        img.onload = img.onerror = res;
    }));
    Promise.race([Promise.all(loaded), new Promise((res) => setTimeout(res, 4000))]).then(() => {
        setTimeout(() => {
            iframe.contentWindow.focus();
            iframe.contentWindow.print();
        }, 200);
    });
}

/**
 * Tek siparis etiketi yazdir: 1x Terzi + 1x Magaza + 1x Musteri.
 */
export function printTailorLabel(data) {
    const terzi = _buildOrderLabel(data, 'terzi');
    const magaza = _buildOrderLabel(data, 'magaza');
    const musteri = _buildCustomerSummaryLabel([data]);
    _printHtml(terzi + magaza + musteri, `Terzi Etiket — ${data.name}`);
}

/**
 * Birden fazla siparis etiketi yazdir.
 * Her siparis icin 1x Terzi + 1x Magaza nushasi,
 * Sona tek bir MUSTERI OZET nushasi (tum urunler tek etikette).
 */
export function printMultipleTailorLabels(dataArray) {
    // Her siparis icin terzi + magaza nushalari
    let allLabels = '';
    for (const data of dataArray) {
        allLabels += _buildOrderLabel(data, 'terzi');
        allLabels += _buildOrderLabel(data, 'magaza');
    }

    // En sona tek bir musteri ozet nushasi
    allLabels += _buildCustomerSummaryLabel(dataArray);

    const names = dataArray.map(d => d.name).join(', ');
    _printHtml(allLabels, `Terzi Etiketler — ${names}`);
}

/**
 * SADECE hediye etiketi yazdir (bağımsız ekrandan).
 */
export function printGiftLabelOnly(dataArray, company = null) {
    let allLabels = '';
    for (const data of dataArray) {
        allLabels += _buildGiftLabel(data, company);
    }
    const names = dataArray.map(d => d.product_code || d.product_barcode || d.name).join(', ');
    _printHtml(allLabels, `Hediye Etiketi — ${names}`);
}
