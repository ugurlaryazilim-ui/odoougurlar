# -*- coding: utf-8 -*-

import base64
import io
import logging
import re
import time
import zipfile
from datetime import datetime
import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class UgurlarInvoiceCollectorWizard(models.TransientModel):
    _name = 'ugurlar.invoice.collector'
    _description = 'Toptan Alış Fatura Toplama & ZIP Arşivleme Wizard'

    brand_id = fields.Many2one(
        'product.attribute.value',
        string='Marka',
        domain="[('attribute_id.name', 'ilike', 'Marka')]",
        help='Faturaları taranacak marka'
    )
    product_group_id = fields.Many2one(
        'product.attribute.value',
        string='Ürün Grubu',
        domain="[('attribute_id.name', 'ilike', 'Ürün Grubu')]",
        help='Faturaları taranacak ürün grubu'
    )
    date_start = fields.Date(string='Başlangıç Tarihi')
    date_end = fields.Date(string='Bitiş Tarihi')
    
    batch_size = fields.Integer(
        string='Paket İndirme Boyutu (Batch)',
        default=15,
        help='Her mikro-adımda işlenecek fatura sayısı.'
    )

    state = fields.Selection([
        ('draft', 'Taslak'),
        ('scanned', 'Faturalar Bulundu'),
        ('downloading', 'İndiriliyor...'),
        ('completed', 'ZIP Oluşturuldu'),
    ], string='Durum', default='draft')

    line_ids = fields.One2many(
        'ugurlar.invoice.collector.line',
        'wizard_id',
        string='Bulunan Faturalar'
    )

    zip_file = fields.Binary(string='ZIP Dosyası', readonly=True, attachment=True)
    zip_filename = fields.Char(string='ZIP Dosya Adı', readonly=True)
    
    total_found_invoices = fields.Integer(string='Bulunan Fatura Sayısı', compute='_compute_totals', store=True)
    selected_invoices_count = fields.Integer(string='Seçili Fatura Sayısı', compute='_compute_totals', store=True)

    processed_count = fields.Integer(string='İşlenen Fatura', compute='_compute_progress', store=True)
    pending_count = fields.Integer(string='Bekleyen Fatura', compute='_compute_progress', store=True)
    progress_percent = fields.Float(string='İlerleme Yüzdesi', compute='_compute_progress', store=True)
    progress_text = fields.Char(string='İndirme İlerlemesi', compute='_compute_progress', store=True)

    @api.depends('line_ids', 'line_ids.selected')
    def _compute_totals(self):
        for rec in self:
            rec.total_found_invoices = len(rec.line_ids)
            rec.selected_invoices_count = len(rec.line_ids.filtered(lambda l: l.selected))

    @api.depends('line_ids', 'line_ids.selected', 'line_ids.download_status')
    def _compute_progress(self):
        for rec in self:
            selected = rec.line_ids.filtered(lambda l: l.selected)
            processed = selected.filtered(lambda l: l.download_status in ('success', 'error'))
            pending = selected.filtered(lambda l: l.download_status == 'pending')
            
            rec.processed_count = len(processed)
            rec.pending_count = len(pending)
            total = len(selected)
            
            if total > 0:
                rec.progress_percent = (len(processed) / total) * 100.0
                rec.progress_text = f"{len(processed)} / {total} (%{int(rec.progress_percent)})"
            else:
                rec.progress_percent = 0.0
                rec.progress_text = "0 / 0 (%0)"

    @staticmethod
    def _extract_item_code(variant_sku):
        """
        Varyant SKU'sundan ana ürün kodunu (Nebim ItemCode) çıkarır.
        Varyant formatı: {ItemCode}-{RenkKodu}-{Beden}
        Örnek: '2W22CT1333PR-0138-M' → '2W22CT1333PR'
        """
        match = re.match(r'^(.+)-\d{3,4}-.+$', variant_sku)
        if match:
            return match.group(1)
        return variant_sku

    def action_scan_invoices(self):
        """
        Seçilen Marka ve Ürün Grubu filtrelerine uyan Odoo ürünlerinin
        ItemCode (default_code) listesini alır, Nebim SP'sini çağırarak
        Toptan Alış belgelerini tekleştirilmiş olarak çeker.
        """
        self.ensure_one()
        
        template_domain = []
        if self.brand_id:
            template_domain.append(('attribute_line_ids.value_ids', '=', self.brand_id.id))
        if self.product_group_id:
            template_domain.append(('attribute_line_ids.value_ids', '=', self.product_group_id.id))

        if not template_domain:
            raise UserError('Lütfen en az bir filtre kriteri (Marka veya Ürün Grubu) seçiniz.')

        templates = self.env['product.template'].search(template_domain)
        _logger.info("Fatura Tarama: %d adet ürün şablonu bulundu.", len(templates))

        item_codes = set()
        for tmpl in templates:
            for variant in tmpl.product_variant_ids:
                code = variant.default_code or tmpl.default_code
                if code:
                    main_code = self._extract_item_code(code.strip())
                    item_codes.add(main_code)
            if not tmpl.product_variant_ids and tmpl.default_code:
                main_code = self._extract_item_code(tmpl.default_code.strip())
                item_codes.add(main_code)
        
        if not item_codes:
            raise UserError(
                f'{len(templates)} adet ürün şablonu bulundu ama hiçbirinin ItemCode (default_code) alanı dolu değil.\n'
                'Lütfen ürünlerin Dahili Referans (default_code) alanlarını kontrol edin.'
            )

        _logger.info("Fatura Tarama: %d adet benzersiz ana ürün kodu (ItemCode) bulundu. Nebim SP çağrılıyor...", len(item_codes))
        
        sample_codes = list(item_codes)[:5]
        _logger.info("Fatura Tarama - Örnek ItemCode'lar: %s", sample_codes)

        connector = self.env['odoougurlar.nebim.connector'].sudo()
        all_results = []
        batch_sz = 20
        code_list = list(item_codes)
        
        try:
            for i in range(0, len(code_list), batch_sz):
                batch = code_list[i:i + batch_sz]
                batch_str = ','.join(batch)
                _logger.info("Fatura Tarama - Batch %d/%d: %d kod gönderiliyor...", 
                           (i // batch_sz) + 1, 
                           (len(code_list) + batch_sz - 1) // batch_sz,
                           len(batch))
                
                sp_params = [{'Name': '@ItemCode', 'Value': batch_str}]
                batch_results = connector.run_proc('usp_GetPurchaseInvoices_Ugurlar', sp_params)
                
                if batch_results and isinstance(batch_results, list):
                    _logger.info("Fatura Tarama - Batch sonucu: %d kayıt", len(batch_results))
                    all_results.extend(batch_results)
                else:
                    _logger.info("Fatura Tarama - Batch sonucu: 0 kayıt (boş veya dict)")
        except Exception as e:
            raise UserError(f'Nebim prosedürü çalıştırılırken hata oluştu: {str(e)}')

        if not all_results:
            raise UserError(
                f'Nebim veritabanından bu ürünler için Toptan Alış faturası bulunamadı.\n'
                f'Toplam {len(item_codes)} adet ItemCode denendi.\n'
                f'Örnek kodlar: {", ".join(sample_codes)}\n\n'
                f'Lütfen tbl_EntegraToptanAlisBelge tablosunun güncel olduğundan emin olun\n'
                f'(sp_UpdateEntegraToptanAlisBelge prosedürünü çalıştırın).'
            )
        
        existing_lines = [(5, 0, 0)]
        seen_docs = set()

        for row in all_results:
            doc_num = str(row.get('DocumentNumber', '')).strip()
            if not doc_num or doc_num in seen_docs:
                continue

            doc_date_raw = row.get('DocumentDate')
            doc_date = False
            if doc_date_raw:
                try:
                    if 'T' in str(doc_date_raw):
                        doc_date = fields.Date.from_string(str(doc_date_raw).split('T')[0])
                    else:
                        doc_date = fields.Date.from_string(str(doc_date_raw).split(' ')[0])
                except Exception:
                    doc_date = False

            if self.date_start and doc_date and doc_date < self.date_start:
                continue
            if self.date_end and doc_date and doc_date > self.date_end:
                continue

            seen_docs.add(doc_num)
            existing_lines.append((0, 0, {
                'selected': True,
                'item_code': str(row.get('ItemCode', '')).strip(),
                'document_number': doc_num,
                'document_date': doc_date,
                'vendor_name': str(row.get('VendorName', '')).strip(),
                'ref_number': str(row.get('RefNumber', '')).strip(),
                'download_status': 'pending',
            }))

        if len(existing_lines) <= 1:
            raise UserError('Belirtilen tarih kriterlerine uyan Toptan Alış faturası bulunamadı.')

        self.write({
            'line_ids': existing_lines,
            'state': 'scanned',
            'zip_file': False,
            'zip_filename': False,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _try_download_pdf(self, url, timeout=15):
        """URL'den PDF içeriğini indirmeyi dener. Başarısızsa None döner."""
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200 and len(resp.content) > 100:
                content_type = resp.headers.get('Content-Type', '').lower()
                if 'text/html' not in content_type or resp.content[:5] == b'%PDF-':
                    return resp.content
        except Exception as e:
            _logger.debug("PDF indirme başarısız (%s): %s", url, str(e))
        return None

    def _process_batch_lines(self, batch_lines):
        """15-20 adetlik bir fatura paketinin indirme işlemini gerçekleştirir."""
        connector = self.env['odoougurlar.nebim.connector'].sudo()
        ettn_to_line = {}

        for line in batch_lines:
            doc_num = line.document_number
            pdf_content = None
            
            # Yol 1: e-Arşiv URL'ini dene (giden satış faturaları)
            try:
                params = [{'Name': 'DocumentNumber', 'Value': doc_num}]
                res = connector.run_proc('usp_Invoice_EArchieveURL', params)
                invoice_url = res[0].get('InvoiceURL', '') if (res and isinstance(res, list) and isinstance(res[0], dict)) else ''

                if invoice_url:
                    line.invoice_url = invoice_url
                    pdf_url = invoice_url.replace('view-earchive', 'pdf-earchive') if 'view-earchive' in invoice_url else invoice_url
                    pdf_content = self._try_download_pdf(pdf_url)
                    if pdf_content:
                        safe_vendor = re.sub(r'[^\w\s-]', '', line.vendor_name or '').strip().replace(' ', '_')[:30]
                        file_name = f"{doc_num}_{safe_vendor}.pdf"
                        line.write({
                            'pdf_file': base64.b64encode(pdf_content),
                            'pdf_filename': file_name,
                            'download_status': 'success',
                            'error_message': False,
                        })
                        _logger.info("e-Arşiv PDF başarıyla indirildi: %s", doc_num)
            except Exception as e:
                _logger.warning("e-Arşiv PDF sorgu uyarısı (%s): %s", doc_num, str(e))

            # Yol 2: e-Fatura ETTN al (gelen alış faturaları)
            if not pdf_content:
                try:
                    params = [{'Name': 'DocumentNumber', 'Value': doc_num}]
                    res = connector.run_proc('usp_PurchaseInvoice_EFaturaURL', params)
                    ettn = str(res[0].get('ETTN', '')).strip() if (res and isinstance(res, list) and isinstance(res[0], dict)) else ''
                    
                    if ettn:
                        line.invoice_url = f"ETTN: {ettn}"
                        ettn_to_line[ettn] = line
                    else:
                        line.write({
                            'download_status': 'error',
                            'error_message': 'Nebim ETTN bulunamadı.'
                        })
                        _logger.warning("e-Fatura ETTN bulunamadı: %s", doc_num)
                except Exception as e:
                    line.write({
                        'download_status': 'error',
                        'error_message': f'Nebim ETTN sorgu hatası: {str(e)}'
                    })

        # Doğan SOAP API üzerinden toplu indirme (TEK SOAP LOGIN OTURUMUNDA)
        if ettn_to_line:
            _logger.info("Doğan SOAP API - Batch indirme (%d adet ETTN tek oturumda indiriliyor)...", len(ettn_to_line))
            try:
                from ..services.dogan_connector import DoganEInvoiceConnector
                dogan = DoganEInvoiceConnector(self.env)
                pdf_dict = dogan.get_invoices_batch_pdf(list(ettn_to_line.keys()))
                
                for ettn, line in ettn_to_line.items():
                    pdf_content = pdf_dict.get(ettn)
                    if pdf_content:
                        safe_vendor = re.sub(r'[^\w\s-]', '', line.vendor_name or '').strip().replace(' ', '_')[:30]
                        file_name = f"{line.document_number}_{safe_vendor}.pdf"
                        line.write({
                            'pdf_file': base64.b64encode(pdf_content),
                            'pdf_filename': file_name,
                            'download_status': 'success',
                            'error_message': False,
                        })
                        _logger.info("e-Fatura PDF Doğan API'den indirildi (%s)", line.document_number)
                    else:
                        # Fallback: portal URLs
                        dogan_urls = [
                            f"https://portal.dogandonusum.com/einvoice/view-einvoice/view-pdf-einvoice.xhtml?uuid={ettn}",
                            f"https://portal.dogandonusum.com/fatura/pdf/download?ettn={ettn}",
                            f"https://portal.dogandonusum.com/fatura/pdf/{ettn}",
                            f"https://portal.dogandonusum.com/einvoice/pdf-einvoice/{ettn}",
                        ]
                        for try_url in dogan_urls:
                            pdf_content = self._try_download_pdf(try_url)
                            if pdf_content:
                                safe_vendor = re.sub(r'[^\w\s-]', '', line.vendor_name or '').strip().replace(' ', '_')[:30]
                                file_name = f"{line.document_number}_{safe_vendor}.pdf"
                                line.write({
                                    'pdf_file': base64.b64encode(pdf_content),
                                    'pdf_filename': file_name,
                                    'download_status': 'success',
                                    'error_message': False,
                                })
                                break
                        
                        if not pdf_content:
                            line.write({
                                'download_status': 'error',
                                'error_message': f'Doğan API PDF indiremedi (ETTN: {ettn})'
                            })
            except Exception as e:
                _logger.error("Doğan SOAP API Batch Hatası: %s", str(e))
                for ettn, line in ettn_to_line.items():
                    if line.download_status == 'pending':
                        line.write({
                            'download_status': 'error',
                            'error_message': f'Doğan API hatası: {str(e)}'
                        })

    def action_download_zip(self):
        """
        Zaman sınırlı paket döngüsü (time-capped batching):
        Tek bir HTTP isteğinde max 25 saniyeye kadar kaç paket işlenebilirse işler (örn: 60-80 fatura).
        HTTP zaman aşımı süresine (60s) yaklaşılmadan 25. saniyede durur ve canlı güncellenir.
        OWL JS sayesinde sonraki adımı otomatik devam ettirir (Zero-Click Auto Streaming).
        """
        self.ensure_one()
        selected_lines = self.line_ids.filtered(lambda l: l.selected)
        if not selected_lines:
            raise UserError('Lütfen ZIP arşivine eklenecek en az bir fatura seçiniz.')

        start_time = time.time()
        max_duration = 25.0
        batch_sz = self.batch_size if self.batch_size > 0 else 15

        while True:
            pending_lines = selected_lines.filtered(lambda l: l.download_status == 'pending')
            if not pending_lines:
                break

            if time.time() - start_time >= max_duration:
                _logger.info("HTTP zaman sınırı (25 sn) ulaşıldı. Kalan %d fatura sonraki adıma devrediliyor.", len(pending_lines))
                break

            batch = pending_lines[:batch_sz]
            _logger.info("Batch işleniyor: %d adet (Geçen süre: %.1f sn)", len(batch), time.time() - start_time)
            self._process_batch_lines(batch)

        remaining = selected_lines.filtered(lambda l: l.download_status == 'pending')
        if remaining:
            self.write({'state': 'downloading'})
            _logger.info("İstek tamamlandı. Kalan %d adet fatura var. Ekran yenileniyor.", len(remaining))
        else:
            _logger.info("Tüm faturalar indirildi. ZIP arşivi hazırlanıyor...")
            return self._finalize_zip(selected_lines)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_start_background_download(self):
        """Faturaları indirmeyi arka plan Cron görevine devreder ve kullanıcıya bildirim gösterir."""
        self.ensure_one()
        self.write({'state': 'downloading'})
        
        cron = self.env.ref('ugurlar_invoice_collector.cron_process_invoice_collector_jobs', raise_if_not_found=False)
        if cron:
            cron._trigger()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Arka Planda İndirme Başlatıldı 🚀',
                'message': 'Faturalar arka planda otomatik indirilmeye başlandı. Tamamlandığında tıklanabilir bildirim alacaksınız.',
                'type': 'success',
                'sticky': True,
            }
        }

    @api.model
    def _cron_process_download_jobs(self):
        """
        Arka plan Cron İşleyicisi: 'downloading' durumundaki fatura arşivleme işlerini tarar,
        arka planda indirir, ZIP oluşturur ve işi başlatan kullanıcıya tıklanabilir canlı Bus bildirimi & mesajı gönderir.
        """
        jobs = self.search([('state', '=', 'downloading')], limit=5)
        for job in jobs:
            _logger.info("Cron: Arka plan fatura arşivleme işi işleniyor (Job ID: %d)...", job.id)
            try:
                start_time = time.time()
                while time.time() - start_time < 25.0:
                    pending = job.line_ids.filtered(lambda l: l.selected and l.download_status == 'pending')
                    if not pending:
                        break
                    batch_sz = job.batch_size if job.batch_size > 0 else 15
                    batch = pending[:batch_sz]
                    job._process_batch_lines(batch)
                
                remaining = job.line_ids.filtered(lambda l: l.selected and l.download_status == 'pending')
                if not remaining:
                    job._finalize_zip(job.line_ids.filtered(lambda l: l.selected))
                    _logger.info("Cron: Job ID %d tamamlandı! ZIP oluşturuldu: %s", job.id, job.zip_filename)
                    
                    target_partner = job.create_uid.partner_id
                    if target_partner:
                        try:
                            # 1. Tıklanabilir canlı Bus pop-up bildirimi (Tıklayınca doğrudan bu ZIP formunu açar)
                            self.env['bus.bus']._sendone(
                                target_partner,
                                'simple_notification',
                                {
                                    'title': '🎉 Fatura ZIP Arşivi Hazır!',
                                    'message': f'{job.zip_filename} başarıyla indirildi. Tıklayarak arşivi indirebilirsiniz.',
                                    'type': 'success',
                                    'sticky': True,
                                    'action': {
                                        'type': 'ir.actions.act_window',
                                        'name': job.zip_filename or 'Fatura Arşivi',
                                        'res_model': 'ugurlar.invoice.collector',
                                        'res_id': job.id,
                                        'views': [[False, 'form']],
                                        'target': 'current',
                                    }
                                }
                            )
                            _logger.info("Cron: Bus bildirimi ve yönlendirme linki kullanıcıya iletildi (%s)", job.create_uid.name)
                        except Exception as ne:
                            _logger.warning("Bus bildirim gönderim hatası: %s", str(ne))

                        try:
                            # 2. Odoo Bildirim Kutusu (Zil İkonu / Discuss Inbox) Mesajı
                            target_partner.message_post(
                                body=f"<b>🎉 Fatura ZIP Arşivi Hazır!</b><br/>"
                                     f"<b>Dosya:</b> {job.zip_filename}<br/>"
                                     f"<b>Marka / Ürün Grubu:</b> {job.brand_id.name or 'Tümü'} / {job.product_group_id.name or 'Tümü'}<br/>"
                                     f"<b>İndirilen Fatura Sayısı:</b> {job.processed_count} adet",
                                subject="Fatura ZIP Arşivi Hazırlandı",
                                message_type="notification",
                                subtype_xmlid="mail.mt_comment",
                            )
                        except Exception as me:
                            _logger.debug("Partner message_post hatası: %s", str(me))
            except Exception as e:
                _logger.error("Cron hatası (Job ID %d): %s", job.id, str(e))

    def _finalize_zip(self, selected_lines):
        """Tüm indirilen PDF'leri tek bir ZIP arşivinde birleştirir."""
        in_memory_zip = io.BytesIO()
        success_count = 0

        with zipfile.ZipFile(in_memory_zip, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for line in selected_lines.filtered(lambda l: l.download_status == 'success' and l.pdf_file):
                pdf_data = base64.b64decode(line.pdf_file)
                filename = line.pdf_filename or f"{line.document_number}.pdf"
                zip_file.writestr(filename, pdf_data)
                success_count += 1

        if success_count == 0:
            raise UserError(
                'Seçilen faturaların hiçbirine ait PDF dosyası indirilemedi.\n\n'
                'Lütfen satır detaylarındaki Hata Açıklamalarını kontrol ediniz.'
            )

        brand_name = self.brand_id.name or 'Tumu'
        group_name = self.product_group_id.name or 'Tumu'
        safe_brand = re.sub(r'[^\w]', '', brand_name)
        safe_group = re.sub(r'[^\w]', '', group_name)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        filename = f"{safe_brand}-{safe_group}-{timestamp}.zip"

        in_memory_zip.seek(0)
        zip_base64 = base64.b64encode(in_memory_zip.read())

        self.write({
            'zip_file': zip_base64,
            'zip_filename': filename,
            'state': 'completed',
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_reset(self):
        """Wizard'ı ilk durumuna döndürür."""
        self.ensure_one()
        self.line_ids.unlink()
        self.write({
            'state': 'draft',
            'zip_file': False,
            'zip_filename': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class UgurlarInvoiceCollectorLine(models.TransientModel):
    _name = 'ugurlar.invoice.collector.line'
    _description = 'Fatura Toplama Wizard Satırı'

    wizard_id = fields.Many2one('ugurlar.invoice.collector', ondelete='cascade')
    selected = fields.Boolean(string='Seç', default=True)
    item_code = fields.Char(string='Ürün Kodu')
    document_number = fields.Char(string='Belge Numarası', required=True)
    document_date = fields.Date(string='Belge Tarihi')
    vendor_name = fields.Char(string='Tedarikçi / Cari Adı')
    ref_number = fields.Char(string='Belge Ref No / E-Fatura No')
    invoice_url = fields.Char(string='Fatura URL')
    download_status = fields.Selection([
        ('pending', 'Bekliyor'),
        ('success', 'Başarılı'),
        ('error', 'Hata'),
    ], string='İndirme Durumu', default='pending')
    error_message = fields.Text(string='Hata Detayı')
    
    pdf_file = fields.Binary(string='İndirilen PDF', attachment=True)
    pdf_filename = fields.Char(string='PDF Dosya Adı')
