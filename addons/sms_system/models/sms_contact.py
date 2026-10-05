from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..services.turatel import normalize_number


class SmsSystemList(models.Model):
    """Toplu SMS alıcı listesi (müşteri ya da personel)."""
    _name = 'sms.system.list'
    _description = 'SMS Alıcı Listesi'
    _order = 'name'

    name = fields.Char(string='Liste Adı', required=True)
    list_type = fields.Selection([('customer', 'Müşteri'), ('staff', 'Personel')], string='Tür',
                                 default='customer', required=True)
    contact_ids = fields.Many2many('sms.system.contact', 'sms_system_contact_list_rel', 'list_id', 'contact_id',
                                   string='Kişiler')
    contact_count = fields.Integer(string='Kişi', compute='_compute_contact_count')
    note = fields.Text(string='Not')
    active = fields.Boolean(default=True)

    def _compute_contact_count(self):
        data = dict(self.env['sms.system.contact']._read_group(
            [('list_ids', 'in', self.ids)], ['list_ids'], ['__count']))
        for lst in self:
            lst.contact_count = data.get(lst, 0)

    def action_view_contacts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': self.name, 'res_model': 'sms.system.contact',
            'view_mode': 'list,form', 'domain': [('list_ids', 'in', self.id)],
            'context': {'default_list_ids': [(4, self.id)]},
        }


class SmsSystemContact(models.Model):
    """SMS rehberi: tüm kaynaklardan (Excel, Nebim, terzi, Odoo) gelen numaralar tek yerde, numara başına bir kayıt."""
    _name = 'sms.system.contact'
    _description = 'SMS Rehberi'
    _order = 'name, id'

    name = fields.Char(string='Ad Soyad')
    mobile = fields.Char(string='Cep Telefonu', required=True, index=True,
                         help='5XXXXXXXXX biçiminde saklanır')
    source = fields.Selection([
        ('manual', 'Elle'),
        ('excel', 'Excel/CSV'),
        ('nebim', 'Nebim'),
        ('tailor', 'Terzi'),
        ('odoo', 'Odoo Kişileri'),
    ], string='Kaynak', default='manual', required=True, index=True)
    customer_code = fields.Char(string='Müşteri Kodu', index=True)
    partner_id = fields.Many2one('res.partner', string='Odoo Kişisi', ondelete='set null')
    list_ids = fields.Many2many('sms.system.list', 'sms_system_contact_list_rel', 'contact_id', 'list_id',
                                string='Listeler')
    iys_status = fields.Selection([
        ('unknown', 'Bilinmiyor'),
        ('approved', 'Onaylı'),
        ('rejected', 'Ret'),
    ], string='İYS İzni', default='unknown', required=True, index=True,
        help='Ticari (kampanya) SMS yalnız İYS onaylı numaralara gider')
    iys_checked_at = fields.Datetime(string='İYS Kontrol Tarihi', readonly=True)
    opt_out = fields.Boolean(string='Kara Listede', index=True,
                             help='Kara listedeki numaralara hiçbir toplu SMS gönderilmez')
    opt_out_reason = fields.Char(string='Kara Liste Sebebi')
    opt_out_date = fields.Datetime(string='Kara Liste Tarihi', readonly=True)
    note = fields.Text(string='Not')
    active = fields.Boolean(default=True)

    _unique_mobile = models.Constraint('UNIQUE(mobile)', 'Bu cep telefonu rehberde zaten var!')

    @api.model
    def _prepare_mobile(self, vals):
        if vals.get('mobile'):
            num = normalize_number(vals['mobile'])
            if not num:
                raise ValidationError(_('Geçersiz cep telefonu: %s') % vals['mobile'])
            vals['mobile'] = num
        if vals.get('opt_out') and not vals.get('opt_out_date'):
            vals['opt_out_date'] = fields.Datetime.now()
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._prepare_mobile(dict(v)) for v in vals_list])

    def write(self, vals):
        vals = self._prepare_mobile(dict(vals))
        if 'opt_out' in vals and not vals['opt_out']:
            vals.setdefault('opt_out_date', False)
        return super().write(vals)

    @api.depends('name', 'mobile')
    def _compute_display_name(self):
        for c in self:
            c.display_name = '%s (%s)' % (c.name, c.mobile) if c.name else (c.mobile or '')

    @api.model
    def upsert_numbers(self, rows, source, lists=None):
        """Numara listesini rehbere ekle/güncelle; listelere bağla.

        rows: [{'mobile': ..., 'name': ..., 'customer_code': ..., 'partner_id': ...}]
        Mevcut kişinin adı boşsa doldurulur; kara liste ve İYS durumu asla değiştirilmez.
        Dönen sözlük: created, updated, invalid (ham numaralar), duplicate (dosya içi tekrar).
        """
        result = {'created': 0, 'updated': 0, 'invalid': [], 'duplicate': 0}
        seen = {}
        for row in rows:
            num = normalize_number(str(row.get('mobile') or ''))
            if not num:
                if row.get('mobile'):
                    result['invalid'].append(str(row['mobile']))
                continue
            if num in seen:
                result['duplicate'] += 1
                continue
            seen[num] = row
        if not seen:
            return result
        Contact = self.with_context(active_test=False)
        existing = {c.mobile: c for c in Contact.search([('mobile', 'in', list(seen))])}
        list_cmds = [(4, lst.id) for lst in (lists or [])]
        to_create = []
        for num, row in seen.items():
            contact = existing.get(num)
            if contact:
                vals = {}
                if row.get('name') and not contact.name:
                    vals['name'] = row['name']
                if row.get('customer_code') and not contact.customer_code:
                    vals['customer_code'] = row['customer_code']
                if row.get('partner_id') and not contact.partner_id:
                    vals['partner_id'] = row['partner_id']
                if list_cmds:
                    vals['list_ids'] = list_cmds
                if not contact.active:
                    vals['active'] = True
                if vals:
                    contact.write(vals)
                result['updated'] += 1
            else:
                to_create.append({
                    'mobile': num, 'name': row.get('name') or False, 'source': source,
                    'customer_code': row.get('customer_code') or False,
                    'partner_id': row.get('partner_id') or False, 'list_ids': list_cmds,
                })
        if to_create:
            Contact.create(to_create)
            result['created'] = len(to_create)
        return result

    def action_opt_out(self):
        self.write({'opt_out': True, 'opt_out_reason': self.env.context.get('opt_out_reason') or _('Elle')})

    def action_opt_in(self):
        self.write({'opt_out': False, 'opt_out_reason': False})
