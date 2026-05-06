/** @odoo-module **/

import { Component, useState, xml, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

// ─── KARGO ETİKETİ ALAN TİPLERİ ──────────────────
const CARGO_FIELD_TYPES = [
    // Sipariş
    { type: 'order_number',      label: 'Sipariş No',        icon: 'fa-hashtag',      color: '#714B67', group: 'order' },
    { type: 'picking_name',      label: 'Picking No',        icon: 'fa-file-text',    color: '#8e44ad', group: 'order' },
    { type: 'origin',            label: 'Kaynak (SO)',        icon: 'fa-link',         color: '#2c3e50', group: 'order' },
    { type: 'marketplace',       label: 'Pazaryeri',          icon: 'fa-shopping-bag', color: '#e67e22', group: 'order' },
    // Müşteri
    { type: 'customer_name',     label: 'Müşteri Adı',       icon: 'fa-user',         color: '#2980b9', group: 'customer' },
    { type: 'partner_phone',     label: 'Telefon',            icon: 'fa-phone',        color: '#27ae60', group: 'customer' },
    { type: 'shipping_address',  label: 'Teslimat Adresi',   icon: 'fa-map-marker',   color: '#e74c3c', group: 'customer' },
    { type: 'shipping_city',     label: 'İl',                 icon: 'fa-building',     color: '#16a085', group: 'customer' },
    { type: 'shipping_district', label: 'İlçe',               icon: 'fa-map-pin',      color: '#1abc9c', group: 'customer' },
    // Kargo
    { type: 'cargo_tracking',    label: 'Kargo Takip No',    icon: 'fa-truck',        color: '#c0392b', group: 'cargo' },
    { type: 'cargo_barcode',     label: 'Kargo Takip Barkod',icon: 'fa-barcode',      color: '#d35400', group: 'cargo' },
    { type: 'cargo_provider',    label: 'Kargo Firması',     icon: 'fa-building-o',   color: '#f39c12', group: 'cargo' },
    // Ürünler
    { type: 'item_list',         label: 'Ürün Listesi',      icon: 'fa-list',         color: '#34495e', group: 'items' },
    { type: 'total_qty',         label: 'Toplam Adet',       icon: 'fa-cubes',        color: '#7f8c8d', group: 'items' },
    { type: 'total_items',       label: 'Ürün Çeşidi',       icon: 'fa-th',           color: '#95a5a6', group: 'items' },
    // Diğer
    { type: 'sender_name',       label: 'Gönderici Adı',     icon: 'fa-industry',     color: '#555',    group: 'other' },
    { type: 'custom_text',       label: 'Serbest Metin',     icon: 'fa-pencil',       color: '#2c3e50', group: 'other' },
    { type: 'date_today',        label: 'Bugün Tarihi',      icon: 'fa-calendar',     color: '#999',    group: 'other' },
    { type: 'line',              label: 'Çizgi',              icon: 'fa-minus',        color: '#aaa',    group: 'other' },
    { type: 'cargo_qr_code',     label: 'QR Karekod',        icon: 'fa-qrcode',       color: '#8e44ad', group: 'cargo' },
    { type: 'box',               label: 'Kutu / Çerçeve',    icon: 'fa-square-o',     color: '#7f8c8d', group: 'other' },
    // Nebim
    { type: 'nebim_invoice_no',   label: 'Nebim Fatura No',   icon: 'fa-file-text-o',  color: '#e74c3c', group: 'nebim' },
    { type: 'nebim_invoice_date', label: 'Nebim Fatura Tarihi', icon: 'fa-calendar-o', color: '#c0392b', group: 'nebim' },
];

const CARGO_GROUPS = [
    { id: 'order',    label: 'Sipariş' },
    { id: 'customer', label: 'Müşteri' },
    { id: 'cargo',    label: 'Kargo' },
    { id: 'items',    label: 'Ürünler' },
    { id: 'nebim',    label: 'Nebim' },
    { id: 'other',    label: 'Diğer' },
];

const MM_TO_PX = 3.78;

export class CargoLabelDesigner extends Component {
    static template = xml`
        <div class="ub-screen ub-designer-app" style="padding-bottom:0;" t-on-keydown="onKeyDown" tabindex="0">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="onBack"><i class="fa fa-arrow-left"></i></button>
                <h2 class="ub-screen-title"><i class="fa fa-paint-brush"></i> Kargo Etiket Tasarımcısı</h2>
                <div style="margin-left:auto; display:flex; gap:0.5rem;">
                    <div class="ub-zoom-controls" style="margin-right:1rem;">
                        <button class="ub-zoom-btn" t-on-click="zoomOut"><i class="fa fa-minus"></i></button>
                        <span class="ub-zoom-label" t-esc="Math.round(state.zoom * 100) + '%'"/>
                        <button class="ub-zoom-btn" t-on-click="zoomIn"><i class="fa fa-plus"></i></button>
                    </div>
                    <button class="btn btn-sm btn-outline-secondary" style="margin-right:0.5rem; border-radius:6px; background:#fff;"
                            t-on-click="() => this.state.previewMode = !this.state.previewMode" title="Önizleme Modu">
                        <i t-attf-class="fa {{state.previewMode ? 'fa-pencil' : 'fa-eye'}}"></i> <t t-esc="state.previewMode ? 'DÜZENLE' : 'ÖNİZLE'"/>
                    </button>
                    <button class="btn btn-sm btn-primary" style="background:#6366F1;border-color:#6366F1;padding:0.4rem 1.2rem;font-weight:600;letter-spacing:0.5px; border-radius:6px;"
                            t-on-click="onSave"><i class="fa fa-save"></i> TASARIMI KAYDET</button>
                </div>
            </div>

            <div class="ub-designer-main-area">
                
                <!-- SOL PANEL: Araç Çubuğu -->
                <div class="ub-designer-left-panel">
                    <div class="ub-designer-panel-title">Bileşenler</div>
                    <div style="padding: 0 1rem 0.5rem 1rem;">
                        <input type="text" class="form-control form-control-sm" placeholder="Bileşen ara..." t-att-value="state.searchQuery" t-on-input="(ev) => this.state.searchQuery = ev.target.value.toLowerCase()" style="border-radius:6px; font-size:0.8rem;"/>
                    </div>
                    <div class="ub-designer-tools">
                        <t t-foreach="groups" t-as="g" t-key="g.id">
                            <t t-set="groupFields" t-value="getGroupFields(g.id).filter(ft => ft.label.toLowerCase().includes(state.searchQuery || ''))"/>
                            <div t-if="groupFields.length > 0">
                                <span class="ub-tool-group-label" t-esc="g.label"/>
                                <t t-foreach="groupFields" t-as="ft" t-key="ft.type">
                                    <button class="ub-tool-btn" t-on-click="() => this.addElement(ft.type)" t-att-title="ft.label">
                                        <i t-attf-class="fa {{ft.icon}}" t-attf-style="color:{{ft.color}}"></i>
                                        <t t-esc="ft.label"/>
                                    </button>
                                </t>
                            </div>
                        </t>
                    </div>
                </div>

                <!-- ORTA: Canvas ve Üstünde Şablon Ayarları -->
                <div class="ub-designer-center-area">
                    <div class="ub-tpl-toolbar">
                        <select style="width:auto;min-width:180px;" t-on-change="onLoadTemplate">
                            <option value="">✨ Yeni Tasarım Olarak Başla</option>
                            <t t-foreach="state.templates" t-as="t" t-key="t.id">
                                <option t-att-value="t.id" t-att-selected="state.editingId === t.id" t-esc="t.name"/>
                            </t>
                        </select>
                        <input class="ub-tpl-name" type="text" placeholder="Tasarım / Şablon Adı"
                               t-att-value="state.templateName" t-on-input="(ev) => this.state.templateName = ev.target.value"/>
                        
                        <div style="display:flex;align-items:center;gap:0.3rem;margin-left:auto;">
                            <input class="ub-tpl-dim" type="number" title="Genişlik mm"
                                   t-att-value="state.widthMm" t-on-change="(ev) => this.setDimension('w', ev.target.value)"/>
                            <span style="font-size:0.8rem;color:#6B7280;">×</span>
                            <input class="ub-tpl-dim" type="number" title="Yükseklik mm"
                                   t-att-value="state.heightMm" t-on-change="(ev) => this.setDimension('h', ev.target.value)"/>
                            <span style="font-size:0.75rem;color:#6B7280;margin-right:0.5rem;">mm</span>
                            <button class="btn btn-sm btn-outline-info" style="border-radius:6px;" t-on-click="exportTemplate" title="Tasarımı Dışa Aktar"><i class="fa fa-download"></i></button>
                            <label class="btn btn-sm btn-outline-info" style="border-radius:6px; margin:0; cursor:pointer;" title="Tasarımı İçe Aktar"><i class="fa fa-upload"></i><input type="file" accept=".json" style="display:none;" t-on-change="importTemplate"/></label>
                            <button class="btn btn-sm btn-outline-danger" t-if="state.editingId" style="border-radius:6px;"
                                    t-on-click="onDelete" title="Sil"><i class="fa fa-trash"></i> Sil</button>
                        </div>
                    </div>

                    <div class="ub-designer-canvas-area" t-ref="canvasArea"
                         t-on-mousedown="onCanvasMouseDown" t-on-touchstart="onCanvasTouchStart">
                        <div t-attf-class="ub-designer-paper {{state.previewMode ? 'preview-mode' : ''}}" t-ref="paper"
                             t-attf-style="width:{{paperW}}px; height:{{paperH}}px; transform:scale({{state.zoom}}); transform-origin:center center;">
                            <div class="ub-designer-grid" t-attf-style="background-size:{{gridSize}}px {{gridSize}}px; {{state.previewMode ? 'display:none;' : ''}}"></div>
                            <t t-if="!state.previewMode">
                                <t t-foreach="state.guideLines || []" t-as="guide" t-key="guide_index">
                                    <div t-if="guide.type === 'vertical'" class="ub-guide-line-v" t-attf-style="left:{{guide.pos * mmPx}}px; top:{{guide.start * mmPx}}px; height:{{(guide.end - guide.start) * mmPx}}px;"></div>
                                    <div t-if="guide.type === 'horizontal'" class="ub-guide-line-h" t-attf-style="top:{{guide.pos * mmPx}}px; left:{{guide.start * mmPx}}px; width:{{(guide.end - guide.start) * mmPx}}px;"></div>
                                </t>
                            </t>
                            <t t-foreach="state.elements" t-as="el" t-key="el.id">
                                <div t-attf-class="ub-design-element {{state.selectedId === el.id and !state.previewMode ? 'ub-el-selected' : ''}} {{el.type === 'line' ? 'ub-el-line' : ''}} {{el.type === 'box' ? 'ub-el-box' : ''}}"
                                     t-attf-style="left:{{el.x * mmPx}}px; top:{{el.y * mmPx}}px; width:{{el.width * mmPx}}px; height:{{el.height * mmPx}}px; font-size:{{el.fontSize}}pt; font-weight:{{el.fontWeight}}; text-align:{{el.textAlign}}; transform: rotate({{el.rotation || 0}}deg); color: {{el.color || '#000000'}}; background-color: {{el.bgColor || 'transparent'}}; border: {{el.type === 'box' ? ((el.borderWidth || 1) + 'px solid ' + (el.color || '#000000')) : (state.previewMode ? 'none' : '')}};"
                                     t-on-mousedown.stop="(ev) => !state.previewMode and this.onElMouseDown(ev, el)"
                                     t-on-touchstart.stop="(ev) => !state.previewMode and this.onElTouchStart(ev, el)">
                                    <t t-if="!state.previewMode">
                                        <span class="ub-el-type-badge" t-esc="getFieldLabel(el.type)"/>
                                    </t>
                                    
                                    <t t-if="el.type === 'cargo_qr_code'">
                                        <img t-attf-src="/report/barcode/?type=QR&amp;value={{el.content || '123456789'}}" style="width:100%; height:100%; object-fit:contain;" />
                                    </t>
                                    <t t-elif="el.type === 'cargo_barcode'">
                                        <img t-attf-src="/report/barcode/Code128/{{state.previewMode ? '8880031736932' : 'BARCODE123'}}?width=600&amp;height=150" style="width:100%; height:100%; object-fit:fill; display:block;" />
                                    </t>
                                    <t t-elif="el.type === 'item_list' and state.previewMode">
                                        <div class="ub-el-content" style="width:100%; height:100%; overflow:hidden;">
                                            <table style="width:100%; border-collapse:collapse; font-size:inherit;">
                                                <thead><tr style="border-bottom:1px solid #333;">
                                                    <th style="text-align:left;padding:0 1px;">#</th>
                                                    <th style="text-align:left;padding:0 1px;">Kod</th>
                                                    <th style="text-align:left;padding:0 1px;">Açıklama</th>
                                                    <th style="text-align:right;padding:0 1px;">Adet</th>
                                                </tr></thead>
                                                <tbody>
                                                    <tr><td>1</td><td>26YMDV088</td><td>Polo Gömlek</td><td style="text-align:right;">3</td></tr>
                                                    <tr><td>2</td><td>34KZJN012</td><td>Jean Pantolon</td><td style="text-align:right;">1</td></tr>
                                                </tbody>
                                            </table>
                                        </div>
                                    </t>
                                    <t t-elif="el.type !== 'line' and el.type !== 'box'">
                                        <span class="ub-el-content" t-esc="getPreviewText(el)"/>
                                    </t>

                                    <t t-if="!state.previewMode">
                                        <div class="ub-el-resize"
                                             t-on-mousedown.stop="(ev) => this.onResizeMouseDown(ev, el)"
                                             t-on-touchstart.stop="(ev) => this.onResizeTouchStart(ev, el)"></div>
                                    </t>
                                </div>
                            </t>
                        </div>
                    </div>
                </div>

                <!-- SAĞ PANEL: Özellikler & Katmanlar -->
                <div class="ub-designer-right-panel" style="display:flex; flex-direction:column;">
                    <div class="ub-designer-panel-title">Araçlar</div>
                    <div class="ub-designer-props" style="flex:1; overflow-y:auto; padding-bottom:1rem;">
                        <t t-if="selectedEl">
                            <div class="ub-props-title">
                                <span><i class="fa fa-sliders"></i> <t t-esc="getFieldLabel(selectedEl.type)"/></span>
                            </div>
                            <div class="ub-props-grid">
                                <div class="ub-prop-field"><label>X (mm)</label>
                                    <input type="number" step="0.5" t-att-value="selectedEl.x"
                                           t-on-change="(ev) => this.updateProp('x', ev.target.value)"/></div>
                                <div class="ub-prop-field"><label>Y (mm)</label>
                                    <input type="number" step="0.5" t-att-value="selectedEl.y"
                                           t-on-change="(ev) => this.updateProp('y', ev.target.value)"/></div>
                                <div class="ub-prop-field"><label>Genişlik</label>
                                    <input type="number" step="0.5" t-att-value="selectedEl.width"
                                           t-on-change="(ev) => this.updateProp('width', ev.target.value)"/></div>
                                <div class="ub-prop-field"><label>Yükseklik</label>
                                    <input type="number" step="0.5" t-att-value="selectedEl.height"
                                           t-on-change="(ev) => this.updateProp('height', ev.target.value)"/></div>
                                <div class="ub-prop-field" t-if="selectedEl.type !== 'line' and selectedEl.type !== 'cargo_barcode' and selectedEl.type !== 'box' and selectedEl.type !== 'cargo_qr_code'"><label>Font (pt)</label>
                                    <input type="number" step="1" min="4" max="72" t-att-value="selectedEl.fontSize"
                                           t-on-change="(ev) => this.updateProp('fontSize', ev.target.value)"/></div>
                                <div class="ub-prop-field" t-if="selectedEl.type !== 'line' and selectedEl.type !== 'cargo_barcode' and selectedEl.type !== 'box' and selectedEl.type !== 'cargo_qr_code'"><label>Kalınlık</label>
                                    <select t-att-value="selectedEl.fontWeight"
                                            t-on-change="(ev) => this.updateProp('fontWeight', ev.target.value)">
                                        <option value="normal">Normal</option>
                                        <option value="bold">Bold</option>
                                        <option value="600">Semi-Bold</option>
                                    </select></div>
                                <div class="ub-prop-field full" t-if="selectedEl.type !== 'line' and selectedEl.type !== 'cargo_barcode' and selectedEl.type !== 'box' and selectedEl.type !== 'cargo_qr_code'"><label>Hizalama</label>
                                    <select t-att-value="selectedEl.textAlign"
                                            t-on-change="(ev) => this.updateProp('textAlign', ev.target.value)">
                                        <option value="left">Sol</option>
                                        <option value="center">Orta</option>
                                        <option value="right">Sağ</option>
                                    </select></div>
                                <div class="ub-prop-field full" t-if="selectedEl.type === 'custom_text' or selectedEl.type === 'sender_name' or selectedEl.type === 'cargo_qr_code'"><label>Metin / İçerik</label>
                                    <input type="text" t-att-value="selectedEl.content"
                                           t-on-input="(ev) => this.updateProp('content', ev.target.value)"/></div>

                                <!-- Gelişmiş Özellikler -->
                                <div class="ub-prop-field"><label>Döndürme (°)</label>
                                    <select t-att-value="selectedEl.rotation || 0"
                                            t-on-change="(ev) => this.updateProp('rotation', ev.target.value)">
                                        <option value="0">0° Yatay</option>
                                        <option value="90">90° Dikey (Aşağı)</option>
                                        <option value="180">180° Ters</option>
                                        <option value="270">270° Dikey (Yukarı)</option>
                                    </select></div>
                                <div class="ub-prop-field"><label>Metin Rengi</label>
                                    <input type="color" t-att-value="selectedEl.color || '#000000'"
                                           t-on-input="(ev) => this.updateProp('color', ev.target.value)"/></div>
                                <div class="ub-prop-field"><label>Arka Plan</label>
                                    <input type="color" t-att-value="selectedEl.bgColor || '#ffffff'"
                                           t-on-input="(ev) => this.updateProp('bgColor', ev.target.value)"/>
                                    <button class="btn btn-sm btn-outline-secondary" style="font-size:0.6rem; padding: 0.1rem 0.2rem; margin-top:0.2rem;" t-on-click="(ev) => this.updateProp('bgColor', 'transparent')">Şeffaf Yap</button>
                                </div>
                                <div class="ub-prop-field" t-if="selectedEl.type === 'box'"><label>Kenar Kalınlığı</label>
                                    <input type="number" step="1" min="1" max="10" t-att-value="selectedEl.borderWidth || 1"
                                           t-on-change="(ev) => this.updateProp('borderWidth', ev.target.value)"/></div>
                            </div>
                            
                            <div style="display:flex;gap:0.5rem;margin-top:1.5rem;">
                                <button class="btn btn-sm btn-outline-secondary" style="flex:1;font-size:0.75rem; border-radius:6px;"
                                        t-on-click="moveLayerUp" title="Öne Getir"><i class="fa fa-arrow-up"></i></button>
                                <button class="btn btn-sm btn-outline-secondary" style="flex:1;font-size:0.75rem; border-radius:6px;"
                                        t-on-click="moveLayerDown" title="Arkaya Gönder"><i class="fa fa-arrow-down"></i></button>
                                <button t-attf-class="btn btn-sm {{selectedEl.locked ? 'btn-danger' : 'btn-outline-secondary'}}" style="flex:1;font-size:0.75rem; border-radius:6px;"
                                        t-on-click="toggleLock" title="Kilitle/Çöz"><i t-attf-class="fa {{selectedEl.locked ? 'fa-lock' : 'fa-unlock'}}"></i></button>
                            </div>
                            <div style="display:flex;gap:0.5rem;margin-top:0.5rem; justify-content:space-between;">
                                <button class="btn btn-sm btn-outline-secondary" style="flex:1;font-size:0.75rem; border-radius:6px;"
                                        t-on-click="duplicateSelected" title="Çoğalt">
                                    <i class="fa fa-clone"></i> Çoğalt
                                </button>
                                <button class="btn btn-sm btn-outline-danger" style="flex:1;font-size:0.75rem; border-radius:6px;"
                                        t-on-click="deleteSelected"><i class="fa fa-trash"></i> Sil</button>
                            </div>
                        </t>
                        <t t-if="!selectedEl">
                            <div class="ub-props-empty">
                                <i class="fa fa-mouse-pointer"></i>
                                Seçim Yapılmadı
                            </div>
                        </t>

                        <!-- KATMANLAR (LAYERS) -->
                        <div class="ub-layers-panel" style="margin-top: 1.5rem; border-top: 1px solid #e5e7eb; padding-top: 1rem;">
                            <div style="font-size: 0.75rem; font-weight: 600; color: #6b7280; margin-bottom: 0.5rem; text-transform: uppercase;">Katmanlar (<t t-esc="state.elements.length"/>)</div>
                            <div style="display: flex; flex-direction: column; gap: 0.25rem;">
                                <t t-foreach="[...state.elements].reverse()" t-as="el" t-key="el.id">
                                    <div t-attf-class="ub-layer-item {{state.selectedId === el.id ? 'active' : ''}}" t-on-click="() => this.state.selectedId = el.id"
                                         t-attf-style="display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0.6rem; font-size: 0.75rem; background: {{state.selectedId === el.id ? '#eff6ff' : '#fff'}}; border: 1px solid {{state.selectedId === el.id ? '#6366F1' : '#e5e7eb'}}; border-radius: 6px; cursor: pointer; color: {{state.selectedId === el.id ? '#1e3a8a' : '#374151'}}; font-weight: {{state.selectedId === el.id ? '600' : 'normal'}};">
                                        <i t-attf-class="fa {{getFieldIcon(el.type)}}" style="color:#9ca3af; width:14px; text-align:center;"></i>
                                        <span style="flex:1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                                            <t t-esc="getFieldLabel(el.type)"/> <t t-if="el.content">- <t t-esc="el.content"/></t>
                                        </span>
                                        <i t-attf-class="fa {{el.locked ? 'fa-lock' : 'fa-unlock'}}" style="color:#9ca3af; cursor:pointer;" title="Kilitle/Çöz" t-on-click.stop="() => el.locked = !el.locked"></i>
                                    </div>
                                </t>
                                <t t-if="state.elements.length === 0">
                                    <div style="font-size:0.75rem; color:#9ca3af; text-align:center; padding:1rem 0;">Tuvale bir obje ekleyin</div>
                                </t>
                            </div>
                        </div>

                        <div style="font-size:0.65rem; color:#9CA3AF; margin-top:1.5rem; text-align:center; padding: 1rem; background: #FAFAFB; border-radius: 6px;">
                            💡 <b>Kısayollar:</b><br/>Sil = DEL<br/>Hareket = Ok Tuşları<br/>Çoğalt = Ctrl+D
                        </div>
                    </div>
                </div>
            </div>

            <t t-if="state.saving">
                <div class="ub-loading" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9999;">
                    <i class="fa fa-spinner fa-spin fa-2x"></i><p>Şablon Kaydediliyor...</p>
                </div>
            </t>
        </div>
    `;

    static props = { navigate: Function, scanner: Object };

    setup() {
        this.canvasAreaRef = useRef('canvasArea');
        this.paperRef = useRef('paper');
        this.state = useState({
            templateName: 'Kargo Etiketi', widthMm: 100, heightMm: 150,
            elements: [], selectedId: null, editingId: 0, guideLines: [],
            templates: [], saving: false, zoom: 0.75, searchQuery: '', previewMode: false,
        });
        this._nextId = 1;
        this._drag = null;
        this._resize = null;
        this._onMouseMove = this._onMouseMove.bind(this);
        this._onMouseUp = this._onMouseUp.bind(this);
        this._onTouchMove = this._onTouchMove.bind(this);
        this._onTouchEnd = this._onTouchEnd.bind(this);

        onMounted(() => {
            document.addEventListener('mousemove', this._onMouseMove);
            document.addEventListener('mouseup', this._onMouseUp);
            document.addEventListener('touchmove', this._onTouchMove, { passive: false });
            document.addEventListener('touchend', this._onTouchEnd);
            this.loadTemplates().then(() => {
                if (this.props.templateId) this.loadTemplate(this.props.templateId);
            });
        });
        onWillUnmount(() => {
            document.removeEventListener('mousemove', this._onMouseMove);
            document.removeEventListener('mouseup', this._onMouseUp);
            document.removeEventListener('touchmove', this._onTouchMove);
            document.removeEventListener('touchend', this._onTouchEnd);
        });
    }

    get fieldTypes() { return CARGO_FIELD_TYPES; }
    get groups() { return CARGO_GROUPS; }
    get mmPx() { return MM_TO_PX; }
    get paperW() { return Math.round(this.state.widthMm * MM_TO_PX); }
    get paperH() { return Math.round(this.state.heightMm * MM_TO_PX); }
    get gridSize() { return Math.round(5 * MM_TO_PX); }
    get selectedEl() { return this.state.elements.find(e => e.id === this.state.selectedId) || null; }

    getGroupFields(gid) { return CARGO_FIELD_TYPES.filter(f => f.group === gid); }

    getFieldLabel(type) {
        const f = CARGO_FIELD_TYPES.find(ft => ft.type === type);
        return f ? f.label : type;
    }

    getFieldIcon(type) {
        const f = CARGO_FIELD_TYPES.find(ft => ft.type === type);
        return f ? f.icon : 'fa-cube';
    }

    getPreviewText(el) {
        if (!this.state.previewMode && el.type !== 'custom_text' && el.type !== 'sender_name' && el.type !== 'cargo_barcode') {
            return `[${this.getFieldLabel(el.type)}]`;
        }
        
        const previews = {
            order_number: '11098912935',
            picking_name: 'WH/OUT/00123',
            origin: 'S00123',
            marketplace: 'Trendyol',
            customer_name: 'Ahmet Yılmaz',
            partner_phone: '0532 123 45 67',
            shipping_address: 'Atatürk Cad. No:5 D:3',
            shipping_city: 'İstanbul',
            shipping_district: 'Kadıköy',
            cargo_tracking: '8880031736932260',
            cargo_barcode: '|||||||| |||| ||||||||',
            cargo_provider: 'Kolay Gelsin',
            item_list: '#  Kod         Açıklama        Adet',
            total_qty: '4 adet',
            total_items: '2 çeşit',
            sender_name: el.content || 'Uğurlar Ticaret',
            custom_text: el.content || 'Metin...',
            date_today: new Date().toLocaleDateString('tr-TR'),
            line: '',
            box: '',
            cargo_qr_code: '',
        };
        return previews[el.type] || el.type;
    }

    addElement(type) {
        const defaults = {
            order_number:     { width: 40, height: 6, fontSize: 10, fontWeight: 'bold' },
            picking_name:     { width: 35, height: 5, fontSize: 8, fontWeight: 'normal' },
            origin:           { width: 30, height: 5, fontSize: 8, fontWeight: 'normal' },
            marketplace:      { width: 30, height: 6, fontSize: 10, fontWeight: 'bold' },
            customer_name:    { width: 60, height: 7, fontSize: 11, fontWeight: 'bold' },
            partner_phone:    { width: 40, height: 5, fontSize: 9, fontWeight: 'normal' },
            shipping_address: { width: 80, height: 12, fontSize: 9, fontWeight: 'normal' },
            shipping_city:    { width: 30, height: 5, fontSize: 9, fontWeight: '600' },
            shipping_district:{ width: 30, height: 5, fontSize: 9, fontWeight: 'normal' },
            cargo_tracking:   { width: 60, height: 8, fontSize: 14, fontWeight: 'bold' },
            cargo_barcode:    { width: 70, height: 20, fontSize: 9, fontWeight: 'normal' },
            cargo_provider:   { width: 50, height: 8, fontSize: 12, fontWeight: 'bold' },
            item_list:        { width: 80, height: 20, fontSize: 8, fontWeight: 'normal' },
            total_qty:        { width: 25, height: 5, fontSize: 9, fontWeight: 'bold' },
            total_items:      { width: 25, height: 5, fontSize: 9, fontWeight: 'normal' },
            sender_name:      { width: 50, height: 6, fontSize: 9, fontWeight: '600' },
            custom_text:      { width: 40, height: 6, fontSize: 9, fontWeight: 'normal' },
            date_today:       { width: 25, height: 4, fontSize: 7, fontWeight: 'normal' },
            line:             { width: 80, height: 1, fontSize: 1, fontWeight: 'normal' },
            box:              { width: 40, height: 20, fontSize: 9, fontWeight: 'normal' },
            cargo_qr_code:    { width: 20, height: 20, fontSize: 9, fontWeight: 'normal' },
        };
        const d = defaults[type] || { width: 40, height: 6, fontSize: 9, fontWeight: 'normal' };
        const el = {
            id: 'el_' + (this._nextId++), type,
            x: 5, y: 5 + this.state.elements.length * 8,
            width: d.width, height: d.height,
            fontSize: d.fontSize, fontWeight: d.fontWeight,
            textAlign: 'left', content: '',
            rotation: 0, color: '#000000', bgColor: 'transparent', borderWidth: 1, locked: false
        };
        if (el.y + el.height > this.state.heightMm) el.y = 5;
        this.state.elements.push(el);
        this.state.selectedId = el.id;
    }

    duplicateSelected() {
        const sel = this.selectedEl; if (!sel) return;
        const dup = { ...sel, id: 'el_' + (this._nextId++), x: sel.x + 2, y: sel.y + 2 };
        this.state.elements.push(dup);
        this.state.selectedId = dup.id;
    }

    onKeyDown(ev) {
        const sel = this.selectedEl; if (!sel) return;
        const step = 0.5;
        switch (ev.key) {
            case 'Delete': case 'Backspace':
                if (ev.target.tagName === 'INPUT' || ev.target.tagName === 'SELECT') return;
                ev.preventDefault(); this.deleteSelected(); break;
            case 'ArrowLeft':  ev.preventDefault(); sel.x = Math.max(-50, sel.x - step); break;
            case 'ArrowRight': ev.preventDefault(); sel.x = Math.min(this.state.widthMm + 50, sel.x + step); break;
            case 'ArrowUp':    ev.preventDefault(); sel.y = Math.max(-50, sel.y - step); break;
            case 'ArrowDown':  ev.preventDefault(); sel.y = Math.min(this.state.heightMm + 50, sel.y + step); break;
            case 'd': case 'D':
                if (ev.ctrlKey || ev.metaKey) { ev.preventDefault(); this.duplicateSelected(); } break;
        }
    }

    zoomIn()  { this.state.zoom = Math.min(4, this.state.zoom + 0.25); }
    zoomOut() { this.state.zoom = Math.max(0.25, this.state.zoom - 0.25); }

    // ─── SÜRÜKLE-BIRAK (Mouse) ────────────────────
    onElMouseDown(ev, el) {
        this.state.selectedId = el.id;
        if (!el.locked) {
            this._drag = { id: el.id, startMouseX: ev.clientX, startMouseY: ev.clientY, startElX: el.x, startElY: el.y };
        }
    }

    _onMouseMove(ev) {
        const z = this.state.zoom;
        if (this._drag) {
            const dx = (ev.clientX - this._drag.startMouseX) / (MM_TO_PX * z);
            const dy = (ev.clientY - this._drag.startMouseY) / (MM_TO_PX * z);
            const el = this.state.elements.find(e => e.id === this._drag.id);
            if (el && !el.locked) {
                const rawNewX = Math.round((this._drag.startElX + dx) * 2) / 2;
                const rawNewY = Math.round((this._drag.startElY + dy) * 2) / 2;
                this._applyDragWithSnapping(el, rawNewX, rawNewY);
            }
        }
        if (this._resize) {
            const dx = (ev.clientX - this._resize.startMouseX) / (MM_TO_PX * z);
            const dy = (ev.clientY - this._resize.startMouseY) / (MM_TO_PX * z);
            const el = this.state.elements.find(e => e.id === this._resize.id);
            if (el) {
                el.width = Math.max(5, Math.round((this._resize.startW + dx) * 2) / 2);
                el.height = Math.max(1, Math.round((this._resize.startH + dy) * 2) / 2);
            }
        }
    }

    _onMouseUp() { this._drag = null; this._resize = null; this.state.guideLines = []; }

    onResizeMouseDown(ev, el) {
        this.state.selectedId = el.id;
        this._resize = { id: el.id, startMouseX: ev.clientX, startMouseY: ev.clientY, startW: el.width, startH: el.height };
    }

    // ─── SÜRÜKLE-BIRAK (Touch) ────────────────────
    onElTouchStart(ev, el) {
        const t = ev.touches[0]; this.state.selectedId = el.id;
        if (!el.locked) {
            this._drag = { id: el.id, startMouseX: t.clientX, startMouseY: t.clientY, startElX: el.x, startElY: el.y };
        }
    }

    _onTouchMove(ev) {
        if (!this._drag && !this._resize) return;
        ev.preventDefault();
        const t = ev.touches[0]; const z = this.state.zoom;
        if (this._drag) {
            const dx = (t.clientX - this._drag.startMouseX) / (MM_TO_PX * z);
            const dy = (t.clientY - this._drag.startMouseY) / (MM_TO_PX * z);
            const el = this.state.elements.find(e => e.id === this._drag.id);
            if (el && !el.locked) {
                const rawNewX = Math.round((this._drag.startElX + dx) * 2) / 2;
                const rawNewY = Math.round((this._drag.startElY + dy) * 2) / 2;
                this._applyDragWithSnapping(el, rawNewX, rawNewY);
            }
        }
        if (this._resize) {
            const dx = (t.clientX - this._resize.startMouseX) / (MM_TO_PX * z);
            const dy = (t.clientY - this._resize.startMouseY) / (MM_TO_PX * z);
            const el = this.state.elements.find(e => e.id === this._resize.id);
            if (el) {
                el.width = Math.max(5, Math.round((this._resize.startW + dx) * 2) / 2);
                el.height = Math.max(1, Math.round((this._resize.startH + dy) * 2) / 2);
            }
        }
    }

    _onTouchEnd() { this._drag = null; this._resize = null; this.state.guideLines = []; }

    _applyDragWithSnapping(el, rawNewX, rawNewY) {
        this.state.guideLines = [];
        if (this.state.previewMode) {
            el.x = Math.max(-50, Math.min(this.state.widthMm + 50, rawNewX));
            el.y = Math.max(-50, Math.min(this.state.heightMm + 50, rawNewY));
            return;
        }

        const threshold = 1.0; // mm
        let snapX = null, snapY = null;

        const eT = rawNewY, eB = rawNewY + el.height, eMY = rawNewY + el.height / 2;
        const eL = rawNewX, eR = rawNewX + el.width, eMX = rawNewX + el.width / 2;

        for (let o of this.state.elements) {
            if (o.id === el.id) continue;
            const oT = o.y, oB = o.y + o.height, oMY = o.y + o.height / 2;
            const oL = o.x, oR = o.x + o.width, oMX = o.x + o.width / 2;

            if (snapX === null) {
                const xs = [
                    { ep: eL, op: oL }, { ep: eL, op: oR }, { ep: eL, op: oMX },
                    { ep: eR, op: oL }, { ep: eR, op: oR }, { ep: eR, op: oMX },
                    { ep: eMX, op: oL }, { ep: eMX, op: oR }, { ep: eMX, op: oMX }
                ];
                for (let s of xs) {
                    if (Math.abs(s.ep - s.op) <= threshold) {
                        snapX = rawNewX + (s.op - s.ep);
                        this.state.guideLines.push({ id:`v_${o.id}`, type: 'vertical', pos: s.op, start: -10, end: this.state.heightMm + 10 });
                        break;
                    }
                }
            }

            if (snapY === null) {
                const ys = [
                    { ep: eT, op: oT }, { ep: eT, op: oB }, { ep: eT, op: oMY },
                    { ep: eB, op: oT }, { ep: eB, op: oB }, { ep: eB, op: oMY },
                    { ep: eMY, op: oT }, { ep: eMY, op: oB }, { ep: eMY, op: oMY }
                ];
                for (let s of ys) {
                    if (Math.abs(s.ep - s.op) <= threshold) {
                        snapY = rawNewY + (s.op - s.ep);
                        this.state.guideLines.push({ id:`h_${o.id}`, type: 'horizontal', pos: s.op, start: -10, end: this.state.widthMm + 10 });
                        break;
                    }
                }
            }
        }
        el.x = Math.max(-50, Math.min(this.state.widthMm + 50, snapX !== null ? snapX : Math.round(rawNewX * 2)/2));
        el.y = Math.max(-50, Math.min(this.state.heightMm + 50, snapY !== null ? snapY : Math.round(rawNewY * 2)/2));
    }
    onResizeTouchStart(ev, el) {
        const t = ev.touches[0]; this.state.selectedId = el.id;
        this._resize = { id: el.id, startMouseX: t.clientX, startMouseY: t.clientY, startW: el.width, startH: el.height };
    }

    onCanvasMouseDown(ev) {
        if (ev.target === this.canvasAreaRef.el || ev.target.classList.contains('ub-designer-paper') || ev.target.classList.contains('ub-designer-grid'))
            this.state.selectedId = null;
    }
    onCanvasTouchStart(ev) {
        if (ev.target === this.canvasAreaRef.el || ev.target.classList.contains('ub-designer-paper') || ev.target.classList.contains('ub-designer-grid'))
            this.state.selectedId = null;
    }

    updateProp(prop, value) {
        const el = this.selectedEl; if (!el) return;
        if (['x', 'y', 'width', 'height', 'fontSize', 'rotation', 'borderWidth'].includes(prop)) el[prop] = parseFloat(value) || 0;
        else el[prop] = value;
    }
    moveLayerUp() {
        const id = this.state.selectedId; if (!id) return;
        const idx = this.state.elements.findIndex(e => e.id === id);
        if (idx < this.state.elements.length - 1) {
            const el = this.state.elements.splice(idx, 1)[0];
            this.state.elements.splice(idx + 1, 0, el);
        }
    }
    moveLayerDown() {
        const id = this.state.selectedId; if (!id) return;
        const idx = this.state.elements.findIndex(e => e.id === id);
        if (idx > 0) {
            const el = this.state.elements.splice(idx, 1)[0];
            this.state.elements.splice(idx - 1, 0, el);
        }
    }
    toggleLock() {
        if (this.selectedEl) {
            this.selectedEl.locked = !this.selectedEl.locked;
            if (this.selectedEl.locked) { this._drag = null; this._resize = null; }
        }
    }
    deleteSelected() {
        this.state.elements = this.state.elements.filter(e => e.id !== this.state.selectedId);
        this.state.selectedId = null;
    }
    setDimension(dim, val) {
        const v = Math.max(10, Math.min(300, parseFloat(val) || 100));
        if (dim === 'w') this.state.widthMm = v; else this.state.heightMm = v;
    }

    // ─── ŞABLON CRUD — aynı label_template tablosunu kullanıyoruz ama cargo_ prefix ile ────
    async loadTemplates() {
        try {
            const res = await BarcodeService.labelTemplateList();
            // Sadece "Kargo" başlayan şablonları filtrele
            this.state.templates = (res.templates || []).filter(t => t.name.startsWith('Kargo'));
        } catch (e) {}
    }
    onLoadTemplate(ev) {
        const id = parseInt(ev.target.value);
        if (!id) {
            this.state.editingId = 0; this.state.templateName = 'Kargo Etiketi';
            this.state.widthMm = 100; this.state.heightMm = 150;
            this.state.elements = []; this.state.selectedId = null; this._nextId = 1;
            return;
        }
        this.loadTemplate(id);
    }
    loadTemplate(id) {
        const t = this.state.templates.find(t => t.id === id); if (!t) return;
        this.state.editingId = t.id; this.state.templateName = t.name;
        this.state.widthMm = t.width_mm; this.state.heightMm = t.height_mm;
        this.state.elements = (t.elements || []).map(e => ({ ...e }));
        this.state.selectedId = null;
        this._nextId = Math.max(...this.state.elements.map(e => parseInt((e.id || '').replace('el_','')) || 0), 0) + 1;
    }
    async onSave() {
        if (!this.state.templateName.trim()) { alert('Şablon adı gerekli'); return; }
        // Kargo prefix emin ol
        let name = this.state.templateName.trim();
        if (!name.startsWith('Kargo')) name = 'Kargo — ' + name;
        this.state.saving = true;
        try {
            const res = await BarcodeService.labelTemplateSave(
                this.state.editingId, name,
                this.state.widthMm, this.state.heightMm,
                this.state.elements.map(e => ({
                    id: e.id, type: e.type, x: e.x, y: e.y,
                    width: e.width, height: e.height,
                    fontSize: e.fontSize, fontWeight: e.fontWeight,
                    textAlign: e.textAlign, content: e.content || '',
                    rotation: e.rotation || 0, color: e.color || '#000000', bgColor: e.bgColor || 'transparent', borderWidth: e.borderWidth || 1,
                    locked: e.locked || false,
                })), false
            );
            if (res.error) alert(res.error);
            else { this.state.editingId = res.id; this.state.templateName = name; await this.loadTemplates(); alert(res.message || 'Kaydedildi!'); }
        } catch (e) { alert('Kaydetme hatası: ' + (e.message || e)); }
        this.state.saving = false;
    }
    async onDelete() {
        if (!this.state.editingId) return;
        if (!confirm('Şablonu silmek istediğinize emin misiniz?')) return;
        try { await BarcodeService.labelTemplateDelete(this.state.editingId); this.state.editingId = 0; this.state.templateName = 'Kargo Etiketi'; this.state.elements = []; this.state.selectedId = null; await this.loadTemplates(); } catch (e) { alert('Silme hatası'); }
    }

    exportTemplate() {
        const data = {
            name: this.state.templateName,
            widthMm: this.state.widthMm,
            heightMm: this.state.heightMm,
            type: 'cargo',
            elements: this.state.elements.map(e => ({
                id: e.id, type: e.type, x: e.x, y: e.y,
                width: e.width, height: e.height,
                fontSize: e.fontSize, fontWeight: e.fontWeight,
                textAlign: e.textAlign, content: e.content || '',
                rotation: e.rotation || 0, color: e.color || '#000000',
                bgColor: e.bgColor || 'transparent', borderWidth: e.borderWidth || 1,
                locked: e.locked || false,
            }))
        };
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = (this.state.templateName || 'tasarim').replace(/[\s\/\\]+/g, '_') + '.json';
        a.click();
        URL.revokeObjectURL(url);
    }

    importTemplate(ev) {
        const file = ev.target.files[0];
        if (!file) return;
        ev.target.value = '';
        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const data = JSON.parse(e.target.result);
                if (!data.elements || !Array.isArray(data.elements)) {
                    alert('Geçersiz tasarım dosyası'); return;
                }
                this.state.templateName = data.name || 'İçe Aktarılan';
                this.state.widthMm = data.widthMm || 100;
                this.state.heightMm = data.heightMm || 150;
                this.state.elements = data.elements.map(e => ({ ...e }));
                this.state.selectedId = null;
                this.state.editingId = 0;
                this._nextId = Math.max(...this.state.elements.map(e => parseInt((e.id || '').replace('el_','')) || 0), 0) + 1;
                alert('Tasarım başarıyla içe aktarıldı!');
            } catch (err) {
                alert('Dosya okunamadı: ' + err.message);
            }
        };
        reader.readAsText(file);
    }

    onBack() { this.props.navigate('packing'); }
}
