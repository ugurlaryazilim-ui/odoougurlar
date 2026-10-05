import base64
import csv
import io
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.turatel import normalize_number

PHONE_HEADERS = ('cep', 'gsm', 'tel', 'phone', 'mobile', 'numara')
NAME_HEADERS = ('ad', 'adı', 'soyad', 'isim', 'name', 'müşteri', 'musteri', 'unvan', 'ünvan', 'kişi', 'kisi')
CODE_HEADERS = ('kod', 'code', 'cari')


def _norm_header(value):
    text = str(value or '').strip().replace('İ', 'i').replace('I', 'ı').lower()
    return re.sub(r'\s+', ' ', text)


def _match(header, keys):
    """Kelime eşleşmesi; 3+ harfli anahtarlar kelime başında da eşleşir (tel → telefon, ama ad ≠ adres)."""
    words = [w for w in re.split(r'[\s_./()-]+', header) if w]
    return any(k in words or (len(k) >= 3 and any(w.startswith(k) for w in words)) for k in keys)


def detect_columns(rows):
    """Başlık satırından (yoksa içerikten) telefon / ad / kod sütunlarını bul.

    Dönen: (veri satırları, {'mobile': i, 'name': i|None, 'customer_code': i|None})
    """
    if not rows:
        return [], {}
    header = [_norm_header(c) for c in rows[0]]
    cols = {'mobile': None, 'name': None, 'customer_code': None}
    for i, h in enumerate(header):
        if not h:
            continue
        if cols['mobile'] is None and _match(h, PHONE_HEADERS):
            cols['mobile'] = i
        elif cols['customer_code'] is None and _match(h, CODE_HEADERS):
            cols['customer_code'] = i
        elif cols['name'] is None and _match(h, NAME_HEADERS):
            cols['name'] = i
    if cols['mobile'] is not None:
        return rows[1:], cols
    # Başlık yok: numaraların çoğunun geçerli olduğu ilk sütun telefon, ilk metin sütunu ad
    sample = rows[:50]
    width = max(len(r) for r in sample)
    for i in range(width):
        values = [r[i] for r in sample if i < len(r) and str(r[i] or '').strip()]
        if values and sum(1 for v in values if normalize_number(str(v))) >= len(values) * 0.6:
            cols['mobile'] = i
            break
    if cols['mobile'] is None:
        return rows, cols
    for i in range(width):
        if i != cols['mobile'] and any(re.search(r'[A-Za-zÇĞİÖŞÜçğıöşü]', str(r[i] or ''))
                                       for r in sample if i < len(r)):
            cols['name'] = i
            break
    # İlk satır başlık mıydı? (telefon hücresi geçersizse başlık say)
    first_is_header = not normalize_number(str(rows[0][cols['mobile']] if cols['mobile'] < len(rows[0]) else ''))
    return (rows[1:] if first_is_header else rows), cols


