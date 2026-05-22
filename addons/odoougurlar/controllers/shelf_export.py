"""Raf Detay Dosyası Excel Export Controller."""
import io
import logging
from datetime import datetime as dt

from odoo import http
from odoo.http import request, content_disposition

_logger = logging.getLogger(__name__)


class ShelfExportController(http.Controller):

    @http.route('/odoougurlar/shelf_detail_export', type='http', auth='user')
    def shelf_detail_export(self, **kw):
        """Tüm dahili stok konumlarını Excel olarak indir."""
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        except ImportError:
            _logger.error("openpyxl kütüphanesi bulunamadı!")
            return request.not_found()

        try:
            return self._generate_shelf_excel(openpyxl, Font, PatternFill,
                                              Alignment, Border, Side)
        except Exception as e:
            _logger.exception("Raf export hatası: %s", str(e))
            return request.not_found()

    def _generate_shelf_excel(self, openpyxl, Font, PatternFill,
                              Alignment, Border, Side):
        """Excel dosyası oluştur ve döndür."""
        env = request.env
        cr = env.cr

        # ─── VERİ TOPLAMA (SQL ile hızlı) ───
        cr.execute("""
            SELECT
                sl.id,
                sl.complete_name,
                sl.name,
                sl.barcode,
                sl.usage,
                sl.posx, sl.posy, sl.posz,
                sl.scrap_location,
                sw.name AS warehouse_name,
                (SELECT COUNT(*) FROM stock_location ch
                 WHERE ch.location_id = sl.id) AS child_count,
                COALESCE((
                    SELECT SUM(sq.quantity)
                    FROM stock_quant sq
                    JOIN stock_location sub ON sq.location_id = sub.id
                    WHERE sub.parent_path LIKE sl.parent_path || '%%'
                      AND sub.usage = 'internal'
                      AND sq.quantity > 0
                ), 0) AS total_qty,
                COALESCE((
                    SELECT COUNT(DISTINCT sq.product_id)
                    FROM stock_quant sq
                    WHERE sq.location_id = sl.id AND sq.quantity > 0
                ), 0) AS product_count
            FROM stock_location sl
            LEFT JOIN stock_warehouse sw ON sw.lot_stock_id = (
                SELECT p.id FROM stock_location p
                WHERE sl.parent_path LIKE p.parent_path || '%%'
                  AND p.id != sl.id
                  AND p.usage = 'internal'
                ORDER BY LENGTH(p.parent_path) ASC
                LIMIT 1
            )
            WHERE sl.usage = 'internal'
            ORDER BY sl.complete_name
        """)
        rows = cr.fetchall()

        # Warehouse cache (ayrıca SQL ile)
        cr.execute("""
            SELECT sl.id, sw.name
            FROM stock_warehouse sw
            JOIN stock_location sl ON sl.id = sw.lot_stock_id
        """)
        wh_map = {}
        for loc_id, wh_name in cr.fetchall():
            wh_map[loc_id] = wh_name

        # Her lokasyon için warehouse bul (parent_path üzerinden)
        cr.execute("""
            SELECT sl.id, sw.name
            FROM stock_location sl
            JOIN stock_warehouse sw ON sl.parent_path LIKE
                (SELECT parent_path FROM stock_location WHERE id = sw.lot_stock_id) || '%%'
            WHERE sl.usage = 'internal'
        """)
        loc_wh = {}
        for loc_id, wh_name in cr.fetchall():
            loc_wh[loc_id] = wh_name

        _logger.info("Raf export: %d lokasyon bulundu", len(rows))

        # ─── EXCEL OLUŞTUR ───
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Raf Detay Listesi"

        # Stiller
        header_font = Font(name='Calibri', bold=True, color='FFFFFF', size=11)
        header_fill = PatternFill(start_color='2E4057', end_color='2E4057',
                                  fill_type='solid')
        header_align = Alignment(horizontal='center', vertical='center',
                                 wrap_text=True)
        thin_border = Border(
            left=Side(style='thin', color='D0D0D0'),
            right=Side(style='thin', color='D0D0D0'),
            top=Side(style='thin', color='D0D0D0'),
            bottom=Side(style='thin', color='D0D0D0'),
        )
        row_fill_even = PatternFill(start_color='F5F7FA', end_color='F5F7FA',
                                    fill_type='solid')
        data_align = Alignment(vertical='center')

        # Başlıklar
        headers = [
            'Path', 'Name', 'Id', 'Unique Code', 'Global Slot',
            'Total Quantity', 'Type', 'Code', 'Is Pick',
            'Warehouse', 'Max Sku Count', 'Is Pool', 'Is Salable',
            'Is Shelf', 'Slot', 'Shelf Restriction', 'Pallet Restriction',
            'Is Countable', 'Is Reservable', 'Extra Shelf Life',
            'Width', 'Height', 'Length', 'Product Group',
        ]

        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = thin_border

        # Veri satırları
        usage_map = {
            'supplier': 'Supplier', 'view': 'View', 'internal': 'Normal',
            'customer': 'Customer', 'inventory': 'Inventory',
            'transit': 'Transit', 'production': 'Production',
        }

        for row_idx, row in enumerate(rows, 2):
            (loc_id, complete_name, name, barcode, usage,
             posx, posy, posz, scrap, wh_name,
             child_count, total_qty, product_count) = row

            warehouse = loc_wh.get(loc_id, wh_name or '')
            has_children = child_count > 0

            slot_parts = []
            if posx: slot_parts.append(str(posx))
            if posy: slot_parts.append(str(posy))
            if posz: slot_parts.append(str(posz))
            slot = '.'.join(slot_parts) if slot_parts else ''

            row_data = [
                complete_name or '',
                name or '',
                loc_id,
                barcode or '',
                slot or 'ALL',
                total_qty,
                usage_map.get(usage, usage or ''),
                barcode or '',
                'Yes' if usage == 'internal' and not has_children else 'No',
                warehouse or '',
                product_count,
                'No',
                'Yes' if usage == 'internal' else 'No',
                'Yes' if not has_children and usage == 'internal' else 'No',
                slot or 'ALL',
                'ALL',
                'ALL',
                'Yes' if usage == 'internal' else 'No',
                'Yes' if usage == 'internal' and not scrap else 'No',
                0, 0, 0, 0, '',
            ]

            for col_idx, value in enumerate(row_data, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border = thin_border
                cell.alignment = data_align
                if row_idx % 2 == 0:
                    cell.fill = row_fill_even

        # Sütun genişlikleri
        col_widths = {
            1: 40, 2: 20, 3: 8, 4: 16, 5: 12,
            6: 14, 7: 10, 8: 16, 9: 8,
            10: 20, 11: 14, 12: 8, 13: 10,
            14: 8, 15: 10, 16: 16, 17: 16,
            18: 12, 19: 12, 20: 14,
            21: 8, 22: 8, 23: 8, 24: 14,
        }
        for col, width in col_widths.items():
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = width

        ws.auto_filter.ref = f"A1:{openpyxl.utils.get_column_letter(len(headers))}1"
        ws.freeze_panes = 'A2'

        # Dosya döndür
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        file_data = output.read()

        filename = f"raf_detay_listesi_{dt.now().strftime('%Y-%m-%d_%H-%M')}.xlsx"

        headers_resp = [
            ('Content-Type',
             'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', content_disposition(filename)),
            ('Content-Length', len(file_data)),
        ]
        return request.make_response(file_data, headers=headers_resp)
