import base64
import logging

from odoo import _, fields, http
from odoo.exceptions import AccessDenied, AccessError, UserError
from odoo.http import request
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

OPEN_STATES = ('received', 'sent', 'returned')
MAX_PHOTOS = 8
MAX_PHOTO_BYTES = 6 * 1024 * 1024


def _local_dt(record, value, fmt='%d.%m.%Y %H:%M'):
    """UTC datetime'ı kullanıcının saat dilimine çevirip biçimle."""
    if not value:
        return ''
    return fields.Datetime.context_timestamp(record, fields.Datetime.to_datetime(value)).strftime(fmt)


class VendorClaimController(http.Controller):
    """Tedarikçi İnceleme mobil ekranı için JSON API."""

    # ─── Ortak ───────────────────────────────────────

    @staticmethod
    def _check_user():
        if not request.env.user._is_internal():
            raise AccessDenied()

    @staticmethod
    def _claims():
        return request.env['vendor.claim']

    def _get_claim(self, claim_id):
        try:
            claim = self._claims().browse(int(claim_id)).exists()
        except (TypeError, ValueError):
            claim = None
        if not claim:
            raise UserError(_('Kayıt bulunamadı.'))
        return claim

    @staticmethod
    def _error(e):
        if isinstance(e, (UserError, AccessError)):
            return {'error': str(e.args[0] if e.args else e)}
        _logger.exception('Tedarikçi İnceleme mobil hata')
        return {'error': _('İşlem yapılamadı. Lütfen tekrar deneyin veya sistem yöneticisine bildirin.')}

    @staticmethod
    def _label(claim, field):
        return dict(claim._fields[field].selection).get(claim[field], '') if claim[field] else ''

    def _summary(self, claim):
        return {
            'id': claim.id,
            'name': claim.name,
            'state': claim.state,
            'state_label': self._label(claim, 'state'),
            'customer_name': claim.customer_name or '',
            'customer_mobile': claim.customer_mobile or '',
            'invoice_no': claim.invoice_no or '',
            'product_name': claim.product_name or claim.product_code or '',
            'product_barcode': claim.product_barcode or '',
            'vendor': claim.vendor_id.name or claim.vendor_name or '',
            'days_at_vendor': claim.days_at_vendor,
            'is_overdue': claim.is_overdue,
            'result': claim.result or '',
            'result_label': self._label(claim, 'result'),
            'date': _local_dt(claim, claim.create_date, '%d.%m.%Y'),
        }

    def _detail(self, claim):
        data = self._summary(claim)
        messages = claim.message_ids.filtered(lambda m: m.message_type == 'comment' and m.body)[:15]
        data.update({
            'invoice_date': claim.invoice_date.strftime('%d.%m.%Y') if claim.invoice_date else '',
            'customer_code': claim.customer_code or '',
            'sales_person': claim.sales_person or '',
            'product_code': claim.product_code or '',
            'quantity': claim.quantity,
            'defect_description': claim.defect_description or '',
            'customer_request_label': self._label(claim, 'customer_request'),
            'out_carrier': claim.out_carrier or '',
            'out_tracking': claim.out_tracking or '',
            'in_carrier': claim.in_carrier or '',
            'in_tracking': claim.in_tracking or '',
            'result_note': claim.result_note or '',
            'notes': claim.notes or '',
            'sent_at': _local_dt(claim, claim.sent_at),
            'returned_at': _local_dt(claim, claim.returned_at),
            'delivered_at': _local_dt(claim, claim.delivered_at),
            'photo_ids': claim.photo_ids.filtered(lambda a: (a.mimetype or '').startswith('image/')).ids,
            'notes_log': [{
                'author': m.author_id.name or '',
                'date': _local_dt(claim, m.date),
                'body': html2plaintext(m.body or ''),
            } for m in messages],
        })
        return data

    def _attach_photos(self, claim, photos):
        """Mobilden gelen data URL fotoğrafları kayda ekle."""
        attachments = request.env['ir.attachment']
        for idx, photo in enumerate((photos or [])[:MAX_PHOTOS]):
            if not isinstance(photo, str) or ',' not in photo:
                continue
            header, data = photo.split(',', 1)
            if not header.startswith('data:image/'):
                continue
            raw = base64.b64decode(data)
            if len(raw) > MAX_PHOTO_BYTES:
                continue
            attachments |= attachments.create({
                'name': '%s-%s.jpg' % (claim.name, len(claim.photo_ids) + idx + 1),
                'datas': data,
                'res_model': claim._name,
                'res_id': claim.id,
                'mimetype': header[5:].split(';', 1)[0],
            })
        if attachments:
            claim.write({'photo_ids': [(4, a.id) for a in attachments]})
        return attachments

    # ─── Ana menü ────────────────────────────────────

    @http.route('/vendor_claim/stats', type='jsonrpc', auth='user')
    def stats(self, **kw):
        self._check_user()
        Claim = self._claims()
        counts = dict(Claim._read_group([('state', 'in', OPEN_STATES)], ['state'], ['__count']))
        return {
            'received': counts.get('received', 0),
            'sent': counts.get('sent', 0),
            'returned': counts.get('returned', 0),
            'overdue': Claim.search_count([('is_overdue', '=', True)]),
        }

    # ─── Fatura / ürün ───────────────────────────────

    @http.route('/vendor_claim/search_invoice', type='jsonrpc', auth='user')
    def search_invoice(self, search_term='', **kw):
        self._check_user()
        try:
            return {'invoices': request.env['ugurlar.tailor.mssql.connector'].sudo().search_invoices(search_term)}
        except Exception as e:
            return self._error(e)

    @http.route('/vendor_claim/invoice_detail', type='jsonrpc', auth='user')
    def invoice_detail(self, invoice_no='', **kw):
        self._check_user()
        Claim = self._claims()
        try:
            detail = Claim._fetch_invoice(invoice_no)
        except Exception as e:
            return self._error(e)
        if not detail:
            return {'error': _('Fatura bulunamadı.')}
        Product = request.env['product.product']
        for item in detail['items']:
            item['vendor'] = Claim._product_vendor_name(Product.browse(item['product_id'])) if item['product_id'] else ''
        existing = Claim.search([('invoice_no', '=', detail['invoice_no'])], limit=10)
        detail['existing'] = [self._summary(c) for c in existing]
        return detail

    @http.route('/vendor_claim/product_lookup', type='jsonrpc', auth='user')
    def product_lookup(self, barcode='', **kw):
        self._check_user()
        Claim = self._claims()
        product = Claim._find_product(barcode)
        if not product:
            return {'error': _('%s barkodlu ürün bulunamadı.') % (barcode or '')}
        return {
            'product_id': product.id,
            'barcode': (barcode or '').strip(),
            'product_code': product.default_code or '',
            'product_name': product.display_name,
            'vendor': Claim._product_vendor_name(product),
        }

    # ─── Kayıt oluşturma ─────────────────────────────

    @http.route('/vendor_claim/create', type='jsonrpc', auth='user')
    def create_claim(self, data=None, photos=None, **kw):
        self._check_user()
        data = data or {}
        if not (data.get('defect_description') or '').strip():
            return {'error': _('Ayıp / şikayet açıklaması zorunlu.')}
        if not (data.get('customer_name') or '').strip():
            return {'error': _('Müşteri adı zorunlu.')}
        if not (data.get('product_barcode') or '').strip():
            return {'error': _('Ürün barkodu zorunlu.')}
        try:
            quantity = float(data.get('quantity') or 1)
        except (TypeError, ValueError):
            quantity = 1.0
        vals = {
            'no_invoice': bool(data.get('no_invoice')),
            'invoice_no': False if data.get('no_invoice') else (data.get('invoice_no') or False),
            'invoice_date': False if data.get('no_invoice') else ((data.get('invoice_date') or '')[:10] or False),
            'customer_code': data.get('customer_code') or False,
            'customer_name': data['customer_name'].strip(),
            'customer_mobile': (data.get('customer_mobile') or '').strip() or False,
            'sales_person': data.get('sales_person') or False,
            'product_barcode': data['product_barcode'].strip(),
            'product_code': data.get('product_code') or False,
            'quantity': max(quantity, 1.0),
            'defect_description': data['defect_description'].strip(),
            'notes': (data.get('notes') or '').strip() or False,
        }
        if data.get('customer_request') in dict(self._claims()._fields['customer_request'].selection):
            vals['customer_request'] = data['customer_request']
        if data.get('invoice_items') and not vals['no_invoice']:
            vals['invoice_items'] = data['invoice_items']
        try:
            with request.env.cr.savepoint():
                claim = self._claims().create(vals)
                self._attach_photos(claim, photos)
        except Exception as e:
            return self._error(e)
        return {'id': claim.id, 'name': claim.name, 'vendor': claim.vendor_id.name or '',
                'slip_url': '/report/pdf/vendor_claim.report_vendor_claim_slip/%s' % claim.id}

    # ─── Liste / detay ───────────────────────────────

    @http.route('/vendor_claim/list', type='jsonrpc', auth='user')
    def list_claims(self, search='', status='', offset=0, **kw):
        self._check_user()
        domain = []
        if status == 'overdue':
            domain.append(('is_overdue', '=', True))
        elif status == 'open':
            domain.append(('state', 'in', OPEN_STATES))
        elif status in ('received', 'sent', 'returned', 'delivered', 'cancelled'):
            domain.append(('state', '=', status))
        search = (search or '').strip()
        if search:
            domain += ['|', '|', '|', '|', '|',
                       ('name', 'ilike', search), ('customer_name', 'ilike', search),
                       ('customer_mobile', 'ilike', search), ('product_barcode', '=', search),
                       ('invoice_no', 'ilike', search), ('vendor_id.name', 'ilike', search)]
        Claim = self._claims()
        try:
            offset = max(int(offset or 0), 0)
        except (TypeError, ValueError):
            offset = 0
        claims = Claim.search(domain, limit=50, offset=offset)
        return {'items': [self._summary(c) for c in claims], 'total': Claim.search_count(domain)}

    @http.route('/vendor_claim/detail', type='jsonrpc', auth='user')
    def detail(self, claim_id=None, **kw):
        self._check_user()
        try:
            return self._detail(self._get_claim(claim_id))
        except Exception as e:
            return self._error(e)

    @http.route('/vendor_claim/find', type='jsonrpc', auth='user')
    def find(self, code='', **kw):
        """Toplu işlem: takip no (INC-...) ya da açık kayıtlardaki ürün barkodu."""
        self._check_user()
        code = (code or '').strip()
        if not code:
            return {'error': _('Kod boş.')}
        Claim = self._claims()
        claim = Claim.search([('name', '=ilike', code)], limit=1)
        if not claim:
            claims = Claim.search([('product_barcode', '=', code), ('state', 'in', OPEN_STATES)], limit=2)
            if len(claims) > 1:
                return {'error': _('%s barkodlu birden fazla açık kayıt var; takip numarasını okutun.') % code}
            claim = claims
        if not claim:
            return {'error': _('%s için kayıt bulunamadı.') % code}
        return self._summary(claim)

    # ─── İşlemler ────────────────────────────────────

    def _apply_action(self, claim, action, vals):
        vals = vals or {}
        claim = claim.with_context(vendor_claim_strict=True)
        if action == 'send':
            claim.write({k: (vals.get(k) or '').strip() or claim[k] for k in ('out_carrier', 'out_tracking')
                         if k in vals})
            claim.action_send_to_vendor()
        elif action == 'return':
            write = {k: (vals.get(k) or '').strip() for k in ('in_carrier', 'in_tracking', 'result_note')
                     if (vals.get(k) or '').strip()}
            if vals.get('result'):
                if vals['result'] not in dict(claim._fields['result'].selection):
                    raise UserError(_('Geçersiz sonuç.'))
                write['result'] = vals['result']
            if write:
                claim.write(write)
            claim.action_mark_returned()
        elif action == 'deliver':
            claim.action_mark_delivered()
        elif action == 'cancel':
            claim.action_cancel()
        elif action == 'note':
            body = (vals.get('note') or '').strip()
            if not body:
                raise UserError(_('Not boş olamaz.'))
            claim.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_note')
        elif action == 'photo':
            if not self._attach_photos(claim, vals.get('photos')):
                raise UserError(_('Fotoğraf eklenemedi.'))
        elif action == 'mobile':
            mobile = claim._normalize_mobile(vals.get('customer_mobile'))
            if not mobile:
                raise UserError(_('Geçerli bir cep telefonu girin.'))
            claim.customer_mobile = mobile
        else:
            raise UserError(_('Bilinmeyen işlem.'))

    @http.route('/vendor_claim/action', type='jsonrpc', auth='user')
    def action(self, claim_id=None, action='', vals=None, **kw):
        self._check_user()
        try:
            claim = self._get_claim(claim_id)
            with request.env.cr.savepoint():
                self._apply_action(claim, action, vals)
            return self._detail(claim)
        except Exception as e:
            return self._error(e)

    @http.route('/vendor_claim/bulk', type='jsonrpc', auth='user')
    def bulk(self, claim_ids=None, action='', vals=None, **kw):
        """Okutulan kayıtları tek işlemle ilerlet; her kayıt ayrı (biri hata verirse diğerleri etkilenmez)."""
        self._check_user()
        if action not in ('send', 'return', 'deliver'):
            return {'error': _('Bilinmeyen işlem.')}
        results = []
        for claim_id in (claim_ids or [])[:200]:
            try:
                claim = self._get_claim(claim_id)
                with request.env.cr.savepoint():
                    self._apply_action(claim, action, vals)
                results.append({'id': claim.id, 'ok': True})
            except Exception as e:
                results.append({'id': claim_id, 'ok': False, 'error': self._error(e)['error']})
        return {'results': results}

    @http.route('/vendor_claim/send_sms', type='jsonrpc', auth='user')
    def send_sms(self, claim_id=None, **kw):
        """Durumun şablonuyla SMS (İncelemeden geldi → hatırlatma metni seçilebilir)."""
        self._check_user()
        try:
            claim = self._get_claim(claim_id)
            code = {'received': 'vendor_claim_received', 'sent': 'vendor_claim_sent',
                    'returned': 'vendor_claim_reminder' if claim.sms_returned_sent else 'vendor_claim_returned',
                    'delivered': 'vendor_claim_delivered'}.get(claim.state)
            if not code:
                return {'error': _('Bu durumda SMS gönderilmez.')}
            if not claim.customer_mobile:
                return {'error': _('Müşterinin cep telefonu yok.')}
            msg = claim._send_template_sms(code)
            if not msg:
                return {'error': _('SMS şablonu bulunamadı.')}
            if msg.state == 'error':
                return {'error': _('SMS gönderilemedi: %s') % (msg.error or '')}
            return {'ok': True, 'message': _('SMS gönderildi: %s') % msg.number}
        except Exception as e:
            return self._error(e)
