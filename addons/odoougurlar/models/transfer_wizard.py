"""Transfer Siparişi Oluşturma Sihirbazı."""
import base64
import io
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TransferOrderWizard(models.TransientModel):
    """Depolar arası ürün transferi oluşturma wizard'ı."""
    _name = 'odoougurlar.transfer.wizard'
    _description = 'Transfer Siparişi Oluşturma Sihirbazı'

    source_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kaynak Depo', required=True,
    )
    dest_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Hedef Depo', required=True,
    )
    upload_type = fields.Selection([
        ('excel', 'Excel Yükleme'),
        ('search', 'Ürün Arama'),
    ], string='Ürün Ekleme Yöntemi', default='excel', required=True)
    excel_file = fields.Binary(string='Excel Dosyası')
    excel_filename = fields.Char(string='Dosya Adı')
    line_ids = fields.One2many(
        'odoougurlar.transfer.wizard.line', 'wizard_id',
        string='Ürün Listesi',
    )
    # Ürün arama alanı
    search_barcode = fields.Char(string='Barkod / Ürün Kodu')
    search_qty = fields.Float(string='Adet', default=1.0)

    # Sonuç bilgileri
    warning_message = fields.Text(string='Uyarılar', readonly=True)

    def action_parse_excel(self):
        """Excel dosyasını parse et ve ürün satırlarını oluştur."""
        self.ensure_one()
        if not self.excel_file:
            raise UserError("Önce bir Excel dosyası yükleyin!")
        try:
            self._parse_excel()
        except Exception as e:
            raise UserError(f"Excel okuma hatası: {e}")
        # Wizard'ı yeniden aç (satırlar DB'de artık)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _parse_excel(self):
        """Excel dosyasını parse edip line'ları doldur."""
        try:
            import openpyxl
        except ImportError:
            raise UserError("openpyxl kütüphanesi bulunamadı!")

        file_data = base64.b64decode(self.excel_file)
        wb = openpyxl.load_workbook(io.BytesIO(file_data), read_only=True)
        ws = wb.active

        rows = list(ws.iter_rows(min_row=1, values_only=True))
        if not rows:
            raise UserError("Excel dosyası boş!")

        # Başlık satırında Barkod ve Adet sütunlarını bul
        header = [str(c or '').strip().lower() for c in rows[0]]
        barcode_col = None
        qty_col = None
        for i, h in enumerate(header):
            if h in ('barkod', 'barcode'):
                barcode_col = i
            elif h in ('adet', 'quantity', 'qty', 'miktar'):
                qty_col = i

        if barcode_col is None:
            raise UserError(
                "Excel'de 'Barkod' sütunu bulunamadı!\n"
                "İlk satırda 'Barkod' veya 'Barcode' başlığı olmalı."
            )

        # Mevcut satırları temizle (DB'den)
        self.line_ids.unlink()
        lines = []
        warnings = []
        env = self.env

        for row_idx, row in enumerate(rows[1:], 2):
            barcode = str(row[barcode_col] or '').strip()
            if not barcode:
                continue

            qty = 1.0
            if qty_col is not None and row[qty_col]:
                try:
                    qty = float(row[qty_col])
                except (ValueError, TypeError):
                    qty = 1.0

            if qty <= 0:
                continue

            # Ürünü bul: barcode, nebim_barcode veya default_code
            product = env['product.product'].search([
                '|', '|',
                ('barcode', '=', barcode),
                ('nebim_barcode', '=', barcode),
                ('default_code', '=', barcode),
            ], limit=1)

            if not product:
                warnings.append(f"Satır {row_idx}: Barkod '{barcode}' bulunamadı — atlandı")
                continue

            self.env['odoougurlar.transfer.wizard.line'].create({
                'wizard_id': self.id,
                'product_id': product.id,
                'barcode': barcode,
                'quantity': qty,
            })

        if warnings:
            self.warning_message = '\n'.join(warnings)
        else:
            self.warning_message = False

    def action_add_product(self):
        """Ürün arama ile tek ürün ekle."""
        self.ensure_one()
        if not self.search_barcode:
            raise UserError("Barkod veya ürün kodu girin!")

        barcode = self.search_barcode.strip()
        product = self.env['product.product'].search([
            '|', '|',
            ('barcode', '=', barcode),
            ('nebim_barcode', '=', barcode),
            ('default_code', '=', barcode),
        ], limit=1)

        if not product:
            raise UserError(f"Barkod '{barcode}' ile ürün bulunamadı!")

        # Aynı ürün zaten varsa miktarını artır
        existing = self.line_ids.filtered(lambda l: l.product_id == product)
        if existing:
            existing[0].quantity += self.search_qty or 1.0
        else:
            self.env['odoougurlar.transfer.wizard.line'].create({
                'wizard_id': self.id,
                'product_id': product.id,
                'barcode': barcode,
                'quantity': self.search_qty or 1.0,
            })

        # Alanları temizle
        self.search_barcode = False
        self.search_qty = 1.0

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_create_transfer(self):
        """Transfer siparişi (stock.picking) oluştur."""
        self.ensure_one()

        if not self.line_ids.filtered(lambda l: l.product_id):
            raise UserError("Ürün listesi boş! Önce ürün ekleyin.")

        if self.source_warehouse_id == self.dest_warehouse_id:
            raise UserError("Kaynak ve hedef depo aynı olamaz!")

        source_loc = self.source_warehouse_id.lot_stock_id
        dest_loc = self.dest_warehouse_id.lot_stock_id

        # Transfer picking type bul veya oluştur
        picking_type = self._get_transfer_picking_type()

        # Sequence: T00001 formatı
        seq_name = self.env['ir.sequence'].next_by_code(
            'odoougurlar.transfer.order'
        )
        if not seq_name:
            seq_name = 'T00001'

        # Stok kontrol — uyarılar
        warnings = []
        valid_lines = []
        for line in self.line_ids:
            if not line.product_id:
                continue
            # Kaynak depodaki stok
            available = self.env['stock.quant']._get_available_quantity(
                line.product_id, source_loc,
            )
            if available <= 0:
                warnings.append(
                    f"⚠ {line.product_id.display_name} — "
                    f"kaynak depoda stok yok, atlandı!"
                )
                continue
            elif available < line.quantity:
                warnings.append(
                    f"⚠ {line.product_id.display_name} — "
                    f"istenen: {line.quantity}, mevcut: {available}. "
                    f"Mevcut kadar ({available}) aktarılacak."
                )
                valid_lines.append((line, available))
            else:
                valid_lines.append((line, line.quantity))

        if not valid_lines:
            msg = "Hiçbir ürün için yeterli stok bulunamadı!\n"
            if warnings:
                msg += '\n'.join(warnings)
            raise UserError(msg)

        # Picking oluştur
        picking_vals = {
            'picking_type_id': picking_type.id,
            'location_id': source_loc.id,
            'location_dest_id': dest_loc.id,
            'origin': seq_name,
            'note': f"Transfer: {self.source_warehouse_id.name} → "
                    f"{self.dest_warehouse_id.name}\n"
                    f"Oluşturan: {self.env.user.name}",
        }
        picking = self.env['stock.picking'].create(picking_vals)

        # Move'lar oluştur
        for line, qty in valid_lines:
            self.env['stock.move'].create({
                'product_id': line.product_id.id,
                'product_uom_qty': qty,
                'product_uom': line.product_id.uom_id.id,
                'picking_id': picking.id,
                'location_id': source_loc.id,
                'location_dest_id': dest_loc.id,
            })

        # Picking'i onayla ve rezerve et
        picking.action_confirm()
        picking.action_assign()

        # ─── Batch Picking (Rota Toplama) oluştur ───
        # T00001 adıyla batch oluştur, picking'i bağla
        batch = self.env['stock.picking.batch'].create({
            'name': seq_name,
            'picking_type_id': picking_type.id,
            'picking_ids': [(4, picking.id)],
        })
        _logger.info(
            "Batch picking oluşturuldu: %s (picking: %s)",
            batch.name, picking.name,
        )

        _logger.info(
            "Transfer oluşturuldu: %s — %s → %s, %d ürün",
            seq_name, self.source_warehouse_id.name,
            self.dest_warehouse_id.name, len(valid_lines),
        )

        # Uyarıları göster ve picking'e yönlendir
        if warnings:
            # Uyarılı sonuç wizard'ı göster
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'odoougurlar.transfer.result.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_picking_id': picking.id,
                    'default_message': (
                        f"✅ Transfer oluşturuldu: {seq_name}\n"
                        f"📦 {len(valid_lines)} ürün eklendi\n\n"
                        f"⚠ Uyarılar:\n" + '\n'.join(warnings)
                    ),
                },
            }

        # Doğrudan picking'e yönlendir
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _get_transfer_picking_type(self):
        """Transfer için picking type bul veya oluştur."""
        source_wh = self.source_warehouse_id
        # Kaynak deponun internal transfer type'ını bul
        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', source_wh.id),
            ('code', '=', 'internal'),
        ], limit=1)

        if not picking_type:
            # Yoksa herhangi bir internal type
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
            ], limit=1)

        if not picking_type:
            raise UserError("Dahili transfer tipi bulunamadı!")

        return picking_type


class TransferOrderWizardLine(models.TransientModel):
    """Transfer siparişi ürün satırı."""
    _name = 'odoougurlar.transfer.wizard.line'
    _description = 'Transfer Siparişi Ürün Satırı'

    wizard_id = fields.Many2one(
        'odoougurlar.transfer.wizard', string='Wizard',
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.product', string='Ürün',
    )
    barcode = fields.Char(string='Barkod')
    quantity = fields.Float(string='Adet', default=1.0, required=True)
    product_name = fields.Char(
        string='Ürün Adı', related='product_id.display_name', readonly=True,
    )


class TransferResultWizard(models.TransientModel):
    """Transfer sonucu gösterme wizard'ı."""
    _name = 'odoougurlar.transfer.result.wizard'
    _description = 'Transfer Sonucu'

    picking_id = fields.Many2one('stock.picking', string='Transfer')
    message = fields.Text(string='Sonuç', readonly=True)

    def action_open_picking(self):
        """Oluşturulan transfer'e git."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
