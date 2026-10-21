from odoo import models, fields, api, _


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

    # DIKKAT: 'saving'/'done' oturumda set satırı değişirse kuyruk onaylanandan farklı ürüne yazar (A4 O1).
    # Tüm alanlar kilitli (izin listesi yok); kilit mevcut VE hedef (session_id taşıma) oturuma bakar.
    @api.model_create_multi
    def create(self, vals_list):
        self.env['ai.studio.session']._check_approved_lock_create(vals_list, _('takım parçası'))
        return super().create(vals_list)

    def write(self, vals):
        self.env['ai.studio.session']._check_approved_lock_on(self.session_id, vals, label=_('takım parçası'))
        return super().write(vals)
