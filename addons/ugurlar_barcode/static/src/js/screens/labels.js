/** @odoo-module **/

import { Component, useState, xml, markup } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class LabelScreen extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-print"></i> Etiket Yazdırma
                </h2>
            </div>

            <!-- ŞABLON SEÇİMİ -->
            <div class="ub-search-form">
                <div style="display:flex; gap:0.8rem; align-items:flex-end;">
                    <div class="ub-search-field" style="flex:1;">
                        <label class="ub-field-label">Etiket Şablonu</label>
                        <select class="form-control ub-select" t-on-change="onTemplateChange"
                                t-att-value="state.selectedTemplateId">
                            <option value="0">Varsayılan (mini)</option>
                            <t t-foreach="state.templates" t-as="t" t-key="t.id">
                                <option t-att-value="t.id" t-esc="t.name + ' (' + t.width_mm + '×' + t.height_mm + 'mm)'"/>
                            </t>
                        </select>
                    </div>
                    <button class="btn btn-sm" style="background:#714B67; color:#fff; white-space:nowrap; margin-bottom:2px; padding:0.5rem 0.8rem;"
                            t-on-click="openDesigner">
                        <i class="fa fa-paint-brush"></i> Tasarla
                    </button>
                </div>

                <div class="ub-search-field" style="margin-top:0.8rem;">
                    <label class="ub-field-label">Barkod Ekle</label>
                    <div class="ub-barcode-input-group">
                        <input type="text" class="form-control ub-barcode-input"
                               placeholder="Barkod okutun veya yazın..."
                               t-on-keydown="onKeyDown"
                               t-att-value="state.inputValue"
                               t-on-input="(ev) => this.state.inputValue = ev.target.value"/>
                        <button class="ub-scan-icon-btn" t-on-click="startCameraScan" title="Kamera ile tara">
                            <i class="fa fa-barcode"></i>
                        </button>
                        <button class="ub-scan-icon-btn" t-on-click="addBarcode" title="Ekle"
                                style="border-left:1px solid rgba(255,255,255,0.3); border-radius:0 8px 8px 0;">
                            <i class="fa fa-plus"></i>
                        </button>
                    </div>
                </div>

                <div style="margin-top:0.5rem; display:flex; gap:0.4rem;">
                    <label class="btn btn-sm btn-outline-secondary" style="margin:0; cursor:pointer; font-size:0.78rem;">
                        <i class="fa fa-file-excel-o"></i> Excel'den İçe Aktar
                        <input type="file" accept=".xlsx,.xls,.csv" style="display:none;"
                               t-on-change="onExcelImport"/>
                    </label>
                </div>
            </div>

            <!-- BARKOD LİSTESİ -->
            <t t-if="state.barcodes.length">
                <div class="ub-variants-section" style="margin-top:0.8rem;">
                    <div class="ub-section-title-dark">
                        <i class="fa fa-list"></i> Etiket Listesi (<t t-esc="state.barcodes.length"/>)
                    </div>
                    <div class="ub-variant-table-wrap">
                        <table class="ub-variant-table ub-variant-table-striped">
                            <thead>
                                <tr>
                                    <th>#</th>
                                    <th>Barkod</th>
                                    <th class="text-center">Adet</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                <t t-foreach="state.barcodes" t-as="item" t-key="item_index">
                                    <tr>
                                        <td t-esc="item_index + 1"/>
                                        <td class="ub-barcode-cell" t-esc="item.barcode"/>
                                        <td class="text-center">
                                            <div class="ub-count-input-group">
                                                <button class="btn btn-sm btn-outline-secondary"
                                                        t-on-click="() => this.changeQty(item_index, -1)">−</button>
                                                <input type="number" class="form-control ub-count-input"
                                                       t-att-value="item.qty"
                                                       t-on-change="(ev) => this.setQty(item_index, ev.target.value)"
                                                       style="width:50px;"/>
                                                <button class="btn btn-sm btn-outline-secondary"
                                                        t-on-click="() => this.changeQty(item_index, 1)">+</button>
                                            </div>
                                        </td>
                                        <td>
                                            <button class="btn btn-sm btn-outline-danger"
                                                    t-on-click="() => this.removeBarcode(item_index)">
                                                <i class="fa fa-times"></i>
                                            </button>
                                        </td>
                                    </tr>
                                </t>
                            </tbody>
                        </table>
                    </div>
                </div>

                <div class="ub-action-buttons" style="margin:0.8rem 1rem 0;">
                    <button class="btn ub-action-btn ub-action-stock" style="flex:1;"
                            t-on-click="generateLabels" t-att-disabled="state.loading">
                        <i class="fa fa-print"></i> Etiketleri Oluştur
                    </button>
                </div>
            </t>

            <t t-if="state.loading">
                <div class="ub-loading"><i class="fa fa-spinner fa-spin fa-2x"></i><p>Etiketler oluşturuluyor...</p></div>
            </t>

            <t t-if="state.error">
                <div class="ub-error-card"><i class="fa fa-exclamation-triangle"></i><p t-esc="state.error"/></div>
            </t>

            <!-- ETİKET ÖNİZLEME -->
            <t t-if="state.labels">
                <div class="ub-variants-section" style="margin-top:0.8rem;">
                    <div class="ub-section-title-dark">
                        <i class="fa fa-eye"></i> Etiket Önizleme (<t t-esc="state.labels.found"/> / <t t-esc="state.labels.total"/>)
                    </div>

                    <div style="padding:0.8rem; display:flex; flex-wrap:wrap; gap:0.8rem; justify-content:center;">
                        <t t-foreach="uniquePreviewLabels" t-as="pl" t-key="pl._idx">
                            <t t-if="pl.id and state.selectedTemplate">
                                <div class="ub-label-preview-card"
                                     t-attf-style="width:{{state.selectedTemplate.width_mm * 3}}px; height:{{state.selectedTemplate.height_mm * 3}}px;">
                                    <div t-out="getPreviewHtml(pl)"/>
                                    <div class="ub-label-qty-badge" t-if="pl.qty > 1">×<t t-esc="pl.qty"/></div>
                                </div>
                            </t>
                            <t t-if="pl.id and !state.selectedTemplate">
                                <div class="ub-label-card">
                                    <div class="ub-label-card-top">
                                        <div class="ub-label-name" t-esc="pl.name"/>
                                        <div class="ub-label-code" t-if="pl.nebim_code" t-esc="pl.nebim_code"/>
                                    </div>
                                    <div class="ub-label-barcode-display">
                                        <i class="fa fa-barcode fa-2x"></i>
                                        <span t-esc="pl.barcode"/>
                                    </div>
                                    <div class="ub-label-price">₺<t t-esc="pl.list_price"/></div>
                                    <div style="font-size:0.75rem;color:#888;margin-top:0.3rem;" t-if="pl.qty > 1">
                                        × <t t-esc="pl.qty"/> adet
                                    </div>
                                </div>
                            </t>
                            <div class="ub-error-card" t-if="pl.error" style="margin: 0.5rem 1rem;">
                                <span t-esc="pl.barcode"/> — <span t-esc="pl.error"/>
                            </div>
                        </t>
                    </div>
                </div>

                <div class="ub-action-buttons" style="margin:0.8rem 1rem 0;">
                    <button class="btn ub-action-btn" style="flex:1; background:linear-gradient(135deg,#27ae60,#2ecc71);"
                            t-on-click="printLabels">
                        <i class="fa fa-print"></i> Yazdır
                    </button>
                </div>
            </t>
        </div>
    `;

    static props = { navigate: Function, scanner: Object };

    setup() {
        this.state = useState({
            inputValue: '',
            barcodes: [],  // {barcode, qty}
            loading: false,
            error: null,
            labels: null,
            previewLabels: [],
            templates: [],
            selectedTemplateId: 0,
            selectedTemplate: null,
        });
        this._unsub = this.props.scanner.onScan(bc => {
            this._addBc(bc);
        });
        this.loadTemplates();
    }

    async loadTemplates() {
        try {
            const res = await BarcodeService.labelTemplateList();
            this.state.templates = res.templates || [];
            const def = this.state.templates.find(t => t.is_default);
            if (def) {
                this.state.selectedTemplateId = def.id;
                this.state.selectedTemplate = def;
            }
        } catch (e) { /* sessiz */ }
    }

    onTemplateChange(ev) {
        const id = parseInt(ev.target.value);
        this.state.selectedTemplateId = id;
        this.state.selectedTemplate = this.state.templates.find(t => t.id === id) || null;
    }

    openDesigner() {
        this.props.navigate('label_designer');
    }

    onKeyDown(ev) {
        if (ev.key === 'Enter' && this.state.inputValue.trim()) {
            ev.preventDefault();
            this.addBarcode();
        }
    }

    addBarcode() {
        const bc = this.state.inputValue.trim();
        if (bc) { this._addBc(bc); this.state.inputValue = ''; }
    }

    _addBc(bc) {
        const existing = this.state.barcodes.find(b => b.barcode === bc);
        if (existing) { existing.qty++; }
        else { this.state.barcodes.push({ barcode: bc, qty: 1 }); }
    }

    // ─── KAMERA İLE BARKOD OKUTMA (iOS + Android) ─────
    async startCameraScan() {
        const useNative = 'BarcodeDetector' in window;
        // iOS/Safari fallback: html5-qrcode CDN yükle
        if (!useNative && !window.Html5Qrcode) {
            try {
                await new Promise((resolve, reject) => {
                    const s = document.createElement('script');
                    s.src = 'https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js';
                    s.onload = resolve;
                    s.onerror = () => reject(new Error('Kütüphane yüklenemedi'));
                    document.head.appendChild(s);
                });
            } catch (e) {
                alert('Barkod tarayıcı yüklenemedi. Lütfen barkodu manuel girin.');
                return;
            }
        }

        const overlay = document.createElement('div');
        overlay.className = 'ub-camera-overlay';
        overlay.innerHTML = `
            <div class="ub-camera-header">
                <span>Seri Barkod Okutma</span>
                <button class="ub-camera-close-btn" id="ub-cam-close">✕ Kapat</button>
            </div>
            ${useNative ? '<video id="ub-cam-video" autoplay playsinline muted></video>' : '<div id="ub-cam-reader" style="width:100%;"></div>'}
            <div class="ub-camera-target"></div>
            <div class="ub-camera-status" id="ub-cam-status">Kamera başlatılıyor...</div>
            <div class="ub-scan-counter" id="ub-scan-counter" style="position:fixed; bottom:80px; left:50%; transform:translateX(-50%); background:rgba(0,0,0,0.7); color:#fff; padding:8px 20px; border-radius:20px; font-size:14px; font-weight:bold; z-index:100002; display:none;">
                <i class="fa fa-check-circle" style="color:#4CAF50;"></i> <span id="ub-scan-count">0</span> barkod eklendi
            </div>
            <div class="ub-scan-flash" id="ub-scan-flash" style="position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(76,175,80,0.3); z-index:100001; pointer-events:none; opacity:0; transition:opacity 0.15s;"></div>
        `;
        document.body.appendChild(overlay);

        const statusEl = document.getElementById('ub-cam-status');
        const counterEl = document.getElementById('ub-scan-counter');
        const countSpan = document.getElementById('ub-scan-count');
        const flashEl = document.getElementById('ub-scan-flash');
        let stream = null;
        let animFrame = null;
        let html5QrCode = null;
        let scanning = true;
        let scanCount = 0;
        let lastScannedCode = '';
        let cooldownUntil = 0;

        const cleanup = () => {
            scanning = false;
            if (animFrame) cancelAnimationFrame(animFrame);
            if (stream) stream.getTracks().forEach(t => t.stop());
            if (html5QrCode) { try { html5QrCode.stop(); } catch(e) {} }
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        };

        const onScanSuccess = (barcode) => {
            const now = Date.now();
            if (now < cooldownUntil) return;
            if (barcode === lastScannedCode && now - cooldownUntil < 500) return;
            lastScannedCode = barcode;
            cooldownUntil = now + 1500;

            if (navigator.vibrate) navigator.vibrate(150);
            flashEl.style.opacity = '1';
            setTimeout(() => { flashEl.style.opacity = '0'; }, 200);

            this._addBc(barcode);
            scanCount++;
            countSpan.textContent = scanCount;
            counterEl.style.display = 'block';
            statusEl.textContent = `✓ ${barcode} eklendi — Sonraki barkodu gösterin...`;
            statusEl.style.color = '#4CAF50';
            setTimeout(() => {
                if (scanning) {
                    statusEl.textContent = 'Barkodları sırayla kameraya gösterin...';
                    statusEl.style.color = '';
                }
            }, 1200);
        };

        document.getElementById('ub-cam-close').onclick = cleanup;

        if (useNative) {
            // ─── Chrome/Android: Native BarcodeDetector ─────
            const video = document.getElementById('ub-cam-video');
            navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
            }).then(s => {
                stream = s;
                video.srcObject = stream;
                statusEl.textContent = 'Barkodları sırayla kameraya gösterin...';

                const detector = new BarcodeDetector({
                    formats: ['ean_13', 'ean_8', 'code_128', 'code_39', 'upc_a', 'upc_e', 'itf', 'qr_code']
                });

                const scanFrame = async () => {
                    if (!scanning || video.readyState < 2) {
                        animFrame = requestAnimationFrame(scanFrame);
                        return;
                    }
                    try {
                        const now = Date.now();
                        if (now < cooldownUntil) { animFrame = requestAnimationFrame(scanFrame); return; }
                        const barcodes = await detector.detect(video);
                        if (barcodes.length > 0) onScanSuccess(barcodes[0].rawValue);
                    } catch (e) {}
                    animFrame = requestAnimationFrame(scanFrame);
                };
                video.onloadedmetadata = () => scanFrame();
            }).catch(err => {
                statusEl.textContent = 'Kamera erişimi reddedildi: ' + err.message;
                setTimeout(cleanup, 3000);
            });
        } else {
            // ─── iOS/Safari: html5-qrcode fallback ─────
            try {
                html5QrCode = new Html5Qrcode('ub-cam-reader');
                statusEl.textContent = 'Barkodları sırayla kameraya gösterin...';
                html5QrCode.start(
                    { facingMode: 'environment' },
                    { fps: 10, qrbox: { width: 280, height: 120 }, aspectRatio: 1.777 },
                    (decodedText) => onScanSuccess(decodedText),
                    () => {} // hata — sessiz devam
                ).catch(err => {
                    statusEl.textContent = 'Kamera başlatılamadı: ' + err;
                    setTimeout(cleanup, 3000);
                });
            } catch (err) {
                statusEl.textContent = 'Tarayıcı hatası: ' + err.message;
                setTimeout(cleanup, 3000);
            }
        }
    }

    removeBarcode(index) { this.state.barcodes.splice(index, 1); }
    changeQty(index, delta) {
        const item = this.state.barcodes[index];
        item.qty = Math.max(1, item.qty + delta);
    }
    setQty(index, val) {
        this.state.barcodes[index].qty = Math.max(1, parseInt(val) || 1);
    }

    // Excel/CSV dosyasından barkod okuma
    async onExcelImport(ev) {
        const file = ev.target.files[0];
        if (!file) return;
        ev.target.value = ''; // reset

        const isCSV = file.name.toLowerCase().endsWith('.csv');

        if (isCSV) {
            const reader = new FileReader();
            reader.onload = (e) => this._parseCSV(e.target.result);
            reader.readAsText(file);
        } else {
            // XLSX — SheetJS kütüphanesini yükle
            try {
                await this._loadSheetJS();
                const reader = new FileReader();
                reader.onload = (e) => this._parseXLSX(e.target.result);
                reader.readAsArrayBuffer(file);
            } catch (err) {
                alert('Excel kütüphanesi yüklenemedi. Lütfen dosyayı CSV olarak kaydedin.');
            }
        }
    }

    _loadSheetJS() {
        return new Promise((resolve, reject) => {
            if (window.XLSX) { resolve(); return; }
            const script = document.createElement('script');
            script.src = 'https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js';
            script.onload = () => resolve();
            script.onerror = () => reject(new Error('SheetJS yüklenemedi'));
            document.head.appendChild(script);
        });
    }

    _parseCSV(text) {
        const lines = text.split(/\r?\n/).filter(l => l.trim());
        if (!lines.length) { alert('Dosya boş'); return; }

        let barcodeCol = 0;
        const header = lines[0].split(/[,;\t]/);
        const bcIdx = header.findIndex(h =>
            /barkod|barcode|ean|upc/i.test(h.trim())
        );
        const startRow = bcIdx >= 0 ? 1 : 0;
        if (bcIdx >= 0) barcodeCol = bcIdx;

        let added = 0;
        for (let i = startRow; i < lines.length; i++) {
            const cols = lines[i].split(/[,;\t]/);
            const bc = (cols[barcodeCol] || '').trim().replace(/['"]/g, '');
            if (bc && bc.length >= 4 && /^[0-9A-Za-z-]+$/.test(bc)) {
                this._addBc(bc);
                added++;
            }
        }
        alert(`${added} barkod eklendi`);
    }

    _parseXLSX(buffer) {
        try {
            const wb = window.XLSX.read(buffer, { type: 'array' });
            const sheet = wb.Sheets[wb.SheetNames[0]];
            const data = window.XLSX.utils.sheet_to_json(sheet, { header: 1, raw: false });

            if (!data.length) { alert('Excel dosyası boş'); return; }

            // Başlık satırında barkod sütununu bul
            const header = data[0] || [];
            let barcodeCol = -1;
            for (let c = 0; c < header.length; c++) {
                const h = String(header[c] || '').toLowerCase();
                if (/barkod|barcode|ean|upc|barkot/.test(h)) {
                    barcodeCol = c;
                    break;
                }
            }

            // Başlık bulunamadıysa, 8-14 haneli sayısal veri içeren sütunu bul
            let startRow = 0;
            if (barcodeCol >= 0) {
                startRow = 1;
            } else {
                for (let c = 0; c < (header.length || 1); c++) {
                    // İlk birkaç satıra bak, barkod benzeri veri var mı
                    for (let r = 0; r < Math.min(5, data.length); r++) {
                        const val = String(data[r]?.[c] || '').trim();
                        if (/^[0-9]{8,14}$/.test(val)) {
                            barcodeCol = c;
                            break;
                        }
                    }
                    if (barcodeCol >= 0) break;
                }
                if (barcodeCol < 0) barcodeCol = 0;
            }

            let added = 0;
            for (let i = startRow; i < data.length; i++) {
                const row = data[i];
                if (!row) continue;
                const bc = String(row[barcodeCol] || '').trim().replace(/['"]/g, '').replace(/\.0$/, '');
                if (bc && bc.length >= 4 && /^[0-9A-Za-z-]+$/.test(bc)) {
                    this._addBc(bc);
                    added++;
                }
            }
            alert(`${added} barkod eklendi`);
        } catch (e) {
            alert('Excel dosyası okunamadı: ' + e.message);
        }
    }

    async generateLabels() {
        this.state.loading = true;
        this.state.error = null;
        this.state.labels = null;
        this.state.previewLabels = [];
        try {
            const uniqueBarcodes = this.state.barcodes.map(b => b.barcode);
            const result = await BarcodeService.labelData(uniqueBarcodes);
            if (result.error) { this.state.error = result.error; }
            else {
                this.state.labels = result;
                // Preview etiketlerini qty ile çarp
                const previews = [];
                let idx = 0;
                for (const bc of this.state.barcodes) {
                    const label = result.labels.find(l => l.barcode === bc.barcode);
                    if (label) {
                        for (let i = 0; i < bc.qty; i++) {
                            previews.push({ ...label, qty: bc.qty, _idx: idx++ });
                        }
                    }
                }
                // Bulunamayan barkodlar
                for (const l of result.labels) {
                    if (l.error) previews.push({ ...l, _idx: idx++ });
                }
                this.state.previewLabels = previews;
            }
        } catch (e) {
            this.state.error = 'Hata: ' + (e.message || e);
        }
        this.state.loading = false;
    }

    // Her barkod için tek önizleme (adet badge ayrı gösterilir)
    get uniquePreviewLabels() {
        const seen = new Set();
        const unique = [];
        for (const pl of this.state.previewLabels) {
            const key = pl.barcode || pl._idx;
            if (!seen.has(key)) {
                seen.add(key);
                unique.push(pl);
            }
        }
        return unique;
    }

    // Şablona göre önizleme HTML'i üret
    getPreviewHtml(label) {
        const tpl = this.state.selectedTemplate;
        if (!tpl || !tpl.elements || !tpl.elements.length) return '';

        const scale = 3; // px per mm for preview
        const html = tpl.elements.map(el => {
            if (el.type === 'barcode_visual') {
                const img = `<img src="/report/barcode/Code128/${encodeURIComponent(label.barcode || '123456')}?width=800&amp;height=200" style="width:100%; height:100%; object-fit:fill;" />`;
                return `<div style="position:absolute; left:${el.x * scale}px; top:${el.y * scale}px; width:${el.width * scale}px; height:${el.height * scale}px; overflow:hidden;">${img}</div>`;
            }
            if (el.type === 'line') {
                return `<div style="position:absolute; left:${el.x * scale}px; top:${el.y * scale}px; width:${el.width * scale}px; border-top:${Math.max(1, el.height * scale)}px solid #333;"></div>`;
            }
            const val = this._getFieldValue(el, label);
            if (!val) return '';
            const fs = Math.max(6, el.fontSize * scale * 0.28);
            return `<div style="position:absolute; left:${el.x * scale}px; top:${el.y * scale}px; width:${el.width * scale}px; height:${el.height * scale}px; font-size:${fs}px; font-weight:${el.fontWeight}; text-align:${el.textAlign}; overflow:hidden; line-height:1.2; white-space:pre-wrap; word-break:break-word; text-overflow:ellipsis;">${val}</div>`;
        }).join('');
        return markup(html);
    }
    printLabels() {
        const allLabels = this.state.previewLabels.filter(l => l.id);
        if (!allLabels.length) return;

        const template = this.state.selectedTemplate;
        let html;

        if (template && template.elements && template.elements.length) {
            html = this._buildTemplateHtml(allLabels, template);
        } else {
            html = this._buildDefaultHtml(allLabels);
        }

        const printWindow = window.open('', '_blank');
        printWindow.document.write(html);
        printWindow.document.close();
        printWindow.focus();
        setTimeout(() => printWindow.print(), 300);
    }

    _generateBarcodeImg(code, widthMm, heightMm) {
        if (!code) return '';
        // 300 DPI: 1mm ≈ 11.8px → widthMm * 12 ve heightMm * 12 ile yüksek çözünürlük
        const imgW = Math.round(widthMm * 12);
        const imgH = Math.round(heightMm * 12);
        return `<img src="/report/barcode/Code128/${encodeURIComponent(code)}?width=${imgW}&amp;height=${imgH}&amp;humanreadable=1" style="width:${widthMm}mm; height:${heightMm}mm; display:block; object-fit:fill; image-rendering:-moz-crisp-edges; image-rendering:-webkit-crisp-edges; image-rendering:pixelated;"/>`;
    }

    _getFieldValue(el, label) {
        const attrs = label.attributes || {};

        // attr_ prefix olan tüm nitelikleri dinamik çöz
        if (el.type.startsWith('attr_')) {
            if (el.type === 'attr_custom' && el.content) {
                return attrs[el.content] || '';
            }
            const attrName = el.type.replace('attr_', '');
            return attrs[attrName] || '';
        }

        const fieldMap = {
            product_name: label.name || '',
            barcode: label.barcode || '',
            list_price: '₺' + (label.list_price || 0),
            standard_price: '₺' + (label.standard_price || 0),
            default_code: label.default_code || '',
            nebim_code: label.nebim_code || '',
            nebim_variant_code: label.nebim_variant_code || '',
            nebim_color_code: label.nebim_color_code || '',
            category: label.category || '',
            marka: label.marka || '',
            weight: (label.weight || 0) + ' kg',
            uom: label.uom || 'Adet',
            description: label.description || '',
            custom_text: el.content || '',
            company_name: el.content || 'Uğurlar',
            date_today: new Date().toLocaleDateString('tr-TR'),
        };
        return fieldMap[el.type] || '';
    }

    _buildTemplateHtml(labels, tpl) {
        const w = tpl.width_mm;
        const h = tpl.height_mm;
        const elems = tpl.elements || [];

        const labelHtml = labels.map(l => {
            const contents = elems.map(el => {
                if (el.type === 'barcode_visual') {
                    const img = this._generateBarcodeImg(l.barcode || '', el.width, el.height);
                    return `<div style="position:absolute; left:${el.x}mm; top:${el.y}mm; width:${el.width}mm; height:${el.height}mm; overflow:visible;">${img}</div>`;
                }
                if (el.type === 'line') {
                    return `<div style="position:absolute; left:${el.x}mm; top:${el.y}mm; width:${el.width}mm; height:0; border-top:${Math.max(0.3, el.height)}mm solid #000;"></div>`;
                }
                const val = this._getFieldValue(el, l);
                if (!val) return '';
                return `<div style="position:absolute; left:${el.x}mm; top:${el.y}mm; width:${el.width}mm; height:${el.height}mm; font-size:${el.fontSize}pt; font-weight:${el.fontWeight}; text-align:${el.textAlign || 'left'}; overflow:hidden; line-height:1.2; white-space:pre-wrap; word-break:break-word;">${val}</div>`;
            }).join('');
            return `<div class="label">${contents}</div>`;
        }).join('');

        return `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Etiketler</title><style>
            @page { size: auto; margin: 0 !important; }
            * { margin: 0; padding: 0; box-sizing: border-box; }
            html, body {
                margin: 0; padding: 0;
                font-family: Arial, Helvetica, sans-serif;
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
            }
            .label {
                width: ${w}mm; height: ${h}mm;
                position: relative; overflow: hidden;
                page-break-after: always; page-break-inside: avoid;
            }
            .label:last-child { page-break-after: auto; }
            img { image-rendering: pixelated; image-rendering: -moz-crisp-edges; -ms-interpolation-mode: nearest-neighbor; }
            @media print { @page { size: auto; margin: 0 !important; } html, body { margin:0!important; padding:0!important; } }
        </style></head><body>${labelHtml}</body></html>`;
    }

    _buildDefaultHtml(labels) {
        const w = 60, h = 40;
        return `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Etiketler</title><style>
            @page { size: auto; margin: 0 !important; }
            * { margin: 0; padding: 0; box-sizing: border-box; }
            html, body {
                margin: 0; padding: 0;
                font-family: Arial, Helvetica, sans-serif;
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
            }
            .label {
                width: ${w}mm; height: ${h}mm;
                padding: 2mm 3mm;
                page-break-after: always; page-break-inside: avoid;
                display: flex; flex-direction: column;
                justify-content: center; align-items: center; text-align: center;
            }
            .label:last-child { page-break-after: auto; }
            .label-name { font-size: 8pt; font-weight: bold; margin-bottom: 1mm; line-height: 1.2; }
            .label-code { font-size: 6pt; color: #444; margin-bottom: 1mm; }
            .label-barcode-wrap { margin: 1mm 0; }
            .label-price { font-size: 11pt; font-weight: bold; margin-top: 1mm; }
            img { image-rendering: pixelated; image-rendering: -moz-crisp-edges; -ms-interpolation-mode: nearest-neighbor; }
            @media print { @page { size: auto; margin: 0 !important; } html, body { margin:0!important; padding:0!important; } }
        </style></head><body>${labels.map(l => `
            <div class="label">
                <div class="label-name">${l.name}</div>
                <div class="label-code">${l.default_code || l.nebim_code || ''}</div>
                <div class="label-barcode-wrap">${this._generateBarcodeImg(l.barcode, 46, 14)}</div>
                <div class="label-price">₺${l.list_price}</div>
            </div>
        `).join('')}</body></html>`;
    }

    willUnmount() { if (this._unsub) this._unsub(); }
}

