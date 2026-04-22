/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { BarcodeScanner } from "./barcode_scanner";
import { MainMenu } from "./screens/main_menu";
import { StockSearch } from "./screens/stock_search";
import { ShelfSearch } from "./screens/shelf_search";
import { ShelfControl } from "./screens/shelf_control";
import { PutawayScreen } from "./screens/putaway";
import { ShelfTransferScreen } from "./screens/shelf_transfer";
import { PickingScreen } from "./screens/picking";
import { CountingScreen } from "./screens/counting";
import { MovementsScreen } from "./screens/movements";
import { LabelScreen } from "./screens/labels";
import { LabelDesigner } from "./screens/label_designer";
import { BulkScreen } from "./screens/bulk";
import { PerformanceScreen } from "./screens/performance";
import { ShelfMoveAll } from "./screens/shelf_move_all";
import { ShelfValidateScreen } from "./screens/shelf_validate";
import { BulkPutawayScreen } from "./screens/bulk_putaway";
import { ShelfClearAllScreen } from "./screens/shelf_clear_all";
import { PackingScreen } from "./screens/packing";
import { BatchPickingScreen } from "./screens/batch_picking";
import { CargoLabelDesigner } from "./screens/cargo_label_designer";

// Geçerli ekran isimleri
const VALID_SCREENS = new Set([
    'main', 'stock_search', 'shelf_search', 'shelf_control',
    'putaway', 'shelf_transfer', 'shelf_move_all', 'shelf_validate', 'bulk_putaway', 'shelf_clear_all', 'picking', 'batch_picking', 'counting', 'movements',
    'labels', 'label_designer', 'bulk', 'performance', 'packing', 'cargo_label_designer',
]);

// Storage key — sessionStorage ile yedekle
const STORAGE_KEY = 'ugurlar_barcode_screen';

class BarcodeApp extends Component {
    static components = {
        MainMenu, StockSearch, ShelfSearch, ShelfControl,
        PutawayScreen, ShelfTransferScreen, ShelfMoveAll, ShelfValidateScreen, BulkPutawayScreen, ShelfClearAllScreen, PickingScreen, BatchPickingScreen, CountingScreen,
        MovementsScreen, LabelScreen, LabelDesigner, BulkScreen, PerformanceScreen, PackingScreen, CargoLabelDesigner,
    };

    setup() {
        this.scanner = new BarcodeScanner();

        // Başlangıç ekranını belirle: hash > sessionStorage > 'main'
        const initialScreen = this._readScreen();
        this.state = useState({ screen: initialScreen });

        // Hash değişikliğini dinle (geri/ileri tuşları)
        this._onHashChange = () => {
            const screen = this._readScreenFromHash();
            if (screen && screen !== this.state.screen) {
                this.state.screen = screen;
                this._saveToStorage(screen);
            }
        };

        // popstate dinle (geri tuşu)
        this._onPopState = () => {
            const screen = this._readScreenFromHash();
            if (screen && screen !== this.state.screen) {
                this.state.screen = screen;
                this._saveToStorage(screen);
            }
        };

        onMounted(() => {
            this.scanner.start();
            window.addEventListener('hashchange', this._onHashChange);
            window.addEventListener('popstate', this._onPopState);
            // Hash'i güncelle (mevcut ekranı yansıtsın)
            this._writeHash(this.state.screen, true);
        });

        onWillUnmount(() => {
            this.scanner.stop();
            window.removeEventListener('hashchange', this._onHashChange);
            window.removeEventListener('popstate', this._onPopState);
        });
    }

    // ═══ HASH OKUMA ═══
    _readScreenFromHash() {
        const hash = window.location.hash || '';
        // #screen=xxx veya #...&screen=xxx formatlarını yakala
        const match = hash.match(/(?:^#|[?&])screen=([^&]+)/);
        if (match && VALID_SCREENS.has(match[1])) {
            return match[1];
        }
        return null;
    }

    // ═══ STORAGE OKUMA ═══
    _readFromStorage() {
        try {
            const stored = sessionStorage.getItem(STORAGE_KEY);
            if (stored && VALID_SCREENS.has(stored)) return stored;
        } catch (e) { /* sessionStorage erişim hatası */ }
        return null;
    }

    // ═══ KAYDET ═══
    _saveToStorage(screen) {
        try { sessionStorage.setItem(STORAGE_KEY, screen); } catch (e) {}
    }

    // ═══ BAŞLANGIÇ EKRANI ═══
    _readScreen() {
        // 1. Hash'ten oku
        const fromHash = this._readScreenFromHash();
        if (fromHash) {
            this._saveToStorage(fromHash);
            return fromHash;
        }
        // 2. sessionStorage'dan oku (hash kaybolmuşsa yedek)
        const fromStorage = this._readFromStorage();
        if (fromStorage) return fromStorage;
        // 3. Varsayılan
        return 'main';
    }

    // ═══ HASH YAZMA ═══
    _writeHash(screen, replace = false) {
        const base = window.location.pathname + window.location.search;
        const newUrl = base + '#screen=' + screen;

        if (replace) {
            history.replaceState({ ubScreen: screen }, '', newUrl);
        } else {
            history.pushState({ ubScreen: screen }, '', newUrl);
        }
    }

    // ═══ NAVİGASYON ═══
    navigate(screen) {
        if (this.state.screen === screen) return;
        this.state.screen = screen;
        this._saveToStorage(screen);
        this._writeHash(screen, false);
    }
}

BarcodeApp.template = owl.xml`
    <div class="ub-app">
        <t t-if="state.screen === 'main'">
            <MainMenu navigate.bind="navigate"/>
        </t>
        <t t-if="state.screen === 'stock_search'">
            <StockSearch navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'shelf_search'">
            <ShelfSearch navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'shelf_control'">
            <ShelfControl navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'putaway'">
            <PutawayScreen navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'shelf_transfer'">
            <ShelfTransferScreen navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'shelf_move_all'">
            <ShelfMoveAll navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'shelf_validate'">
            <ShelfValidateScreen navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'bulk_putaway'">
            <BulkPutawayScreen navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'shelf_clear_all'">
            <ShelfClearAllScreen navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'picking'">
            <PickingScreen navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'batch_picking'">
            <BatchPickingScreen navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'counting'">
            <CountingScreen navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'movements'">
            <MovementsScreen navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'labels'">
            <LabelScreen navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'label_designer'">
            <LabelDesigner navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'bulk'">
            <BulkScreen navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'performance'">
            <PerformanceScreen navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'packing'">
            <PackingScreen navigate.bind="navigate" scanner="scanner"/>
        </t>
        <t t-if="state.screen === 'cargo_label_designer'">
            <CargoLabelDesigner navigate.bind="navigate" scanner="scanner"/>
        </t>
    </div>
`;

registry.category("actions").add("ugurlar_barcode_app", BarcodeApp);
