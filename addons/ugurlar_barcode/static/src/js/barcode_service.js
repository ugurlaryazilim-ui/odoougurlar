/** @odoo-module **/

import { rpc } from "@web/core/network/rpc";

export const BarcodeService = {
    async productSearch(barcode, search_type = 'barcode') {
        return await rpc('/ugurlar_barcode/api/product_search', { barcode, search_type });
    },
    async shelfSearch(barcode) {
        return await rpc('/ugurlar_barcode/api/shelf_search', { barcode });
    },
    async shelfControl(barcode) {
        return await rpc('/ugurlar_barcode/api/shelf_control', { barcode });
    },
    async putaway(product_barcode, shelf_barcode, quantity) {
        return await rpc('/ugurlar_barcode/api/putaway', { product_barcode, shelf_barcode, quantity });
    },
    async removeFromShelf(product_barcode, shelf_barcode, quantity) {
        return await rpc('/ugurlar_barcode/api/remove_from_shelf', { product_barcode, shelf_barcode, quantity });
    },
    async pickingList() {
        return await rpc('/ugurlar_barcode/api/picking_list', {});
    },
    async pickingDetail(picking_id) {
        return await rpc('/ugurlar_barcode/api/picking_detail', { picking_id });
    },
    async pickingScan(picking_id, barcode, quantity) {
        return await rpc('/ugurlar_barcode/api/picking_scan', { picking_id, barcode, quantity });
    },
    async pickingValidate(picking_id) {
        return await rpc('/ugurlar_barcode/api/picking_validate', { picking_id });
    },
    async countSave(shelf_barcode, items) {
        return await rpc('/ugurlar_barcode/api/count_save', { shelf_barcode, items });
    },
    async countList(days = 30) {
        return await rpc('/ugurlar_barcode/api/count_list', { days });
    },
    // Faz 5
    async stockMovements(days = 7, product_barcode = '', move_type = 'all') {
        return await rpc('/ugurlar_barcode/api/stock_movements', { days, product_barcode, move_type });
    },
    async labelData(barcodes) {
        return await rpc('/ugurlar_barcode/api/label_data', { barcodes });
    },
    async bulkScan(items, operation = 'info', shelf_barcode = '') {
        return await rpc('/ugurlar_barcode/api/bulk_scan', { items, operation, shelf_barcode });
    },
    async operatorPerformance(days = 7) {
        return await rpc('/ugurlar_barcode/api/operator_performance', { days });
    },
    async shelfTransfer(product_barcode, source_shelf_barcode, target_shelf_barcode, quantity, reason) {
        return await rpc('/ugurlar_barcode/api/shelf_transfer', {
            product_barcode, source_shelf_barcode, target_shelf_barcode, quantity, reason
        });
    },
    // Etiket şablon
    async labelTemplateList() {
        return await rpc('/ugurlar_barcode/api/label_template_list', {});
    },
    async labelTemplateSave(template_id, name, width_mm, height_mm, elements, is_default) {
        return await rpc('/ugurlar_barcode/api/label_template_save', {
            template_id, name, width_mm, height_mm, elements, is_default
        });
    },
    async labelTemplateDelete(template_id) {
        return await rpc('/ugurlar_barcode/api/label_template_delete', { template_id });
    },
    // Tüm Rafı Taşı
    async shelfMoveAll(source_barcode, target_barcode, reason) {
        return await rpc('/ugurlar_barcode/api/shelf_move_all', { source_barcode, target_barcode, reason });
    },
    // Toplu Raf Silme
    async shelfClearAll(shelf_barcode) {
        return await rpc('/ugurlar_barcode/api/shelf_clear_all', { shelf_barcode });
    },
    // Rota Toplama (Wave Picking)
    async batchRouteItems(batch_id) {
        return await rpc('/ugurlar_barcode/api/batch_route_items', { batch_id });
    },
    async batchCollectScan(batch_id, barcode) {
        return await rpc('/ugurlar_barcode/api/batch_collect_scan', { batch_id, barcode });
    },
    async batchCollectComplete(batch_id) {
        return await rpc('/ugurlar_barcode/api/batch_collect_complete', { batch_id });
    },
    // Genel RPC çağrısı
    async call(url, params = {}) {
        return await rpc(url, params);
    },
};

export const AudioFeedback = {
    playSuccess() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gainNode = ctx.createGain();
            osc.connect(gainNode);
            gainNode.connect(ctx.destination);
            
            osc.type = 'sine';
            // 800'den 1200'e hızlı bir çıkış (kısa, tatlı bip)
            osc.frequency.setValueAtTime(800, ctx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(1200, ctx.currentTime + 0.1);
            
            gainNode.gain.setValueAtTime(0, ctx.currentTime);
            gainNode.gain.linearRampToValueAtTime(0.5, ctx.currentTime + 0.05);
            gainNode.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.15);
            
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + 0.15);
        } catch (e) { console.warn("Audio not supported"); }
    },
    playError() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gainNode = ctx.createGain();
            osc.connect(gainNode);
            gainNode.connect(ctx.destination);
            
            osc.type = 'sawtooth';
            // 150 Hz kalın, rahatsız edici bir uyarı (Buzzer)
            osc.frequency.setValueAtTime(150, ctx.currentTime);
            
            gainNode.gain.setValueAtTime(0, ctx.currentTime);
            gainNode.gain.linearRampToValueAtTime(0.5, ctx.currentTime + 0.1);
            gainNode.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.4);
            
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + 0.4);
        } catch (e) { console.warn("Audio not supported"); }
    }
};
