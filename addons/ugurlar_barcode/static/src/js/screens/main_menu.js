/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";

export class MainMenu extends Component {
    static template = xml`
        <div class="ub-main-menu">
            <div class="ub-header">
                <h1 class="ub-title">
                    <i class="fa fa-mobile"></i> Mobil
                </h1>
                <p class="ub-subtitle">Depo Yönetim Sistemi</p>
            </div>

            <div class="ub-search-bar">
                <div class="ub-search-input-wrap">
                    <i class="fa fa-search ub-search-icon"></i>
                    <input type="text"
                           class="ub-search-input"
                           placeholder="Modül ara..."
                           t-on-input="onSearch"
                           t-att-value="state.query"/>
                </div>
            </div>

            <div class="ub-menu-grid">
                <t t-foreach="filteredCards" t-as="card" t-key="card.key">
                    <div t-attf-class="ub-menu-card ub-card-{{card.color}} {{card.disabled ? 'ub-card-disabled' : ''}}"
                         t-on-click="() => !card.disabled and this.props.navigate(card.key)">
                        <div class="ub-card-icon"><i t-att-class="'fa ' + card.icon"/></div>
                        <div class="ub-card-title" t-esc="card.title"/>
                        <div class="ub-card-desc" t-esc="card.desc"/>
                    </div>
                </t>
            </div>

            <div class="ub-no-results" t-if="filteredCards.length === 0">
                <i class="fa fa-search"></i>
                <p>Sonuç bulunamadı</p>
            </div>
        </div>
    `;

    static props = { navigate: Function };

    setup() {
        this.allCards = [
            { key: 'stock_search', icon: 'fa-search', title: 'Ürün Stok Arama', desc: 'Barkod, kod veya isim ile ara', color: 'search', disabled: false },
            { key: 'shelf_search', icon: 'fa-map-marker', title: 'Ürün Raf Arama', desc: 'Ürün hangi rafta?', color: 'shelf', disabled: false },
            { key: 'shelf_control', icon: 'fa-th', title: 'Raf Kontrol', desc: 'Raftaki ürünleri listele', color: 'control', disabled: false },
            { key: 'putaway', icon: 'fa-arrow-down', title: 'Raflama', desc: 'Ürün rafla / kaldır', color: 'putaway', disabled: false },
            { key: 'shelf_transfer', icon: 'fa-truck', title: 'Ürün Raf Taşıma', desc: 'Ürünü başka rafa taşı', color: 'transfer', disabled: false },
            { key: 'shelf_move_all', icon: 'fa-truck', title: 'Tüm Rafı Taşı', desc: 'Raftaki tüm ürünleri taşı', color: 'move-all', disabled: false },
            { key: 'shelf_validate', icon: 'fa-check-square-o', title: 'Raf Ürün Doğrulama', desc: 'Raftaki ürünleri doğrula', color: 'validate', disabled: false },
            { key: 'bulk_putaway', icon: 'fa-cubes', title: 'Toplu Ürün Raflama', desc: 'Rafa sürekli ürün tara', color: 'bulk-putaway', disabled: false },
            { key: 'shelf_clear_all', icon: 'fa-trash-o', title: 'Toplu Raf Silme', desc: 'Raftaki tüm ürünleri kaldır', color: 'clear-all', disabled: false },
            { key: 'picking', icon: 'fa-shopping-cart', title: 'Sipariş Toplama', desc: 'Sipariş ürünlerini topla', color: 'picking', disabled: false },
            { key: 'batch_picking', icon: 'fa-list-ol', title: 'Rota Toplama', desc: 'Toplama listesi ile raf raf topla', color: 'batch-picking', disabled: false },
            { key: 'packing', icon: 'fa-gift', title: 'Paketleme & Fatura', desc: 'Rota ile eşleştir ve faturala', color: 'packing', disabled: false },
            { key: 'counting', icon: 'fa-calculator', title: 'Sayım', desc: 'Raf sayımı yap', color: 'counting', disabled: false },
            // Faz 5
            { key: 'movements', icon: 'fa-exchange', title: 'Stok Hareketleri', desc: 'Giriş/çıkış/transfer raporu', color: 'movements', disabled: false },
            { key: 'labels', icon: 'fa-print', title: 'Etiket Yazdır', desc: 'Barkod etiketi oluştur', color: 'labels', disabled: false },
            { key: 'performance', icon: 'fa-trophy', title: 'Operatör Performans', desc: 'Kim ne kadar iş yaptı?', color: 'performance', disabled: false },
        ];
        this.state = useState({ query: '' });
    }

    onSearch(ev) { this.state.query = ev.target.value; }

    get filteredCards() {
        const q = this.state.query.toLowerCase().trim();
        if (!q) return this.allCards;
        return this.allCards.filter(c => c.title.toLowerCase().includes(q) || c.desc.toLowerCase().includes(q));
    }
}
