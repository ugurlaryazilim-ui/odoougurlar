import base64
import io
import logging
import os
import zipfile

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Desteklenen görsel uzantıları
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff'}

# NEDEN: zip bomb koruması. Sınırlar ZIP'in başlığındaki (central directory) açılmış boyuta
# göre işlenir; zipfile (ZipExtFile) üye okumasını bildirilen file_size'da keser, yani başlık
# yalan söylese bile bir üye bildirilen boyuttan fazla bellek almaz.
# EKIP-BORC: sınırlar sabit; kurulum bazlı ayar istenirse ir.config_parameter'dan okunmalı.
MAX_ZIP_FILES = 5000
MAX_ZIP_TOTAL_BYTES = 2 * 1024 ** 3
MAX_IMAGE_BYTES = 50 * 1024 ** 2


class BulkImageWizard(models.TransientModel):
    """ZIP dosyası ile toplu ürün görseli yükleme sihirbazı."""
    _name = 'ugurlar.bulk.image.wizard'
    _description = 'Toplu Görsel Yükleme Sihirbazı'

    zip_file = fields.Binary(string='ZIP Dosyası', required=True,
                             help='İçinde barkod isimli görseller bulunan .zip dosyası')
    zip_filename = fields.Char(string='Dosya Adı')
    result_message = fields.Text(string='Sonuç', readonly=True)

    # ----- Ayar yardımcıları -----

    # Selection key → gerçek karakter (image_settings.py'deki ile aynı)
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

    # ----- Renk kardeşi bulma -----

    def _find_color_siblings(self, variant):
        """
        Bir varyantın aynı renkteki kardeşlerini bul.
        Odoo 19 product.template.attribute.value üzerinden çalışır.

        Returns: recordset of product.product (kendisi HARİÇ)
        """
        color_attr_name = 'Renk'  # TODO: config'den alınabilir
        ptavs = variant.product_template_attribute_value_ids

        if not ptavs:
            return self.env['product.product']

        # 'Renk' özelliğine ait PTAV'ı bul
        color_ptav = ptavs.filtered(
            lambda p: p.attribute_id.name.lower() in (color_attr_name.lower(), 'color', 'colour')
        )

        if not color_ptav:
            return self.env['product.product']

        # Aynı template + aynı renk değerine sahip diğer varyantları bul
        siblings = self.env['product.product'].search([
            ('product_tmpl_id', '=', variant.product_tmpl_id.id),
            ('product_template_attribute_value_ids', 'in', color_ptav.ids),
            ('id', '!=', variant.id),
        ])

        return siblings

    def _clean_variant_images(self, variants):
        """Varyantların (recordset) tüm eski ek resimlerini tek sorgu/silmeyle sil."""
        old_images = self.env['product.image'].search([
            ('product_variant_id', 'in', variants.ids),
        ])
        count = len(old_images)
        old_images.unlink()
        return count

    # ----- Log (ayrı transaction) -----

    def _save_log(self, vals, log_id=None):
        """Log kaydını AYRI cursor'da yazıp commit eder; ana işlem geri alınsa da log kalır."""
        with self.env.registry.cursor() as cr:
            Log = self.env(cr=cr)['ugurlar.image.sync.log']
            if log_id:
                Log.browse(log_id).write(vals)
                return log_id
            return Log.create(vals).id

    # ----- ZIP okuma -----

    def _open_zip_source(self):
        """
        ZIP'i dosya nesnesi olarak aç. self.zip_file (tüm içeriğin base64 hali) okunmaz:
        attachment filestore'daysa diskten akış okunur, değilse ham bayt (base64'ün 1/3 küçüğü).
        """
        self.flush_recordset(['zip_file'])
        att = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', self._name),
            ('res_field', '=', 'zip_file'),
            ('res_id', '=', self.id),
        ], limit=1)
        if att and att.store_fname:
            return open(att._full_path(att.store_fname), 'rb')
        if att:
            return io.BytesIO(att.raw)
        return io.BytesIO(base64.b64decode(self.zip_file))

    def _group_zip_members(self, zf, separator, main_index):
        """
        Üyeleri içerik OKUMADAN barkoda göre grupla: {barkod: [(sıra, dosya_adı, ZipInfo)]}.
        Boyut sınırları burada, hiçbir şey açılmadan uygulanır.
        """
        members = [m for m in zf.infolist() if not m.is_dir()]
        if len(members) > MAX_ZIP_FILES:
            raise UserError(
                f'ZIP içinde çok fazla dosya var ({len(members)}). '
                f'En fazla {MAX_ZIP_FILES} dosya yüklenebilir; ZIP\'i parçalara bölün.'
            )
        total = sum(m.file_size for m in members)
        if total > MAX_ZIP_TOTAL_BYTES:
            raise UserError(
                f'ZIP\'in açılmış boyutu çok büyük ({total // 1024 ** 2} MB). '
                f'En fazla {MAX_ZIP_TOTAL_BYTES // 1024 ** 2} MB açılabilir; ZIP\'i parçalara bölün.'
            )

        image_groups = {}
        skipped_files = []
        for member in members:
            filename = os.path.basename(member.filename)
            name, ext = os.path.splitext(filename)

            if ext.lower() not in ALLOWED_EXTENSIONS:
                skipped_files.append(f'{filename} → Desteklenmeyen format')
                continue
            if member.file_size > MAX_IMAGE_BYTES:
                skipped_files.append(
                    f'{filename} → Dosya çok büyük ({member.file_size // 1024 ** 2} MB, '
                    f'en fazla {MAX_IMAGE_BYTES // 1024 ** 2} MB)'
                )
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

            image_groups.setdefault(barcode, []).append((order, filename, member))
        return image_groups, skipped_files

    # ----- Tek barkod işlemi -----

    def _import_barcode(self, variant, images, zf, main_index, overwrite):
        """
        Bir barkodun görsellerini varyanta ve renk kardeşlerine yaz. Rapor satırlarını döndürür.
        Yalnız bu barkodun görselleri aynı anda bellekte tutulur.
        """
        details = []
        barcode = variant.barcode
        tmpl = variant.product_tmpl_id

        # ── Hedef varyantları belirle (renk yayma) ──
        targets = variant
        siblings = self._find_color_siblings(variant)
        if siblings:
            targets |= siblings
            sib_barcodes = ', '.join(s.barcode or s.name for s in siblings)
            details.append(f'  🎨 {barcode} renk kardeşleri: {sib_barcodes}')

        self._clean_variant_images(targets)

        images.sort(key=lambda x: x[0])
        for order, fname, member in images:
            img_b64 = base64.b64encode(zf.read(member))

            if str(order) == main_index:
                todo = targets if overwrite else targets.filtered(lambda t: not t.image_variant_1920)
                if variant not in todo:
                    details.append(f'  ✓ {fname} → {variant.barcode or variant.name} (mevcut, atlandı)')
                if not todo:
                    continue
                # NEDEN: kardeşlere tek write; döngüde tek tek write, her biri için ayrı
                # resize/yeniden hesap ve SQL UPDATE demek.
                todo.write({'image_variant_1920': img_b64})

                # Template kapak görseli — compute override ile güvenli
                if not tmpl.image_1920:
                    tmpl.image_1920 = img_b64
                    details.append('  🖼️ Template kapak görseli ayarlandı')

                for tv in todo:
                    tv_barcode = tv.barcode or tv.name
                    if tv == variant:
                        details.append(f'  ✓ {fname} → {tv_barcode} (ANA RESİM)')
                    else:
                        details.append(f'    🎨 ANA → {tv_barcode} (renk kardeşi)')
            else:
                # Ek resim — VARYANT (barkod) bazlı; hedeflerin hepsi tek create ile
                self.env['product.image'].create([{
                    'product_variant_id': tv.id,
                    'product_tmpl_id': tv.product_tmpl_id.id,
                    'name': f'{tv.barcode or tv.name}_{order}',
                    'image_1920': img_b64,
                } for tv in targets])
                for tv in targets:
                    tv_barcode = tv.barcode or tv.name
                    if tv == variant:
                        details.append(f'  ✓ {fname} → {tv_barcode} (ek resim #{order})')
                    else:
                        details.append(f'    🎨 EK #{order} → {tv_barcode} (renk kardeşi)')
        return details

    # ----- Ana işlem -----

    def action_import_images(self):
        """ZIP dosyasını açar, her görseli barkodla eşler ve ürüne atar."""
        self.ensure_one()

        if not self.zip_file:
            raise UserError('Lütfen bir ZIP dosyası seçin!')

        log_id = self._save_log({
            'name': f'ZIP Yükleme: {self.zip_filename or "dosya.zip"}',
            'sync_type': 'zip',
            'state': 'running',
        })

        try:
            log_vals, report = self._run_import()
        except Exception as e:
            # NEDEN: UserError ile ana transaction geri alınır; log ayrı cursor'da yazıldığı için
            # hata nedeni kaybolmaz.
            # NEDEN: UserError metni bilerek yazılmış; diğer istisnalar (FileNotFoundError vb.)
            # filestore yolu gibi sunucu ayrıntısı taşıyabilir, kullanıcıya/log kaydına yalnız türü gider.
            msg = str(e) if isinstance(e, UserError) else type(e).__name__
            self._save_log({
                'state': 'error',
                'detail_log': f'HATA: {msg}',
                'end_date': fields.Datetime.now(),
            }, log_id)
            if isinstance(e, UserError):
                raise
            _logger.exception('ZIP toplu görsel yükleme hatası')
            raise UserError(f'ZIP işleme hatası: {msg}') from e

        self._save_log(log_vals, log_id)
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

    def _run_import(self):
        """ZIP'i işle. (log değerleri, rapor metni) döndürür."""
        separator = self._get_separator()
        main_index = self._get_main_index()
        match_field = self._get_match_field()
        overwrite = self._get_overwrite()

        with self._open_zip_source() as src:
            if not zipfile.is_zipfile(src):
                raise UserError('Yüklenen dosya geçerli bir ZIP dosyası değil!')
            src.seek(0)
            with zipfile.ZipFile(src, 'r') as zf:
                image_groups, skipped_files = self._group_zip_members(zf, separator, main_index)

                # Barkod → varyant id: tek sorgu (barkod başına search yok). İlk eşleşme geçerli.
                # NEDEN: kayıt değil id tutulur; döngüde browse edilen tek kayıtlık prefetch,
                # aramadaki tüm varyantların görsellerinin toplu okunmasını önler.
                variants_by_code = {}
                for v in self.env['product.product'].search([(match_field, 'in', list(image_groups))]):
                    variants_by_code.setdefault(v[match_field], v.id)

                matched = 0
                not_found = []
                errors = []
                details = []
                for barcode, images in image_groups.items():
                    variant_id = variants_by_code.get(barcode)
                    if not variant_id:
                        not_found.append(barcode)
                        continue
                    variant = self.env['product.product'].browse(variant_id)
                    # NEDEN: barkod başına savepoint; bozuk bir görsel yalnız o barkodu geri alır,
                    # diğer barkodlar ve log korunur.
                    try:
                        with self.env.cr.savepoint():
                            details += self._import_barcode(variant, images, zf, main_index, overwrite)
                            self.env.flush_all()  # DB hataları savepoint içinde patlasın
                        matched += 1
                    except Exception as e:  # noqa: BLE001 — barkod hatası toplanır, diğerleri sürer
                        _logger.warning('Toplu görsel: %s işlenemedi: %s', barcode, e)
                        errors.append(f'{barcode} → {e}')
                    # NEDEN: yazılan görsel, 1024/512/256/128 yeniden boyutları ve ek resimler env
                    # önbelleğinde kalır; boşaltılmazsa tepe bellek barkod sayısıyla doğrusal artar
                    # (~12 MB/barkod, limit_memory_soft=4GB'a çarpar). flush_all savepoint içinde yapıldı.
                    # DIKKAT: döngü dışında değişkende tutulan kayıtlar boşaltmadan sonra yeniden okunur.
                    self.env.invalidate_all()

        total = len(image_groups)
        error_count = len(not_found) + len(errors)
        skipped_count = len(skipped_files)

        report_lines = [
            '═══ TOPLU GÖRSEL YÜKLEME RAPORU ═══',
            '',
            f'📦 ZIP Dosyası: {self.zip_filename}',
            f'📊 Toplam Barkod: {total}',
            f'✅ Eşleşen: {matched}',
            f'⏭️  Atlanan Dosya: {skipped_count}',
            f'❌ Bulunamayan Barkod: {len(not_found)}',
            f'🛑 Hatalı Barkod: {len(errors)}',
            '',
        ]
        if details:
            report_lines += ['── Başarılı Eşleştirmeler ──', *details, '']
        if not_found:
            report_lines += ['── Bulunamayan Barkodlar ──', *(f'  ✗ {nf}' for nf in not_found), '']
        if errors:
            report_lines += ['── Hatalı Barkodlar (geri alındı) ──', *(f'  ✗ {er}' for er in errors), '']
        if skipped_files:
            report_lines += ['── Atlanan Dosyalar ──', *(f'  ⚠ {sf}' for sf in skipped_files)]

        report = '\n'.join(report_lines)
        return {
            'state': 'done',
            'total_files': sum(len(imgs) for imgs in image_groups.values()),
            'matched_count': matched,
            'skipped_count': skipped_count,
            'error_count': error_count,
            'detail_log': report,
            'end_date': fields.Datetime.now(),
        }, report
