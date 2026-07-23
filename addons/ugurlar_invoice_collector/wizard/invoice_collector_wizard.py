# -*- coding: utf-8 -*-

import base64
import io
import logging
import re
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
    
    state = fields.Selection([
        ('draft', 'Taslak'),
        ('scanned', 'Faturalar Bulundu'),
        ('completed', 'ZIP Oluşturuldu'),
    ], string='Durum', default='draft')

    line_ids = fields.One2many(
        'ugurlar.invoice.collector.line',
        'wizard_id',
        string='Bulunan Faturalar'
    )

    zip_file = fields.Binary(string='ZIP Dosyası', readonly=True)
    zip_filename = fields.Char(string='ZIP Dosya Adı', readonly=True)
    
    total_found_invoices = fields.Integer(string='Bulunan Fatura Sayısı', compute='_compute_totals')
    selected_invoices_count = fields.Integer(string='Seçili Fatura Sayısı', compute='_compute_totals')

    @api.depends('line_ids', 'line_ids.selected')
    def _compute_totals(self):
        for rec in self:
            rec.total_found_invoices = len(rec.line_ids)
            rec.selected_invoices_count = len(rec.line_ids.filtered(lambda l: l.selected))
    @staticmethod
    def _extract_item_code(variant_sku):
        """
        Varyant SKU'sundan ana ürün kodunu (Nebim ItemCode) çıkarır.
        
        Varyant formatı: {ItemCode}-{RenkKodu}-{Beden}
        Örnek: '2W22CT1333PR-0138-M' → '2W22CT1333PR'
                '2SCT1073FX-0065-XL'  → '2SCT1073FX'
                '2SMORGEN3FX'         → '2SMORGEN3FX'  (zaten ana kod)
        """
        # Regex: Son kısımdaki -RenkKodu(3-4 digit)-Beden kalıbını bul ve kaldır
        match = re.match(r'^(.+)-\d{3,4}-.+$', variant_sku)
        if match:
            return match.group(1)
        return variant_sku  # Zaten ana kod formatında

    def action_scan_invoices(self):
        """
        Seçilen Marka ve Ürün Grubu filtrelerine uyan Odoo ürünlerinin
        ItemCode (default_code) listesini alır, Nebim SP'sini çağırarak
        Toptan Alış belgelerini tekleştirilmiş olarak çeker.
        """
        self.ensure_one()
        
        # 1. Filtrelere uygun ürün şablonlarını bul (template üzerinden arama — tek varyantlı ürünleri de yakalar)
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
            # Varyant SKU'larından ana ürün kodunu (ItemCode) çıkar
            # Varyant formatı: {ItemCode}-{RenkKodu}-{Beden}  örn: 2W22CT1333PR-0138-M
            # Nebim SP'ye sadece ana ItemCode (2W22CT1333PR) lazım
            for variant in tmpl.product_variant_ids:
                code = variant.default_code or tmpl.default_code
                if code:
                    main_code = self._extract_item_code(code.strip())
                    item_codes.add(main_code)
            # Template'in kendi default_code'unu da kontrol et
            if not tmpl.product_variant_ids and tmpl.default_code:
                main_code = self._extract_item_code(tmpl.default_code.strip())
                item_codes.add(main_code)
        
        if not item_codes:
            raise UserError(
                f'{len(templates)} adet ürün şablonu bulundu ama hiçbirinin ItemCode (default_code) alanı dolu değil.\n'
                'Lütfen ürünlerin Dahili Referans (default_code) alanlarını kontrol edin.'
            )

        _logger.info("Fatura Tarama: %d adet benzersiz ana ürün kodu (ItemCode) bulundu. Nebim SP çağrılıyor...", len(item_codes))
        
        # İlk birkaç kodu loglayalım (debug)
        sample_codes = list(item_codes)[:5]
        _logger.info("Fatura Tarama - Örnek ItemCode'lar: %s", sample_codes)

        # 2. Nebim SP'yi batch'ler halinde çağır (her batch'te max 20 ItemCode)
        #    Nebim Integrator API uzun parametre string'lerini kırpabilir.
        connector = self.env['odoougurlar.nebim.connector'].sudo()
        all_results = []
        batch_size = 20
        code_list = list(item_codes)
        
        try:
            for i in range(0, len(code_list), batch_size):
                batch = code_list[i:i + batch_size]
                batch_str = ','.join(batch)
                _logger.info("Fatura Tarama - Batch %d/%d: %d kod gönderiliyor...", 
                           (i // batch_size) + 1, 
                           (len(code_list) + batch_size - 1) // batch_size,
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
        
        results = all_results

        # 3. Sonuçları tekleştir ve wizard satırlarına yaz
        existing_lines = [(5, 0, 0)]
        seen_docs = set()

        for row in results:
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

            # Tarih aralığı filtresi varsa kontrol et
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
            }))

        if len(existing_lines) <= 1:
            raise UserError('Belirtilen tarih kriterlerine uyan Toptan Alış faturası bulunamadı.')

        self.write({
            'line_ids': existing_lines,
            'state': 'scanned',
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_download_zip(self):
        """
        Seçili faturaların PDF'lerini Nebim / Doğan E-Dönüşüm servislerinden indirir,
        RAM bellek üzerinde ZIP dosyasına paketler ve indirme bağlantısı sunar.
        """
        self.ensure_one()
        selected_lines = self.line_ids.filtered(lambda l: l.selected)
        if not selected_lines:
            raise UserError('Lütfen ZIP arşivine eklenecek en az bir fatura seçiniz.')

        connector = self.env['odoougurlar.nebim.connector'].sudo()
        in_memory_zip = io.BytesIO()

        success_count = 0
        with zipfile.ZipFile(in_memory_zip, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for line in selected_lines:
                doc_num = line.document_number
                pdf_content = None
                
                # 1. Nebim'den E-Fatura / E-Arşiv URL'ini al
                try:
                    params = [{'Name': 'DocumentNumber', 'Value': doc_num}]
                    res = connector.run_proc('usp_Invoice_EArchieveURL', params)
                    
                    invoice_url = ''
                    if res and isinstance(res, list) and len(res) > 0:
                        invoice_url = res[0].get('InvoiceURL', '') if isinstance(res[0], dict) else ''

                    # 2. PDF içeriğini indir
                    if invoice_url:
                        line.invoice_url = invoice_url
                        # Doğan E-Dönüşüm URL'ini direkt PDF çevirme kontrolü
                        pdf_url = invoice_url
                        if 'view-earchive' in pdf_url:
                            pdf_url = pdf_url.replace('view-earchive', 'pdf-earchive')
                        
                        resp = requests.get(pdf_url, timeout=15)
                        if resp.status_code == 200 and len(resp.content) > 100:
                            pdf_content = resp.content
                except Exception as e:
                    _logger.warning("Fatura PDF indirme uyarısı (%s): %s", doc_num, str(e))

                # 3. Eğer URL'den çekilemediyse fallback varsayılan PDF etiketi oluştur
                if not pdf_content:
                    # Alternatif istek veya boş geçmeme bilgisi
                    line.write({
                        'download_status': 'error',
                        'error_message': 'PDF bağlantısı veya ikili verisi alınamadı.'
                    })
                    continue

                # 4. ZIP içine ekle (Dosya Adı: BelgeNo_FirmaAdi.pdf)
                safe_vendor = re.sub(r'[^\w\s-]', '', line.vendor_name or '').strip().replace(' ', '_')[:30]
                file_name = f"{doc_num}_{safe_vendor}.pdf"
                
                zip_file.writestr(file_name, pdf_content)
                line.write({'download_status': 'success', 'error_message': False})
                success_count += 1

        if success_count == 0:
            raise UserError('Seçilen faturaların hiçbirine ait PDF dosyası indirilemedi. Lütfen bağlantıları kontrol edin.')

        # ZIP Dosya İsmi: Marka-UrunGrubu-YYYYMMDD_HHMMSS.zip
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
        self.write({'state': 'draft', 'zip_file': False, 'zip_filename': False})
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
