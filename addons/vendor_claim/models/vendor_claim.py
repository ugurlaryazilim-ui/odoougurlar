import logging
from datetime import timedelta

from markupsafe import Markup, escape
from psycopg2 import errors as pg_errors

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.sms_system.services.turatel import normalize_number

_logger = logging.getLogger(__name__)

PARAM = 'vendor_claim.'
MIN_TIME_LEFT = 20   # cron süresinin sonuna bu kadar saniye kala dur, kalan sonraki çalışmada
VENDOR_ATTRIBUTE = 'Tedarikçi'
MANUAL_SMS_GUARD_SECONDS = 60   # mobil elle SMS: aynı kayıt + aynı şablon için tekrar engeli

# İzinli durum geçişleri (yönetici her geçişi yapabilir)
ALLOWED_TRANSITIONS = {
    'received': {'sent', 'cancelled'},
    'sent': {'returned', 'received', 'cancelled'},
    'returned': {'delivered', 'sent'},
    'delivered': set(),
    'cancelled': {'received'},
}

# Durum → otomatik SMS (şablon kodu, gönderildi işareti alanı)
STATE_SMS = {
    'received': ('vendor_claim_received', 'sms_received_sent'),
    'sent': ('vendor_claim_sent', 'sms_sent_sent'),
    'returned': ('vendor_claim_returned', 'sms_returned_sent'),
    'delivered': ('vendor_claim_delivered', 'sms_delivered_sent'),
}