def _cell(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # Excel 5321234567.0
    return str(value).strip()


def read_file(content, filename):
    """xlsx / csv / txt dosyasını satır listesine çevir."""
    name = (filename or '').lower()
    if name.endswith(('.xlsx', '.xlsm')):
        try:
            import openpyxl
        except ImportError as e:
            raise UserError(_('Excel okuma kütüphanesi (openpyxl) yüklü değil.')) from e
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as e:
            raise UserError(_('Excel dosyası okunamadı: %s') % e) from e
        ws = wb.worksheets[0]
        rows = [[_cell(c) for c in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
    elif name.endswith('.xls'):
        raise UserError(_('Eski .xls biçimi desteklenmiyor; dosyayı .xlsx ya da .csv olarak kaydedin.'))
    else:
        for enc in ('utf-8-sig', 'cp1254', 'latin-1'):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=';,\t|')
        except csv.Error:
            class dialect(csv.excel):
                delimiter = ';' if text.count(';') > text.count(',') else ','
        rows = [[_cell(c) for c in row] for row in csv.reader(io.StringIO(text), dialect)]
    return [r for r in rows if any(r)]


class SmsContactImport(models.TransientModel):
    _name = 'sms.system.contact.import'
    _description = 'SMS Rehberine Excel/CSV Aktar'

    file = fields.Binary(string='Dosya', required=True)
    filename = fields.Char()
    list_id = fields.Many2one('sms.system.list', string='Eklenecek Liste')
    new_list_name = fields.Char(string='ya da Yeni Liste')
    list_type = fields.Selection([('customer', 'Müşteri'), ('staff', 'Personel')], string='Yeni Liste Türü',
                                 default='customer')
    source = fields.Selection([('excel', 'Excel/CSV'), ('nebim', 'Nebim dökümü')], string='Kaynak',
                              default='excel', required=True)
    result = fields.Text(string='Sonuç', readonly=True)
    done = fields.Boolean()

    def action_import(self):
        self.ensure_one()
        if not self.list_id and not (self.new_list_name or '').strip():
            raise UserError(_('Bir liste seçin ya da yeni liste adı yazın.'))
        rows = read_file(base64.b64decode(self.file), self.filename)
        data, cols = detect_columns(rows)
        if cols.get('mobile') is None:
            raise UserError(_('Telefon sütunu bulunamadı. İlk satıra "Ad" ve "Telefon" başlıklarını yazın.'))

        def get(row, key):
            i = cols.get(key)
            return row[i] if i is not None and i < len(row) else ''

        records = [{'mobile': get(r, 'mobile'), 'name': get(r, 'name'), 'customer_code': get(r, 'customer_code')}
                   for r in data]
        lst = self.list_id or self.env['sms.system.list'].create(
            {'name': self.new_list_name.strip(), 'list_type': self.list_type})
        res = self.env['sms.system.contact'].upsert_numbers(records, self.source, lists=lst)
        lines = [
            _('Liste: %s') % lst.name,
            _('Okunan satır: %s') % len(records),
            _('Yeni eklenen: %s') % res['created'],
            _('Rehberde zaten olan (listeye bağlandı): %s') % res['updated'],
            _('Dosyada tekrar eden: %s') % res['duplicate'],
            _('Geçersiz numara: %s') % len(res['invalid']),
        ]
        if res['invalid']:
            lines.append(_('Geçersiz örnekler: %s') % ', '.join(res['invalid'][:20]))
        self.write({'result': '\n'.join(lines), 'done': True, 'list_id': lst.id})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new', 'name': _('Aktarım Sonucu')}

    def action_open_list(self):
        self.ensure_one()
        return self.list_id.action_view_contacts()


class SmsAddToList(models.TransientModel):
    """Odoo kişilerinden / kullanıcılardan seçilenleri SMS listesine ekle."""
    _name = 'sms.system.add.to.list'
    _description = 'SMS Listesine Ekle'

    list_id = fields.Many2one('sms.system.list', string='Liste')
    new_list_name = fields.Char(string='ya da Yeni Liste')
    list_type = fields.Selection([('customer', 'Müşteri'), ('staff', 'Personel')], string='Yeni Liste Türü',
                                 default=lambda self: 'staff' if self.env.context.get('active_model') == 'res.users'
                                 else 'customer')
    record_count = fields.Integer(string='Seçili Kayıt', compute='_compute_record_count')

    @api.depends_context('active_ids')
    def _compute_record_count(self):
        for wiz in self:
            wiz.record_count = len(self.env.context.get('active_ids') or [])

    def _partners(self):
        model = self.env.context.get('active_model')
        ids = self.env.context.get('active_ids') or []
        if model == 'res.users':
            return self.env['res.users'].browse(ids).mapped('partner_id')
        if model == 'res.partner':
            return self.env['res.partner'].browse(ids)
        raise UserError(_('Bu işlem yalnız Kişiler ve Kullanıcılar listesinden yapılabilir.'))

    def action_add(self):
        self.ensure_one()
        if not self.list_id and not (self.new_list_name or '').strip():
            raise UserError(_('Bir liste seçin ya da yeni liste adı yazın.'))
        partners = self._partners()
        lst = self.list_id or self.env['sms.system.list'].create(
            {'name': self.new_list_name.strip(), 'list_type': self.list_type})
        rows = [{'mobile': p.phone, 'name': p.name, 'partner_id': p.id} for p in partners if p.phone]
        res = self.env['sms.system.contact'].upsert_numbers(rows, 'odoo', lists=lst)
        no_phone = len(partners) - len(rows)
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': lst.name, 'sticky': bool(no_phone or res['invalid']),
                'type': 'success' if res['created'] or res['updated'] else 'warning',
                'message': _('%(c)s yeni, %(u)s mevcut kişi listeye eklendi. Telefonu olmayan: %(n)s, '
                             'geçersiz numara: %(i)s.', c=res['created'], u=res['updated'], n=no_phone,
                             i=len(res['invalid'])),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
