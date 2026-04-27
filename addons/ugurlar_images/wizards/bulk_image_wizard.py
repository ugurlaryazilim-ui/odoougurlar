import base64
import io
import logging
import os
import zipfile

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Desteklenen görsel uzantıları
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff'}


class BulkImageWizard(models.TransientModel):
    """ZIP dosyası ile toplu ürün görseli yükleme sihirbazı."""
    _name = 'ugurlar.bulk.image.wizard'
    _description = 'Toplu Görsel Yükleme Sihirbazı'

    zip_file = fields.Binary(string='ZIP Dosyası', required=True,
                             help='İçinde barkod isimli görseller bulunan .zip dosyası')
    zip_filename = fields.Char(string='Dosya Adı')
    result_message = fields.Text(string='Sonuç', readonly=True)

    # ----- Ayar yardımcıları -----

    # Selection key → gerçek karakter
    SEPARATOR_MAP = {'underscore': '_', 'dash': '-', 'dot': '.'}
    INDEX_MAP = {'idx0': '0', 'idx1': '1'}

    def _get_separator(self):
        ICP = self.env['ir.config_parameter'].sudo()
        key = ICP.get_param('ugurlar_images.image_separator', 'underscore')
        return self.SEPARATOR_MAP.get(key, '_')

    def _get_main_index(self):
        ICP = self.env['ir.config_parameter'].sudo()
        key = ICP.get_param('ugurlar_images.main_image_index', 'idx1')
        return self.INDEX_MAP.get(key, '1')

    def _get_match_field(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return ICP.get_param('ugurlar_images.image_match_field', 'barcode')

    def _get_overwrite(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return ICP.get_param('ugurlar_images.image_overwrite', 'True') == 'True'

    # ----- Ana işlem -----

    def action_import_images(self):
        """ZIP dosyasını açar, her görseli barkodla eşler ve ürüne atar."""
        self.ensure_one()

        if not self.zip_file:
            raise UserError('Lütfen bir ZIP dosyası seçin!')

        separator = self._get_separator()
        main_index = self._get_main_index()
        match_field = self._get_match_field()
        overwrite = self._get_overwrite()

        # Log kaydı oluştur
        log = self.env['ugurlar.image.sync.log'].create({
            'name': f'ZIP Yükleme: {self.zip_filename or "dosya.zip"}',
            'sync_type': 'zip',
            'state': 'running',
        })

        try:
            # ZIP dosyasını aç
            zip_data = base64.b64decode(self.zip_file)
            zip_buffer = io.BytesIO(zip_data)

            if not zipfile.is_zipfile(zip_buffer):
                raise UserError('Yüklenen dosya geçerli bir ZIP dosyası değil!')

            zip_buffer.seek(0)
            zf = zipfile.ZipFile(zip_buffer, 'r')

            # Dosyaları grupla: { barkod: [(sıra, dosya_adı, data)] }
            image_groups = {}
            skipped_files = []

            for file_info in zf.infolist():
                if file_info.is_dir():
                    continue

                filename = os.path.basename(file_info.filename)
                name, ext = os.path.splitext(filename)
                ext_lower = ext.lower()

                # Uzantı kontrolü
                if ext_lower not in ALLOWED_EXTENSIONS:
                    skipped_files.append(f'{filename} → Desteklenmeyen format')
                    continue

                # Barkod ve sıra ayrıştırma
                parts = name.rsplit(separator, 1)
                if len(parts) == 2:
                    barcode = parts[0].strip()
                    try:
                        order = int(parts[1].strip())
                    except ValueError:
                        barcode = name
                        order = int(main_index)
                else:
                    barcode = name
                    order = int(main_index)

                if not barcode:
                    skipped_files.append(f'{filename} → Barkod belirlenemedi')
                    continue

                img_data = zf.read(file_info.filename)
                img_b64 = base64.b64encode(img_data)

                if barcode not in image_groups:
                    image_groups[barcode] = []
                image_groups[barcode].append((order, filename, img_b64))

            zf.close()

            # Ürünlerle eşleştir
            matched = 0
            not_found = []
            details = []

            for barcode, images in image_groups.items():
                # Ürünü bul (varyant seviyesinde)
                domain = [(match_field, '=', barcode)]
                variant = self.env['product.product'].search(domain, limit=1)

                if not variant:
                    not_found.append(barcode)
                    continue

                # Görselleri sırala
                images.sort(key=lambda x: x[0])

                for order, fname, img_b64 in images:
                    is_main = (str(order) == main_index)

                    if is_main:
                        # Ana resim (vitrin görseli) — product.template üzerinde
                        if variant.image_1920 and not overwrite:
                            details.append(f'  ✓ {fname} → {barcode} (mevcut, atlandı)')
                            continue
                        variant.product_tmpl_id.image_1920 = img_b64
                        details.append(f'  ✓ {fname} → {barcode} (ANA RESİM)')
                    else:
                        # Ek resim — VARYANT (barkod) bazlı
                        if 'product.image' in self.env:
                            self.env['product.image'].create({
                                'product_variant_id': variant.id,
                                'name': f'{barcode}_{order}',
                                'image_1920': img_b64,
                            })
                            details.append(f'  ✓ {fname} → {barcode} (ek resim #{order})')
                        else:
                            # product.image yoksa ana görseli güncelle
                            variant.image_1920 = img_b64
                            details.append(f'  ✓ {fname} → {barcode} (resim #{order}, ana olarak)')

                matched += 1

            # Sonuç raporu
            total = len(image_groups)
            error_count = len(not_found)
            skipped_count = len(skipped_files)

            report_lines = [
                f'═══ TOPLU GÖRSEL YÜKLEME RAPORU ═══',
                f'',
                f'📦 ZIP Dosyası: {self.zip_filename}',
                f'📊 Toplam Barkod: {total}',
                f'✅ Eşleşen: {matched}',
                f'⏭️  Atlanan Dosya: {skipped_count}',
                f'❌ Bulunamayan Barkod: {error_count}',
                f'',
            ]

            if details:
                report_lines.append('── Başarılı Eşleştirmeler ──')
                report_lines.extend(details)
                report_lines.append('')

            if not_found:
                report_lines.append('── Bulunamayan Barkodlar ──')
                for nf in not_found:
                    report_lines.append(f'  ✗ {nf}')
                report_lines.append('')

            if skipped_files:
                report_lines.append('── Atlanan Dosyalar ──')
                for sf in skipped_files:
                    report_lines.append(f'  ⚠ {sf}')

            report = '\n'.join(report_lines)

            # Log güncelle
            log.write({
                'state': 'done',
                'total_files': sum(len(imgs) for imgs in image_groups.values()),
                'matched_count': matched,
                'skipped_count': skipped_count,
                'error_count': error_count,
                'detail_log': report,
                'end_date': fields.Datetime.now(),
            })

            self.result_message = report

            # Wizard'ı sonuç ile tekrar göster
            return {
                'type': 'ir.actions.act_window',
                'res_model': self._name,
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
                'name': 'Yükleme Sonucu',
            }

        except UserError:
            raise
        except Exception as e:
            log.write({
                'state': 'error',
                'detail_log': f'HATA: {str(e)}',
                'end_date': fields.Datetime.now(),
            })
            raise UserError(f'ZIP işleme hatası: {str(e)}')
