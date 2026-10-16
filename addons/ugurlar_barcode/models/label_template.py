import logging
from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class LabelTemplate(models.Model):
    _name = 'ugurlar.label.template'
    _description = 'Etiket Şablonu'
    _order = 'is_default desc, name'

    name = fields.Char('Şablon Adı', required=True)
    width_mm = fields.Float('Genişlik (mm)', default=60, required=True)
    height_mm = fields.Float('Yükseklik (mm)', default=40, required=True)
    elements_json = fields.Text('Eleman Verisi (JSON)', default='[]')
    is_default = fields.Boolean('Varsayılan', default=False)
    user_id = fields.Many2one('res.users', string='Oluşturan',
                              default=lambda self: self.env.uid)

    # ─── Yetki: kargo etiketi ve varsayılan şablon yalnız stok yöneticisi ───
    # Kural env.uid ile değerlendirilir: controller sudo() kullansa da uid değişmez.
    # Süperkullanıcı (uid 1: modül yükleme, cron) muaftır.
    def _is_template_admin(self):
        if self.env.uid == SUPERUSER_ID:
            return True
        user = self.env.user
        return user.has_group('stock.group_stock_manager') or user.has_group('base.group_system')

    @staticmethod
    def _is_cargo_name(name):
        return 'kargo' in (name or '').lower()

    def _deny(self, mesaj):
        raise AccessError(mesaj)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Denetim oluşan kayıtların GERÇEK değerleriyle yapılır: bağlam (default_*), ir.default,
        # name_create ve load varsayılanları super().create içinde eklenir, vals'ta görünmez.
        # Hata fırlatılınca işlem (ya da çağıranın savepoint'i) geri alınır.
        if not self._is_template_admin():
            for rec in records.sudo():
                if self._is_cargo_name(rec.name):
                    self._deny("Adında 'Kargo' geçen etiket şablonunu yalnız stok yöneticisi oluşturabilir.")
                if rec.is_default:
                    self._deny("Varsayılan etiket şablonunu yalnız stok yöneticisi belirleyebilir.")
        return records

    def write(self, vals):
        if not self._is_template_admin():
            if any(self._is_cargo_name(n) for n in self.sudo().mapped('name')):
                self._deny("Adında 'Kargo' geçen etiket şablonunu yalnız stok yöneticisi değiştirebilir.")
            if 'name' in vals and self._is_cargo_name(vals['name']):
                self._deny("Bir şablonu 'Kargo' adıyla yalnız stok yöneticisi adlandırabilir.")
            if 'is_default' in vals and any(
                    bool(vals['is_default']) != r.is_default for r in self.sudo()):
                self._deny("Varsayılan etiket şablonunu yalnız stok yöneticisi belirleyebilir.")
        return super().write(vals)

    def unlink(self):
        if not self._is_template_admin():
            if any(self._is_cargo_name(n) for n in self.sudo().mapped('name')):
                self._deny("Adında 'Kargo' geçen etiket şablonunu yalnız stok yöneticisi silebilir.")
            if any(self.sudo().mapped('is_default')):
                self._deny("Varsayılan etiket şablonunu yalnız stok yöneticisi silebilir.")
        return super().unlink()
