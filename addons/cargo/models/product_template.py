# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import AccessError

# NEDEN: delivery.carrier.company_id çekirdekte product_id.company_id'nin saklanan related'ıdır (zincir: varyant →
# şablon → şirket). Ürün tarafındaki yazım firma şirketini carrier.write'a (O-1 korunan alan denetimi) uğramadan
# değiştirir: ürün yöneticisi yönetilen firmayı başka şirkete taşıyabilir ya da paylaşımlı yapabilirdi
# (05-guvenlik D-5, D-5b; 05-inceleme Y2). Denetimler yalnız ilgili anahtar vals'tayken sorgu yapar (Nebim/pazaryeri
# ürün yazımlarına ek maliyet yok); env.su (kurulum, -u, root cron) ve Kargo / Yönetici muaftır.


def _cargo_record_id(value):
    return (value.id if isinstance(value, models.BaseModel) else value) or False


def _cargo_exempt(env):
    return env.su or env.user.has_group('cargo.group_cargo_manager')


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _cargo_check_company_change(self, vals):
        if 'company_id' not in vals or _cargo_exempt(self.env):
            return
        new = _cargo_record_id(vals['company_id'])
        changed = self.filtered(lambda template: template.company_id.id != new)
        if changed and changed.with_context(active_test=False).product_variant_ids._cargo_is_managed_delivery():
            raise AccessError(_(
                'Bu ürün bir kargo firmasının teslimat ürünü; şirketini yalnız "Kargo / Yönetici" '
                'değiştirebilir (ürünün şirketi kargo firmasının şirketidir).'))

    def write(self, vals):
        # DIKKAT: super()'den ÖNCE (DERSLER 4). Yönetilmeyen firmanın company_id inverse'i de buraya düşer.
        self._cargo_check_company_change(vals)
        return super().write(vals)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _cargo_is_managed_delivery(self):
        """Varyantlardan biri (arşivli dahil) yönetilen bir kargo firmasının teslimat ürünü mü?"""
        carriers = self.env['delivery.carrier'].sudo().with_context(active_test=False).search(
            [('product_id', 'in', self.ids)])
        return any(carrier._cargo_is_managed() for carrier in carriers)

    def _cargo_check_template_change(self, vals):
        # NEDEN (D-5b): varyantın şablonu başka şirketteki şablona çevrilirse firma şirketi (ve adı/fiyatı) yeni
        # şablondan gelir. Şirket karşılaştırması yerine değişim tümden reddedilir: teslimat varyantını başka
        # şablona taşımanın meşru kullanımı yok. Şablon create/write'taki product_variant_ids Command.link/set
        # çekirdekte (One2many.write_real: lines[inverse] = record) bu write'a iner; ayrı denetim gerekmez.
        if 'product_tmpl_id' not in vals or _cargo_exempt(self.env):
            return
        new = _cargo_record_id(vals['product_tmpl_id'])
        changed = self.filtered(lambda variant: variant.product_tmpl_id.id != new)
        if changed and changed._cargo_is_managed_delivery():
            raise AccessError(_(
                'Bu ürün bir kargo firmasının teslimat ürünü; şablonunu yalnız "Kargo / Yönetici" değiştirebilir '
                '(firmanın şirketi, adı ve fiyatı şablondan gelir).'))

    def write(self, vals):
        # NEDEN: varyanttan company_id yazımı şablona inverse ile iner ve orada da reddedilir; ama ORM o ana kadar
        # varyantın company_id önbelleğini yeni değere çekmiş olur, hatayı yakalayıp süren çağıranda firma şirketi
        # yeni değerle hesaplanır. Denetim varyant yazımından önce de yapılır.
        if 'company_id' in vals:
            self.product_tmpl_id._cargo_check_company_change(vals)
        self._cargo_check_template_change(vals)
        return super().write(vals)
