import logging
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class MarketplaceQuestion(models.Model):
    _name = 'marketplace.question'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Pazaryeri Müşteri Sorusu'
    _order = 'question_date desc'

    name = fields.Char(string='İsim', compute='_compute_name', store=True)
    marketplace_type = fields.Selection([
        ('trendyol', 'Trendyol'), 
        ('hepsiburada', 'Hepsiburada'), 
        ('pttavm', 'PttAVM'), 
        ('n11', 'N11'), 
        ('pazarama', 'Pazarama'), 
        ('shopify', 'Shopify')
    ], string='Pazaryeri', required=True, tracking=True)
    
    store_id = fields.Many2one('trendyol.store', string='Mağaza')
    external_question_id = fields.Char('Pazaryeri Soru ID', required=True, index=True)
    question_text = fields.Text('Soru', required=True, tracking=True)
    customer_name = fields.Char('Müşteri Adı')
    customer_id_external = fields.Char('Pazaryeri Müşteri ID')
    product_name = fields.Char('Ürün Adı')
    product_image_url = fields.Char('Ürün Resmi URL')
    product_web_url = fields.Char('Ürün Web URL')
    product_barcode = fields.Char('Barkod')
    product_main_id = fields.Char('Model Kodu')
    
    product_tmpl_id = fields.Many2one('product.template', string='Odoo Ürün', compute='_compute_product_tmpl', store=True)
    status = fields.Selection([
        ('waiting', 'Cevaplanmayı Bekliyor'), 
        ('answered', 'Cevaplanmış'), 
        ('rejected', 'Reddedilmiş'), 
        ('reported', 'Raporlanmış'), 
        ('unanswered', 'Cevaplanmamış'), 
        ('expired', 'Süresi Dolmuş')
    ], string='Durum', default='waiting', required=True, tracking=True)
    
    answer_text = fields.Text('Cevap')
    template_id = fields.Many2one('marketplace.question.template', string='Cevap Şablonu')
    answer_char_count = fields.Integer(string='Cevap Karakter Sayısı', compute='_compute_answer_char_count')
    external_answer_id = fields.Char('Pazaryeri Cevap ID')
    answer_date = fields.Datetime('Cevap Tarihi', tracking=True)
    answered_date_message = fields.Char('Cevap Süresi Mesajı')
    
    rejection_reason = fields.Text('Red Sebebi')
    rejected_answer_text = fields.Text('Reddedilen Cevap')
    rejected_answer_date = fields.Datetime('Red Tarihi')
    
    report_reason = fields.Text('Raporlama Sebebi')
    reported_date = fields.Datetime('Raporlama Tarihi')
    
    question_date = fields.Datetime('Soru Tarihi', required=True, index=True)
    is_public = fields.Boolean('Herkese Açık')
    show_user_name = fields.Boolean('Kullanıcı Adı Görünsün')
    
    answer_ids = fields.One2many('marketplace.question.answer', 'question_id', string='Cevap Geçmişi')
    company_id = fields.Many2one('res.company', string='Şirket', default=lambda self: self.env.company)
    color = fields.Integer('Renk')
    priority = fields.Selection([('0', 'Normal'), ('1', 'Düşük'), ('2', 'Orta'), ('3', 'Acil')], string='Öncelik', default='0')
    
    remaining_hours = fields.Float(string='Kalan Saat', compute='_compute_remaining_time', store=True)
    remaining_time_display = fields.Char(string='Kalan Süre', compute='_compute_remaining_time', store=True)
    
    ai_enabled = fields.Boolean('AI Cevap Aktif', default=False)
    ai_suggested_answer = fields.Text('AI Önerilen Cevap')


    
    _unique_question = models.Constraint(
        'UNIQUE(marketplace_type, external_question_id)',
        'Bu soru zaten mevcut!',
    )
    
    _marketplace_status_idx = models.Index('(marketplace_type, status)')
    _question_date_idx = models.Index('(question_date)')

    @api.depends('product_barcode', 'product_main_id')
    def _compute_product_tmpl(self):
        """Barkod veya Model Kodu (default_code) üzerinden Odoo ürünü ile otomatik eşleştirme."""
        for rec in self:
            product = False
            # Önce barkod ile dene
            if rec.product_barcode:
                product = self.env['product.product'].search(
                    [('barcode', '=', rec.product_barcode)], limit=1
                )
            # Barkod yoksa veya bulunamadıysa model kodu (default_code) ile dene
            if not product and rec.product_main_id:
                product = self.env['product.product'].search(
                    [('default_code', '=', rec.product_main_id)], limit=1
                )
            rec.product_tmpl_id = product.product_tmpl_id.id if product else False

    @api.depends('answer_text')
    def _compute_answer_char_count(self):
        for rec in self:
            rec.answer_char_count = len(rec.answer_text or '')

    @api.depends('question_date', 'status')
    def _compute_remaining_time(self):
        """Trendyol 3 iş günü cevap süresi var. Kalan süreyi hesapla."""
        now = fields.Datetime.now()
        for rec in self:
            if rec.status == 'waiting' and rec.question_date:
                # 3 iş günü = ~72 saat (basit hesaplama)
                deadline = rec.question_date + timedelta(hours=72)
                diff = deadline - now
                hours = diff.total_seconds() / 3600
                rec.remaining_hours = max(hours, 0)
                if hours <= 0:
                    rec.remaining_time_display = '⏰ Süre doldu!'
                elif hours < 24:
                    rec.remaining_time_display = f'🔴 {int(hours)} saat kaldı'
                elif hours < 48:
                    rec.remaining_time_display = f'🟡 {int(hours/24)} gün {int(hours%24)} saat'
                else:
                    rec.remaining_time_display = f'🟢 {int(hours/24)} gün {int(hours%24)} saat'
            else:
                rec.remaining_hours = 0
                rec.remaining_time_display = ''

    @api.depends('marketplace_type', 'external_question_id')
    def _compute_name(self):
        for rec in self:
            mp = dict(rec._fields['marketplace_type'].selection).get(rec.marketplace_type, '')
            rec.name = f"{mp} #{rec.external_question_id}" if rec.external_question_id else 'Yeni Soru'

    @api.onchange('template_id')
    def _onchange_template_id(self):
        """Şablon seçildiğinde cevap alanını doldur."""
        if self.template_id:
            self.answer_text = self.template_id.template_text
            # Kullanım sayısını artır
            self.template_id.sudo().use_count += 1

    def action_answer_question(self):
        """Cevabı pazaryerine gönder."""
        self.ensure_one()
        if not self.answer_text:
            raise UserError(_('Lütfen bir cevap yazın!'))
        if len(self.answer_text) < 10:
            raise UserError(_('Cevap en az 10 karakter olmalıdır!'))
        if len(self.answer_text) > 2000:
            raise UserError(_('Cevap en fazla 2000 karakter olabilir!'))
        if self.status != 'waiting':
            raise UserError(_('Sadece "Cevaplanmayı Bekliyor" durumundaki sorular cevaplanabilir!'))
        
        # Marketplace'e göre connector seç ve cevap gönder
        connector = self._get_connector()
        result = connector.send_answer(self)
        
        if result.get('success'):
            # Cevap geçmişine kaydet
            self.env['marketplace.question.answer'].create({
                'question_id': self.id,
                'answer_text': self.answer_text,
                'answer_type': 'sent',
                'external_answer_id': str(result.get('answer_id', '')),
                'sent_by': self.env.user.id,
            })
            self.write({
                'status': 'answered',
                'answer_date': fields.Datetime.now(),
                'external_answer_id': str(result.get('answer_id', '')),
            })
            self.message_post(body=f"✅ Cevap gönderildi: {self.answer_text[:100]}...")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Başarılı',
                    'message': 'Cevap başarıyla gönderildi!',
                    'type': 'success',
                    'sticky': False,
                },
            }
        else:
            error_msg = result.get('error', 'Bilinmeyen hata')
            self.message_post(body=f"❌ Cevap gönderilemedi: {error_msg}")
            raise UserError(_('Cevap gönderilemedi:\n\n%s') % error_msg)

    def action_report_question(self):
        """Soruyu pazaryerine raporla."""
        self.ensure_one()
        self.write({'status': 'reported', 'reported_date': fields.Datetime.now()})
        self.message_post(body="⚠️ Soru raporlandı")

    def action_sync_single_question(self):
        """Tek soruyu pazaryerinden güncelle."""
        self.ensure_one()
        connector = self._get_connector()
        connector.sync_single_question(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Senkronizasyon',
                'message': 'Soru güncellendi!',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_open_product_url(self):
        """Ürün sayfasını tarayıcıda aç."""
        self.ensure_one()
        if not self.product_web_url:
            raise UserError(_('Ürün web URL\'si bulunamadı!'))
        return {
            'type': 'ir.actions.act_url',
            'url': self.product_web_url,
            'target': 'new',
        }

    def _get_connector(self):
        """Marketplace tipine göre connector döndür."""
        self.ensure_one()
        if self.marketplace_type == 'trendyol':
            return self.env['trendyol.question.connector']
        # İlerisi için diğer connector'lar eklenecek
        raise UserError(_('%s için connector henüz mevcut değil!') % self.marketplace_type)

    @api.model
    def _cron_sync_all_questions(self):
        """Tüm pazaryerlerinden soruları çek (Cron job)."""
        _logger.info("═══ Pazaryeri Soru Cron Başlatıldı ═══")
        
        # Trendyol
        TrendyolConnector = self.env['trendyol.question.connector']
        stores = self.env['trendyol.store'].search([
            ('active', '=', True),
            ('question_sync_enabled', '=', True),
        ])
        
        _logger.info("Aktif mağaza sayısı (question_sync_enabled=True): %d", len(stores))
        
        if not stores:
            _logger.warning("Soru sync için aktif mağaza bulunamadı! "
                          "Trendyol mağaza ayarlarından 'Soru Senkronizasyonu' tikini kontrol edin.")
            return
        
        total_results = {'created': 0, 'updated': 0, 'errors': 0}
        for store in stores:
            _logger.info("Mağaza sync başlıyor: %s (seller_id: %s)", store.name, store.seller_id)
            try:
                result = TrendyolConnector.sync_questions_for_store(store)
                total_results['created'] += result.get('created', 0)
                total_results['updated'] += result.get('updated', 0)
                _logger.info("Mağaza sync tamamlandı: %s | Yeni: %d | Güncellenen: %d",
                           store.name, result.get('created', 0), result.get('updated', 0))
            except Exception as e:
                total_results['errors'] += 1
                _logger.error("Trendyol soru sync hatası (mağaza: %s): %s", store.name, e, exc_info=True)
        
        # Kalan süreleri güncelle
        self._cron_update_remaining_time()
        
        _logger.info("═══ Pazaryeri Soru Cron Tamamlandı | Yeni: %d | Güncellenen: %d | Hata: %d ═══",
                     total_results['created'], total_results['updated'], total_results['errors'])

    @api.model
    def _cron_update_remaining_time(self):
        """Bekleyen soruların kalan sürelerini yeniden hesapla."""
        waiting = self.search([('status', '=', 'waiting')])
        if waiting:
            waiting._compute_remaining_time()

    def action_generate_ai_answer(self):
        """AI ile cevap önerisi oluştur."""
        self.ensure_one()
        # Placeholder - AI integration will use Gemini API
        # For now, just create a basic suggestion from product info
        if not self.question_text:
            raise UserError(_('Soru metni bulunamadı!'))
        self.message_post(body="🤖 AI cevap önerisi istendi")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'AI Cevap',
                'message': 'AI cevap önerisi özelliği yakında aktif olacak!',
                'type': 'info',
                'sticky': False,
            },
        }
