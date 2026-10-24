# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import AccessError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _cargo_check_company_change(self, vals):
        # NEDEN: delivery.carrier.company_id çekirdekte product_id.company_id'nin saklanan related'ıdır; ürün şirketi
        # yazılınca firma şirketi carrier.write'a (O-1 korunan alan denetimi) uğramadan değişir. Ürün yöneticisi
        # böylece yönetilen firmayı başka şirkete taşıyabilir ya da paylaşımlı yapabilirdi (05-guvenlik D-5, Y2).
        # Yönetilmeyen firmanın company_id inverse'i ürün yazımı olarak buraya düşer. env.su (kurulum/-u) muaftır.
        if 'company_id' not in vals or self.env.su or self.env.user.has_group('cargo.group_cargo_manager'):
            return
        new = vals['company_id']
        new = (new.id if isinstance(new, models.BaseModel) else new) or False
        changed = self.filtered(lambda template: template.company_id.id != new)
        if not changed:
            return
        variants = changed.with_context(active_test=False).product_variant_ids
        carriers = self.env['delivery.carrier'].sudo().with_context(active_test=False).search(
            [('product_id', 'in', variants.ids)])
        if any(carrier._cargo_is_managed() for carrier in carriers):
            raise AccessError(_(
                'Bu ürün bir kargo firmasının teslimat ürünü; şirketini yalnız "Kargo / Yönetici" '
                'değiştirebilir (ürünün şirketi kargo firmasının şirketidir).'))

    def write(self, vals):
        # DIKKAT: super()'den ÖNCE (DERSLER 4).
        self._cargo_check_company_change(vals)
        return super().write(vals)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def write(self, vals):
        # NEDEN: varyanttan yazım şablona inverse ile iner ve orada da reddedilir; ama ORM o ana kadar varyantın
        # company_id önbelleğini yeni değere çekmiş olur, hatayı yakalayıp süren çağıranda firma şirketi yeni değerle
        # hesaplanır. Denetim varyant yazımından önce de yapılır.
        self.product_tmpl_id._cargo_check_company_change(vals)
        return super().write(vals)
