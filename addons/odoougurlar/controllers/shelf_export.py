"""Raf Detay Dosyası Excel Export Controller."""
import io
import logging

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
            return request.not_found()

        locations = request.env['stock.location'].sudo().search(
            [('usage', '=', 'internal')], order='complete_name',
        )

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Raf Detay Listesi"

        # ─── BAŞLIK STİLLERİ ───
        header_font = Font(name='Calibri', bold=True, color='FFFFFF', size=11)
        header_fill = PatternFill(start_color='2E4057', end_color='2E4057', fill_type='solid')
        header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
        thin_border = Border(
            left=Side(style='thin', color='D0D0D0'),
            right=Side(style='thin', color='D0D0D0'),
            top=Side(style='thin', color='D0D0D0'),
            bottom=Side(style='thin', color='D0D0D0'),
        )

        # ─── SÜTUN BAŞLIKLARI (HamurLabs formatı) ───
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

        # ─── VERİ SATIRLARI ───
        usage_map = {
            'supplier': 'Supplier', 'view': 'View', 'internal': 'Normal',
            'customer': 'Customer', 'inventory': 'Inventory',
            'transit': 'Transit', 'production': 'Production',
        }
        row_fill_even = PatternFill(start_color='F5F7FA', end_color='F5F7FA', fill_type='solid')
        data_align = Alignment(vertical='center')

        for row_idx, loc in enumerate(locations, 2):
            warehouse_name = ''
            if loc.warehouse_id:
                warehouse_name = loc.warehouse_id.name or ''

            has_children = bool(loc.child_ids)

            slot_parts = []
            if loc.posx: slot_parts.append(str(loc.posx))
            if loc.posy: slot_parts.append(str(loc.posy))
            if loc.posz: slot_parts.append(str(loc.posz))
            slot = '.'.join(slot_parts) if slot_parts else ''

            total_qty = loc.total_quant_qty
            product_count = len(loc.quant_ids.filtered(lambda q: q.quantity > 0).mapped('product_id'))

            row_data = [
                loc.complete_name or '',
                loc.name or '',
                loc.id,
                loc.barcode or '',
                slot or 'ALL',
                total_qty,
                usage_map.get(loc.usage, loc.usage or ''),
                loc.barcode or '',
                'Yes' if loc.usage == 'internal' and not has_children else 'No',
                warehouse_name,
                product_count,
                'No',
                'Yes' if loc.usage == 'internal' else 'No',
                'Yes' if not has_children and loc.usage == 'internal' else 'No',
                slot or 'ALL',
                'ALL',
                'ALL',
                'Yes' if loc.usage == 'internal' else 'No',
                'Yes' if loc.usage == 'internal' and not loc.scrap_location else 'No',
                0, 0, 0, 0, '',
            ]

            for col_idx, value in enumerate(row_data, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border = thin_border
                cell.alignment = data_align
                if row_idx % 2 == 0:
                    cell.fill = row_fill_even

        # ─── SÜTUN GENİŞLİKLERİ ───
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

        # ─── DOSYA DÖNDÜR ───
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        file_data = output.read()

        from datetime import datetime as dt
        filename = f"raf_detay_listesi_{dt.now().strftime('%Y-%m-%d_%H-%M')}.xlsx"

        headers_resp = [
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', content_disposition(filename)),
            ('Content-Length', len(file_data)),
        ]
        return request.make_response(file_data, headers=headers_resp)
