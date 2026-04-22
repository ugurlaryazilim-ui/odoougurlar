{
    'name': 'Mobil',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Barcode',
    'summary': 'Mobil uyumlu barkod tarama ve depo yönetim modülü',
    'description': """
        Mobil Depo Yönetimi
        =====================
        * Kamera ve el terminali ile barkod tarama
        * Ürün stok arama
        * Raf arama ve kontrol
        * Ürün raflama / raftan kaldırma
        * Sipariş toplama
        * Envanter sayım
        * Stok hareket raporları
        * Operatör performans takibi
    """,
    'author': 'Uğurlar',
    'depends': ['stock', 'barcodes', 'odoougurlar', 'stock_picking_batch'],
    'data': [
        'security/ir.model.access.csv',
        'views/barcode_templates.xml',
        'views/barcode_menu.xml',
        'views/picking_schedule_views.xml',
        'views/picking_batch_views.xml',
        'views/stock_picking_ext_views.xml',
        'data/sequence.xml',
        'data/cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ugurlar_barcode/static/src/css/base.css',
            'ugurlar_barcode/static/src/css/components.css',
            'ugurlar_barcode/static/src/css/screens.css',
            'ugurlar_barcode/static/src/css/label_designer.css',
            'ugurlar_barcode/static/src/css/shelf_transfer.css',
            'ugurlar_barcode/static/src/css/shelf_move_all.css',
            'ugurlar_barcode/static/src/css/shelf_validate.css',
            'ugurlar_barcode/static/src/css/bulk_putaway.css',
            'ugurlar_barcode/static/src/css/shelf_clear_all.css',
            'ugurlar_barcode/static/src/js/barcode_scanner.js',
            'ugurlar_barcode/static/src/js/barcode_service.js',
            'ugurlar_barcode/static/src/js/screens/main_menu.js',
            'ugurlar_barcode/static/src/js/screens/stock_search.js',
            'ugurlar_barcode/static/src/js/screens/shelf_search.js',
            'ugurlar_barcode/static/src/js/screens/shelf_control.js',
            'ugurlar_barcode/static/src/js/screens/putaway.js',
            'ugurlar_barcode/static/src/js/screens/shelf_transfer.js',
            'ugurlar_barcode/static/src/js/screens/shelf_move_all.js',
            'ugurlar_barcode/static/src/js/screens/shelf_validate.js',
            'ugurlar_barcode/static/src/js/screens/bulk_putaway.js',
            'ugurlar_barcode/static/src/js/screens/shelf_clear_all.js',
            'ugurlar_barcode/static/src/js/screens/picking.js',
            'ugurlar_barcode/static/src/js/screens/counting.js',
            'ugurlar_barcode/static/src/js/screens/movements.js',
            'ugurlar_barcode/static/src/js/screens/labels.js',
            'ugurlar_barcode/static/src/js/screens/packing.js',
            'ugurlar_barcode/static/src/js/screens/batch_picking.js',
            'ugurlar_barcode/static/src/css/packing.css',
            'ugurlar_barcode/static/src/css/batch_picking.css',
            'ugurlar_barcode/static/src/js/screens/label_designer.js',
            'ugurlar_barcode/static/src/js/screens/cargo_label_designer.js',
            'ugurlar_barcode/static/src/js/screens/performance.js',
            'ugurlar_barcode/static/src/js/screens/bulk.js',
            'ugurlar_barcode/static/src/js/barcode_action.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'icon': '/ugurlar_barcode/static/description/icon.png',
}