class VendorClaim(models.Model):
    """Müşterinin geri getirdiği ürünün tedarikçiye inceleme gönderimi ve dönüş takibi."""
    _name = 'vendor.claim'
    _description = 'Tedarikçi İnceleme Kaydı'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Takip No', required=True, copy=False, readonly=True, default='Yeni', index=True)
    user_id = fields.Many2one('res.users', string='Sorumlu', default=lambda self: self.env.user,
                              tracking=True, index=True)
    company_id = fields.Many2one('res.company', string='Şirket', default=lambda self: self.env.company,
                                 required=True)

    # ── Nebim fatura / müşteri ──
    no_invoice = fields.Boolean(string='Faturasız', tracking=True,
                                help='Nebim faturası bulunmayan ürün (müşteri ve ürün elle girilir)')
    invoice_no = fields.Char(string='Fatura No', index=True, tracking=True)
    invoice_date = fields.Date(string='Fatura Tarihi')
    invoice_items = fields.Json(string='Faturadaki Ürünler', copy=False)
    invoice_items_html = fields.Html(string='Faturadaki Ürünler ', compute='_compute_invoice_items_html',
                                     sanitize=False)
    customer_code = fields.Char(string='Müşteri Kodu', index=True)
    customer_name = fields.Char(string='Müşteri Adı', required=True, tracking=True)
    customer_mobile = fields.Char(string='Müşteri Cep Telefonu', tracking=True)
    sales_person = fields.Char(string='Satış Personeli')
    customer_claim_count = fields.Integer(string='Müşterinin Kayıtları', compute='_compute_customer_claim_count')

    # ── Ürün / tedarikçi ──
    product_barcode = fields.Char(string='Barkod', index=True)
    product_id = fields.Many2one('product.product', string='Ürün', index=True, tracking=True)
    product_code = fields.Char(string='Ürün Kodu')
    product_name = fields.Char(string='Ürün Adı')
    quantity = fields.Float(string='Adet', default=1.0, digits=(10, 2))
    vendor_name = fields.Char(string='Tedarikçi (Nebim)', help='Ürünün Nebim "Tedarikçi" özelliği')
    vendor_id = fields.Many2one('res.partner', string='Tedarikçi', index=True, tracking=True,
                                domain=[('is_company', '=', True)])
    defect_description = fields.Text(string='Ayıp / Şikayet', required=True)
    customer_request = fields.Selection([
        ('repair', 'Tamir'),
        ('replace', 'Değişim'),
        ('refund', 'Para İadesi'),
        ('inspect', 'Sadece İnceleme'),
    ], string='Müşteri Talebi', default='inspect', tracking=True)
    photo_ids = fields.Many2many('ir.attachment', 'vendor_claim_photo_rel', 'claim_id', 'attachment_id',
                                 string='Fotoğraflar', copy=False)

    # ── Kargo ──
    out_carrier = fields.Char(string='Gönderim Kargo Firması', tracking=True)
    out_tracking = fields.Char(string='Gönderim Takip No', tracking=True)
    in_carrier = fields.Char(string='Dönüş Kargo Firması', tracking=True)
    in_tracking = fields.Char(string='Dönüş Takip No', tracking=True)

    # ── Tedarikçi yanıtı / sonuç ──
    result = fields.Selection([
        ('repaired', 'Tamir Edildi'),
        ('replaced', 'Yenisiyle Değiştirildi'),
        ('refund', 'İade Kabul (Para İadesi)'),
        ('rejected', 'Ret (Kullanıcı Hatası)'),
    ], string='Sonuç', tracking=True, copy=False)
    result_note = fields.Text(string='Tedarikçi Açıklaması', copy=False)
    vendor_report_ids = fields.Many2many('ir.attachment', 'vendor_claim_report_rel', 'claim_id', 'attachment_id',
                                         string='Tedarikçi Yanıt Belgeleri', copy=False)
    notes = fields.Text(string='Notlar')

    # ── Durum ──
    state = fields.Selection([
        ('received', 'Teslim Alındı'),
        ('sent', 'Tedarikçide'),
        ('returned', 'İncelemeden Geldi'),
        ('delivered', 'Müşteriye Teslim Edildi'),
        ('cancelled', 'İptal'),
    ], string='Durum', default='received', required=True, tracking=True, index=True, copy=False)
    sent_at = fields.Datetime(string='Tedarikçiye Gönderim', readonly=True, copy=False)
    returned_at = fields.Datetime(string='Tedarikçiden Dönüş', readonly=True, copy=False)
    delivered_at = fields.Datetime(string='Müşteriye Teslim', readonly=True, copy=False)
    cancelled_at = fields.Datetime(string='İptal Tarihi', readonly=True, copy=False)
    vendor_days = fields.Float(string='Tedarikçide Kalış (gün)', digits=(10, 1), compute='_compute_vendor_days',
                               store=True, aggregator='avg', help='Gönderimden dönüşe kadar geçen gün')
    days_at_vendor = fields.Integer(string='Tedarikçide (gün)', compute='_compute_days_at_vendor')
    is_overdue = fields.Boolean(string='Gecikti', compute='_compute_is_overdue', search='_search_is_overdue')
    overdue_notified = fields.Boolean(string='Gecikme Bildirildi', readonly=True, copy=False)

    # ── SMS ──
    sms_received_sent = fields.Boolean(string='Teslim Alındı SMS', readonly=True, copy=False)
    sms_sent_sent = fields.Boolean(string='Gönderildi SMS', readonly=True, copy=False)
    sms_returned_sent = fields.Boolean(string='İncelemeden Geldi SMS', readonly=True, copy=False)
    sms_delivered_sent = fields.Boolean(string='Teslim Edildi SMS', readonly=True, copy=False)
    reminder_count = fields.Integer(string='Hatırlatma SMS Sayısı', readonly=True, copy=False, default=0)
    last_reminder_at = fields.Datetime(string='Son Hatırlatma', readonly=True, copy=False)

    # ─── Hesaplananlar ───────────────────────────────

    @api.depends('invoice_items')
    def _compute_invoice_items_html(self):
        for claim in self:
            items = claim.invoice_items or []
            if not items:
                claim.invoice_items_html = False
                continue
            rows = Markup('').join(
                Markup('<tr><td>%s</td><td>%s</td><td>%s</td><td class="text-end">%s</td></tr>') % (
                    it.get('barcode') or '', it.get('product_code') or '', it.get('product_name') or '',
                    it.get('quantity') or '')
                for it in items)
            claim.invoice_items_html = Markup(
                '<table class="table table-sm o_vendor_claim_items"><thead><tr><th>Barkod</th><th>Ürün Kodu</th>'
                '<th>Ürün</th><th class="text-end">Adet</th></tr></thead><tbody>%s</tbody></table>') % rows

    @api.depends('sent_at', 'returned_at')
    def _compute_vendor_days(self):
        for claim in self:
            if claim.sent_at and claim.returned_at:
                claim.vendor_days = round((claim.returned_at - claim.sent_at).total_seconds() / 86400, 1)
            else:
                claim.vendor_days = 0.0

    @api.depends('sent_at', 'returned_at', 'state')
    def _compute_days_at_vendor(self):
        now = fields.Datetime.now()
        for claim in self:
            if claim.sent_at and claim.state in ('sent', 'returned', 'delivered'):
                end = claim.returned_at or now
                claim.days_at_vendor = max((end - claim.sent_at).days, 0)
            else:
                claim.days_at_vendor = 0

    @api.model
    def _overdue_days(self):
        return max(int(self.env['ir.config_parameter'].sudo().get_param(PARAM + 'overdue_days', '15') or 15), 1)

    @api.depends('sent_at', 'state')
    def _compute_is_overdue(self):
        limit = fields.Datetime.now() - timedelta(days=self._overdue_days())
        for claim in self:
            claim.is_overdue = bool(claim.state == 'sent' and claim.sent_at and claim.sent_at <= limit)

    def _search_is_overdue(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_('Desteklenmeyen arama.'))
        limit = fields.Datetime.now() - timedelta(days=self._overdue_days())
        domain = [('state', '=', 'sent'), ('sent_at', '<=', limit)]
        return domain if (operator == '=') == value else ['!', '&'] + domain

    def _customer_domain(self):
        self.ensure_one()
        keys = []
        if self.customer_mobile:
            keys.append(('customer_mobile', '=', self.customer_mobile))
        if self.customer_code:
            keys.append(('customer_code', '=', self.customer_code))
        if not keys:
            return None
        return ['|'] * (len(keys) - 1) + keys

    def _compute_customer_claim_count(self):
        for claim in self:
            domain = claim._customer_domain() if claim.id else None
            claim.customer_claim_count = self.search_count(domain + [('id', '!=', claim.id)]) if domain else 0

    def action_view_customer_claims(self):
        self.ensure_one()
        domain = (self._customer_domain() or [('id', '=', 0)]) + [('id', '!=', self.id)]
        return {
            'type': 'ir.actions.act_window', 'name': _('Müşterinin İnceleme Kayıtları'),
            'res_model': self._name, 'view_mode': 'list,form', 'domain': domain,
        }

    # ─── Nebim fatura / ürün / tedarikçi ─────────────

    @api.model
    def _find_product(self, barcode):
        """Barkod → ürün: barcode, virgülle birleşik nebim_barcode (tam parça), ürün kodu."""
        barcode = (barcode or '').strip()
        if not barcode:
            return self.env['product.product']
        Product = self.env['product.product'].sudo().with_context(active_test=False)
        product = Product.search([('barcode', '=', barcode)], limit=1)
        if not product and 'nebim_barcode' in Product._fields:
            for cand in Product.search([('nebim_barcode', 'ilike', barcode)], limit=50):
                if barcode in [b.strip() for b in (cand.nebim_barcode or '').split(',')]:
                    product = cand
                    break
        if not product:
            product = Product.search([('default_code', '=', barcode)], limit=1)
        return product

    @api.model
    def _product_vendor_name(self, product):
        """Ürünün Nebim 'Tedarikçi' özelliği (varyant oluşturmayan nitelik)."""
        if not product:
            return ''
        lines = product.product_tmpl_id.sudo().attribute_line_ids.filtered(
            lambda l: (l.attribute_id.name or '').strip().casefold() == VENDOR_ATTRIBUTE.casefold())
        return ', '.join(lines.mapped('value_ids.name')).strip()

    @api.model
    def _find_vendor(self, vendor_name):
        vendor_name = (vendor_name or '').strip()
        if not vendor_name:
            return self.env['res.partner']
        Partner = self.env['res.partner'].sudo()
        vendor = Partner.search([('name', '=ilike', vendor_name), ('is_company', '=', True),
                                 ('supplier_rank', '>', 0)], limit=1)
        return vendor or Partner.search([('name', '=ilike', vendor_name), ('is_company', '=', True)], limit=1)

    @api.model
    def _resolve_vendor(self, vendor_name):
        """Tedarikçi adına göre tedarikçi kartı: varsa eşleşir, yoksa oluşturulur."""
        vendor_name = (vendor_name or '').strip()
        if not vendor_name:
            return self.env['res.partner']
        Partner = self.env['res.partner'].sudo()
        vendor = self._find_vendor(vendor_name)
        if not vendor:
            vendor = Partner.create({'name': vendor_name, 'is_company': True, 'supplier_rank': 1})
            _logger.info('Tedarikçi İnceleme: yeni tedarikçi kartı %s (%s)', vendor_name, vendor.id)
        elif not vendor.supplier_rank:
            vendor.supplier_rank = 1
        return vendor

    def _product_vals(self, product, create_vendor=True):
        """Ürün seçilince doldurulacak alanlar (ürün, kod, ad, Nebim tedarikçisi ve kartı).

        Formdaki onchange'te kart oluşturulmaz (vazgeçilen formda boş kart kalmasın); kayıtta oluşur.
        """
        if not product:
            return {}
        vendor_name = self._product_vendor_name(product)
        vals = {
            'product_id': product.id,
            'product_code': product.default_code or self.product_code,
            'product_name': product.display_name,
            'vendor_name': vendor_name,
        }
        if vendor_name:
            if create_vendor:
                vals['vendor_id'] = self._resolve_vendor(vendor_name).id
            else:
                vendor = self._find_vendor(vendor_name)
                if vendor:
                    vals['vendor_id'] = vendor.id
        return vals

    @api.model
    def _normalize_mobile(self, number):
        mobile = normalize_number(number or '')
        return '0' + mobile if mobile else ''

    @api.model
    def _fetch_invoice(self, invoice_no):
        """Nebim faturası (terzi modülünün MSSQL bağlantısı): başlık + ürün satırları."""
        detail = self.env['ugurlar.tailor.mssql.connector'].sudo().get_invoice_detail((invoice_no or '').strip())
        if not detail:
            return None
        items = []
        for it in detail.get('items') or []:
            product = self._find_product(it.get('barcode'))
            items.append({
                'barcode': (it.get('barcode') or '').strip(),
                'product_code': (it.get('product_code') or '').strip(),
                'quantity': float(it.get('quantity') or 0),
                'product_id': product.id or False,
                'product_name': product.display_name if product else '',
            })
        detail['items'] = items
        detail['customer_mobile'] = self._normalize_mobile(detail.get('customer_mobile'))
        if not detail['customer_mobile'] and detail.get('customer_code'):
            detail['customer_mobile'] = self._mobile_from_history(detail['customer_code'], detail.get('customer_name'))
        return detail

    @staticmethod
    def _norm_name(name):
        return ' '.join((name or '').lower().split())

    @api.model
    def _mobile_from_history(self, customer_code, customer_name):
        """Aynı kod VE aynı adla açılmış önceki kayıtlarda tek bir cep numarası varsa onu öner.

        Kasa kodları ortaktır; yalnız kodla eşleşirse başka müşterinin numarası sızar (kişisel veri).
        """
        name = self._norm_name(customer_name)
        if not name:
            return ''
        claims = self.sudo().search([('customer_code', '=', customer_code), ('customer_mobile', '!=', False)],
                                    order='id desc', limit=50)
        numbers = {normalize_number(c.customer_mobile) for c in claims
                   if self._norm_name(c.customer_name) == name} - {None}
        return '0' + numbers.pop() if len(numbers) == 1 else ''

    @api.model
    def _invoice_vals(self, detail, barcode=None, create_vendor=True):
        """Fatura detayından kayıt alanları; barkod verilmişse veya faturada tek ürün varsa ürün de dolar."""
        vals = {
            'invoice_no': detail.get('invoice_no'),
            'invoice_date': (detail.get('invoice_date') or '')[:10] or False,
            'customer_code': detail.get('customer_code') or False,
            'customer_name': detail.get('customer_name') or False,
            'sales_person': detail.get('sales_person') or False,
            'invoice_items': detail.get('items') or [],
        }
        if detail.get('customer_mobile'):
            vals['customer_mobile'] = detail['customer_mobile']
        items = detail.get('items') or []
        item = None
        if barcode:
            item = next((it for it in items if it['barcode'] == barcode), None)
        elif len(items) == 1:
            item = items[0]
        if item:
            vals.update({'product_barcode': item['barcode'], 'product_code': item['product_code'] or False,
                         'quantity': item['quantity'] or 1.0})
            if item.get('product_id'):
                vals.update(self._product_vals(self.env['product.product'].browse(item['product_id']),
                                               create_vendor=create_vendor))
        return vals

    @api.onchange('invoice_no')
    def _onchange_invoice_no(self):
        if not self.invoice_no or self.no_invoice:
            return None
        try:
            detail = self._fetch_invoice(self.invoice_no)
        except UserError as e:
            return {'warning': {'title': _('Nebim'), 'message': str(e)}}
        if not detail:
            self.invoice_items = []
            return {'warning': {'title': _('Fatura bulunamadı'),
                                'message': _('%s numaralı fatura Nebim\'de bulunamadı.') % self.invoice_no}}
        barcode = self.product_barcode if any(
            it['barcode'] == self.product_barcode for it in detail['items']) else None
        self.update(self._invoice_vals(detail, barcode, create_vendor=False))
        if not barcode and len(detail['items']) > 1:
            return {'warning': {'title': _('Ürünü seçin'), 'message': _(
                'Faturada %s ürün var. İncelemeye gönderilecek ürünün barkodunu okutun.') % len(detail['items'])}}
        return None

    @api.onchange('product_barcode')
    def _onchange_product_barcode(self):
        barcode = (self.product_barcode or '').strip()
        if not barcode:
            return None
        warning = None
        item = next((it for it in (self.invoice_items or []) if it.get('barcode') == barcode), None)
        if item:
            self.product_code = item.get('product_code') or self.product_code
            self.quantity = item.get('quantity') or 1.0
        elif self.invoice_items and not self.no_invoice:
            warning = {'title': _('Faturada yok'),
                       'message': _('%s barkodu bu faturada bulunmuyor.') % barcode}
        product = self._find_product(barcode)
        if product:
            self.update(self._product_vals(product, create_vendor=False))
        if warning:
            return {'warning': warning}
        return None

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id and self.product_id != self._origin.product_id:
            vals = self._product_vals(self.product_id, create_vendor=False)
            if not self.product_barcode and self.product_id.barcode:
                vals['product_barcode'] = self.product_id.barcode
            self.update(vals)

    @api.onchange('customer_mobile')
    def _onchange_customer_mobile(self):
        if self.customer_mobile:
            mobile = self._normalize_mobile(self.customer_mobile)
            if mobile:
                self.customer_mobile = mobile
            else:
                return {'warning': {'title': _('Cep telefonu'),
                                    'message': _('Geçerli bir cep telefonu değil; SMS gönderilemez.')}}
        return None

    def action_fetch_invoice(self):
        """Formdaki 'Faturadan Getir' — Nebim'den müşteri / ürün bilgisini yeniden çeker."""
        self.ensure_one()
        if self.no_invoice or not self.invoice_no:
            raise UserError(_('Önce fatura numarasını girin.'))
        detail = self._fetch_invoice(self.invoice_no)
        if not detail:
            raise UserError(_('%s numaralı fatura Nebim\'de bulunamadı.') % self.invoice_no)
        barcode = self.product_barcode if any(
            it['barcode'] == self.product_barcode for it in detail['items']) else None
        vals = self._invoice_vals(detail, barcode)
        if self.customer_mobile:
            vals.pop('customer_mobile', None)
        self.write(vals)
        return True

    # ─── Oluşturma / durum ───────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Yeni') == 'Yeni':
                vals['name'] = self.env['ir.sequence'].next_by_code('vendor.claim') or 'Yeni'
            if vals.get('customer_mobile'):
                vals['customer_mobile'] = self._normalize_mobile(vals['customer_mobile']) or vals['customer_mobile']
            # Mobil / API ile yalnız barkod gelirse ürün ve tedarikçi sunucuda tamamlanır
            if vals.get('product_barcode') and not vals.get('product_id'):
                product = self._find_product(vals['product_barcode'])
                for key, value in self._product_vals(product).items():
                    vals.setdefault(key, value)
            elif vals.get('product_id') and not vals.get('vendor_id'):
                product = self.env['product.product'].browse(vals['product_id'])
                for key, value in self._product_vals(product).items():
                    vals.setdefault(key, value)
            if vals.get('vendor_name') and not vals.get('vendor_id'):
                vals['vendor_id'] = self._resolve_vendor(vals['vendor_name']).id or False
        claims = super().create(vals_list)
        claims._link_attachments()
        if not self.env.context.get('vendor_claim_defer_sms'):   # denetleyici: fotoğraflardan sonra kendisi çağırır
            claims._notify_state_sms()
        return claims

    def _link_attachments(self):
        """Yüklenen fotoğraf / yanıt belgelerini kayda bağla (başka kullanıcılar ve PDF de görebilsin)."""
        for claim in self:
            uid = self.env.user.id
            # Yalnız kullanıcının kendi yüklediği, henüz bir kayda bağlanmamış ekler (başkasının kaydedilmemiş
            # eki, kimliği tahmin edilerek bu kayda çekilemez; çekirdek kural onu yalnız oluşturana gösterir)
            loose = (claim.photo_ids | claim.vendor_report_ids).sudo().filtered(
                lambda a: a.create_uid.id == uid
                and (not a.res_model or (a.res_model == claim._name and not a.res_id)))
            if loose:
                loose.write({'res_model': claim._name, 'res_id': claim.id})

    def _is_claim_manager(self):
        return self.env.su or self.env.user.has_group('vendor_claim.group_vendor_claim_manager')

    def _check_transition(self, new_state):
        # vendor_claim_strict: mobil/toplu uçlarda yönetici/sudo muafiyeti yok
        if not self.env.context.get('vendor_claim_strict') and self._is_claim_manager():
            return
        labels = dict(self._fields['state'].selection)
        for claim in self:
            if new_state not in ALLOWED_TRANSITIONS.get(claim.state, set()):
                raise UserError(_('%(claim)s: "%(old)s" durumundan "%(new)s" durumuna geçilemez.') % {
                    'claim': claim.name, 'old': labels.get(claim.state, claim.state),
                    'new': labels.get(new_state, new_state)})

    def write(self, vals):
        # Durum yalnız action_* metodları üzerinden değişir (geçiş kontrolü orada)
        if 'state' in vals and not self.env.context.get('vendor_claim_state_ok'):
            self._check_transition(vals['state'])
        res = super().write(vals)
        if 'photo_ids' in vals or 'vendor_report_ids' in vals:
            self._link_attachments()
        return res

    def _set_state(self, new_state, extra=None):
        """Durumu değiştirir ve durum SMS'ini kuyruğa alır; yeni kuyruğa alınanların {claim_id: {'state',
        'error'}} sonucunu döner."""
        self._check_transition(new_state)
        self.with_context(vendor_claim_state_ok=True).write(dict(extra or {}, state=new_state))
        return self._notify_state_sms(only_new=True)

    # Düğme metotları (action_*) None döner: web istemcisi dönüş değerini eylem sanır. Denetleyici SMS sonucunu
    # almak için aynı işi yapan _<ad> karşılıklarını çağırır.
    def _send_to_vendor(self):
        for claim in self:
            if not claim.vendor_id and claim.vendor_name:
                claim.vendor_id = self._resolve_vendor(claim.vendor_name)
            if not claim.vendor_id:
                raise UserError(_('%s: önce tedarikçiyi seçin.') % claim.name)
        sms = self._set_state('sent', {'sent_at': fields.Datetime.now(), 'returned_at': False,
                                       'overdue_notified': False, 'reminder_count': 0, 'last_reminder_at': False})
        self.activity_unlink(['mail.mail_activity_data_todo'])
        return sms

    def _mark_returned(self):
        for claim in self:
            if not claim.result:
                raise UserError(_('%s: tedarikçiden gelen sonucu (Tamir / Değişim / İade / Ret) seçin.') % claim.name)
        sms = self._set_state('returned', {'returned_at': fields.Datetime.now()})
        self.activity_unlink(['mail.mail_activity_data_todo'])
        return sms

    def _mark_delivered(self):
        return self._set_state('delivered', {'delivered_at': fields.Datetime.now()})

    def _cancel(self):
        sms = self._set_state('cancelled', {'cancelled_at': fields.Datetime.now()})
        self.activity_unlink(['mail.mail_activity_data_todo'])
        return sms

    def action_send_to_vendor(self):
        self._send_to_vendor()

    def action_mark_returned(self):
        self._mark_returned()

    def action_mark_delivered(self):
        self._mark_delivered()

    def action_cancel(self):
        self._cancel()

    def action_reset_to_received(self):
        self._set_state('received', {'sent_at': False, 'returned_at': False, 'delivered_at': False,
                                     'cancelled_at': False, 'overdue_notified': False})

    def action_print_vendor_form(self):
        return self.env.ref('vendor_claim.action_report_vendor_claim_form').report_action(self)

    def _slip_groups(self):
        """Müşteri fişi için kayıtları müşteri bazında grupla (her grup tek fiş).

        Aynı müşteri (ad + cep/kod), aynı fatura ve aynı şirket tek fiş olur; çoklu ürün kaydı (mobil) ya da
        arka uçtan çoklu seçim böylece müşteriye tek kâğıt verir, farklı müşteriler ayrı fişe düşer.
        Sıra: ilk kaydın id'sine göre."""
        groups = {}
        for claim in self.sorted('id'):
            key = (claim.company_id.id, self._norm_name(claim.customer_name),
                   claim.customer_mobile or claim.customer_code or '', claim.invoice_no or '')
            groups[key] = groups.get(key, self.browse()) | claim
        return list(groups.values())

    def action_print_customer_slip(self):
        return self.env.ref('vendor_claim.action_report_vendor_claim_slip').report_action(self)

    # ─── SMS (sms_system / Turatel) ──────────────────

    def _sms_values(self):
        """Yer tutucular: {musteri} {takip} {urun} {tedarikci} {sonuc} {magaza}.

        Birden fazla kayıt (aynı müşteriye tek SMS): {takip} tüm takip no'ları ", " ile birleştirir; {urun} kısa
        kalsın diye "N ürün" olur (SMS uzamasın); {tedarikci} hepsi aynıysa o ad, farklıysa boş (ilkini yazmak
        diğerleri için yanlış bilgi olur); {sonuc} boş (kayıtların sonucu farklı olabilir)."""
        if not self:
            raise ValueError('Kayıt yok')
        first = self[0]
        if len(self) == 1:
            return {
                'musteri': first.customer_name or '',
                'takip': first.name or '',
                'urun': first.product_name or first.product_code or '',
                'tedarikci': first.vendor_id.name or first.vendor_name or '',
                'sonuc': dict(first._fields['result'].selection).get(first.result, '') if first.result else '',
                'magaza': first.company_id.name or first.env.company.name or '',
            }
        vendors = {c.vendor_id.name or c.vendor_name or '' for c in self}
        return {
            'musteri': first.customer_name or '',
            'takip': ', '.join(self.mapped('name')),
            'urun': _('%s ürün') % len(self),
            'tedarikci': vendors.pop() if len(vendors) == 1 else '',
            'sonuc': '',
            'magaza': first.company_id.name or first.env.company.name or '',
        }

    def _send_template_sms(self, code, number=None, queue=False, values=None):
        """Şablonla SMS gönder; sms.system.message kaydını döndür (numara/şablon yoksa None).

        queue=True: sağlayıcı çağrılmaz, kayıt sms_system tekli kuyruğuna alınır.
        values: yer tutucu değerleri (çok kayıtlı tek SMS'te `grup._sms_values()`); SMS kaydı bu kayda bağlanır."""
        self.ensure_one()
        number = number or self.customer_mobile
        template = self.env['sms.system.template'].sudo().get_by_code(code)
        if not number or not template:
            return None
        return self.env['sms.system.message'].send_sms(
            number, template=template, values=values if values is not None else self._sms_values(),
            record=self, queue=queue)

    def _lock_for_manual_sms(self):
        """Mobil elle SMS için satırı transaction sonuna kadar kilitler (NOWAIT); alınamazsa False.

        İki cihaz/çift dokunuş aynı anda gelirse ikincisi beklemeden reddedilir. Odoo imleçleri REPEATABLE READ'dir:
        anlık görüntü isteğin ilk sorgusunda (oturum/kullanıcı okuması) alınır, yani kilitten önce. Yalnız
        FOR UPDATE alan istek satırın yeni sürümünü üretmediği için, görüntüden sonra commit eden diğer istek
        (60 sn / günlük sınır sorgusunda görünmeyen SMS kaydı) serileştirme hatası vermez ve ikinci SMS çıkardı.
        Bu yüzden kilitle birlikte satır güncellenir (yeni sürüm): görüntüden sonra commit eden yarışçı varsa
        FOR UPDATE SerializationFailure verir ve istek reddedilir; yoksa görüntü kilitten önce alınmış olsa da
        tüm önceki SMS kayıtları görünür. LockNotAvailable ve SerializationFailure Odoo'nun yeniden deneme
        listesindedir: savepoint içinde yakalanmazsa istek yeniden çalışır (ikinci SMS riski)."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute('SELECT id FROM vendor_claim WHERE id = %s FOR UPDATE NOWAIT', [self.id])
                self.env.cr.execute('UPDATE vendor_claim SET write_date = write_date WHERE id = %s', [self.id])
        except (pg_errors.LockNotAvailable, pg_errors.SerializationFailure):
            return False
        return True

    def _recent_template_sms(self, code, seconds=MANUAL_SMS_GUARD_SECONDS):
        """Bu kayıt için son `seconds` sn içinde aynı şablonla alınmış (hata olmayan) SMS kaydı var mı (K4).

        Belirsiz (uncertain) kayıt da sayılır: sağlayıcı isteği işlemiş olabilir."""
        self.ensure_one()
        since = fields.Datetime.now() - timedelta(seconds=seconds)
        return bool(self.env['sms.system.message'].sudo().search_count([
            ('res_model', '=', self._name), ('res_id', '=', self.id), ('template_id.code', '=', code),
            ('state', 'in', ('queued', 'sending', 'sent', 'uncertain', 'test')), ('create_date', '>=', since)]))

    def _notify_state_sms(self, only_new=False, group=False):
        """Durumun otomatik SMS'i: ayar açıksa, numara varsa, o durum için daha önce kuyruğa alınmadıysa.

        SMS istek içinde gönderilmez, sms_system tekli kuyruğuna alınır (KK-B11). Döner: {claim_id: {'state',
        'error'}}; state queued | test | error | none. Geçişin SMS'i daha önce alınmışsa son kaydın durumu
        bildirilir; only_new=True ise yalnız bu çağrıda yeni denenenler bildirilir, diğerleri 'none' olur
        (denetleyici yanıtı). Sonuç dönüş değeriyle taşınır, bağlamla değil.

        group=True: aynı durumda ve aynı numaralı kayıtlar için TEK SMS gider (çoklu ürün kaydı); SMS ilk kayda
        bağlanır, gönderildi bayrağı gruptaki tüm kayıtlarda işaretlenir (sonradan tekrar SMS gitmesin) ve
        grubun her kaydı aynı sonucu alır."""
        icp = self.env['ir.config_parameter'].sudo()
        result = {}
        buckets = {}   # (durum, numara) → gönderilecek kayıtlar; group=False ise kayıt başına ayrı
        for claim in self:
            res = {'state': 'none', 'error': ''}
            result[claim.id] = res
            spec = STATE_SMS.get(claim.state)
            if not spec or not claim.customer_mobile:
                continue
            code, flag = spec
            if icp.get_param(PARAM + 'sms_%s_enabled' % claim.state) != 'True':
                continue
            if claim[flag]:
                # Bu geçişin SMS'i zaten alındı: tekrar kuyruğa alınmaz, son kaydın durumu bildirilir
                last = None if only_new else self.env['sms.system.message'].sudo().search(
                    [('res_model', '=', claim._name), ('res_id', '=', claim.id), ('template_id.code', '=', code)],
                    order='id desc', limit=1)
                if last:
                    res.update(state=last.state, error=last.error or '')
                continue
            key = (claim.state, claim.customer_mobile) if group else claim.id
            buckets[key] = buckets.get(key, self.browse()) | claim
        for claims in buckets.values():
            lead = claims[0]
            code, flag = STATE_SMS[lead.state]
            res = result[lead.id]
            try:
                msg = lead._send_template_sms(
                    code, queue=True, values=claims._sms_values() if len(claims) > 1 else None)
            except UserError as e:  # geçersiz numara vb. durum değişikliğini engellemesin
                for claim in claims:
                    claim.message_post(body=_('SMS gönderilemedi: %s') % e)
                res.update(state='error', error=str(e))
            else:
                if msg:
                    res.update(state=msg.state, error=msg.error or '')
                    if msg.state in ('queued', 'test'):
                        claims.sudo().write({flag: True})
                        for claim in claims[1:]:
                            claim.message_post(body=_('Durum SMS bildirimi %s ile birlikte tek mesaj olarak gönderildi.')
                                               % lead.name)
            for claim in claims[1:]:
                result[claim.id] = dict(res)
        return result

    def action_send_sms(self):
        """Formdaki 'SMS Gönder' — şablon seçilebilen pencere."""
        self.ensure_one()
        spec = STATE_SMS.get(self.state)
        return {
            'type': 'ir.actions.act_window',
            'name': _('SMS Gönder'),
            'res_model': 'sms.system.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_number': self.customer_mobile or '',
                'default_res_model': self._name,
                'default_res_id': self.id,
                'default_template_code': spec[0] if spec else False,
                'sms_values': self._sms_values(),
            },
        }

    # ─── Cron'lar ────────────────────────────────────

    @api.model
    def _cron_return_reminders(self):
        """İncelemeden gelip X gündür teslim alınmamış kayıtlara hatırlatma SMS'i (en çok N kez)."""
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param(PARAM + 'sms_reminder_enabled') != 'True':
            return
        days = max(int(icp.get_param(PARAM + 'sms_reminder_days', '3') or 3), 1)
        max_count = int(icp.get_param(PARAM + 'sms_reminder_max', '2') or 2)
        limit = fields.Datetime.now() - timedelta(days=days)
        claims = self.search([
            ('state', '=', 'returned'), ('customer_mobile', '!=', False),
            ('reminder_count', '<', max_count), ('returned_at', '<=', limit),
            '|', ('last_reminder_at', '=', False), ('last_reminder_at', '<=', limit),
        ], limit=200)
        IrCron = self.env['ir.cron']
        for claim in claims:
            try:
                claim._send_template_sms('vendor_claim_reminder', queue=True)
            except UserError as e:
                claim.message_post(body=_('Hatırlatma SMS gönderilemedi: %s') % e)
            # Numara geçersiz / şablon yoksa da sayaç artar: her gün yeniden denenmesin
            claim.write({'reminder_count': claim.reminder_count + 1, 'last_reminder_at': fields.Datetime.now()})
            # Kayıt başına commit: cron kesilse de işlenen kayıtlar kalıcı olur, aynı müşteriye tekrar gitmez
            if IrCron._commit_progress(1) < MIN_TIME_LEFT:
                break

    @api.model
    def _cron_overdue_alerts(self):
        """Tedarikçide X günü geçen kayıtlar için sorumluya tek seferlik aktivite."""
        days = self._overdue_days()
        claims = self.search([('is_overdue', '=', True), ('overdue_notified', '=', False)], limit=500)
        for claim in claims:
            user = claim.user_id or claim.create_uid
            if user and user.active and not user.share:
                claim.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=user.id,
                    summary=_('Tedarikçide %s günü geçti') % days,
                    note=Markup(_('%(name)s — %(vendor)s tedarikçisine %(date)s tarihinde gönderildi, '
                                  'henüz dönmedi. Tedarikçiyi arayın.')) % {
                        'name': escape(claim.name), 'vendor': escape(claim.vendor_id.name or claim.vendor_name or '-'),
                        'date': fields.Datetime.context_timestamp(claim, claim.sent_at).strftime('%d.%m.%Y')})
            claim.overdue_notified = True
