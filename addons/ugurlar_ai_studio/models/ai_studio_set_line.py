from odoo import api, models, fields, _
from odoo.exceptions import AccessError


class AiStudioSetLine(models.Model):
    """Takım çekimindeki her bir ürün parçası.

    Örnek: Pantolon + Ceket takımında 2 set_line olur:
      - Ana Parça (primary): Pantolon
      - Takım Parçası (companion): Ceket
    """
    _name = 'ai.studio.set.line'
    _description = 'AI Studio Takım Parçası'
    _order = 'sequence, id'

    session_id = fields.Many2one(
        'ai.studio.session',
        string='Oturum',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Ürün',
        required=True,
        index=True,
    )
    sequence = fields.Integer(default=10)
    role = fields.Selection([
        ('primary', 'Ana Parça'),
        ('companion', 'Takım Parçası'),
    ], string='Rol', default='companion', required=True)

    # --- İlişkili Alanlar (Kolay Erişim) ---
    barcode = fields.Char(
        related='product_id.barcode',
        string='Barkod',
        store=True,
    )
    product_name = fields.Char(
        related='product_id.display_name',
        string='Ürün Adı',
    )
    product_image = fields.Image(
        related='product_id.image_128',
        string='Ürün Resmi',
    )

    # --- Bu parçaya ait fotoğraflar ---
    photo_ids = fields.One2many(
        'ai.studio.photo',
        'set_line_id',
        string='Fotoğraflar',
    )

    # DIKKAT: 'review'/'saving'/'done' oturumda set satırı değişirse kuyruk onaycının gördüğünden farklı ürüne
    # yazar (A4 O1, J10 O-J10-2). Kilit kayıt kuralında (rule_set_line_operator_edit); burada yalnız kuralın
    # göremediği taşıma — durum listesi kuralınkiyle aynı tutulmalı.
    def write(self, vals):
        Session = self.env['ai.studio.session']
        locked = ('review', 'saving', 'done')
        # NEDEN: kural da reddeder ama genel İngilizce mesajla; operatör nedenini görsün.
        if any(s in locked for s in self.session_id.mapped('state')) and not Session._is_approval_authority():
            raise AccessError(_('İncelemedeki veya onaylanan oturumun takım parçalarını yalnız onaycı veya '
                                'yönetici değiştirebilir.'))
        Session._check_target_session_unlocked(vals, _('takım parçası'), states=locked)
        before = self.session_id
        res = super().write(vals)
        if {'product_id', 'role', 'session_id'} & set(vals):
            self._drop_session_approvals(before | self.session_id)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._drop_session_approvals(records.session_id)
        return records

    def _drop_session_approvals(self, sessions):
        # NEDEN (J10 KK2): takım modunda kuyruk set satırlarının ürünlerine yazar; onaydan sonra yetkisiz
        # değişen takım onaylanmamış ürünlere görsel yazdırırdı. unlink yok: operatör ACL'inde silme kapalı.
        if sessions and not self.env['ai.studio.session']._is_approval_authority():
            sessions._drop_approvals(_('takım parçaları'))
