# -*- coding: utf-8 -*-
from psycopg2 import errors as pg_errors

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

# NEDEN: pazaryeri modüllerinin stock.picking kancaları doğrulamada carrier_tracking_ref'i okuyup pazaryerine
# "kargo takip no" diye gönderir; kargo gönderisinin takip no'su bu transferlere yazılmaz (K-20, 02-tasarim §1.2).
# Alan adları ugurlar_barcode._MARKETPLACE_REGISTRY ile aynıdır (+ Shopify, S-6). Kontrol ``in sale._fields``
# iledir: pazaryeri modülü kurulu değilse alan yoktur ve atlanır (bağımlılık eklenmez).
# EKIP-BORC: yeni pazaryeri modülü eklenince bu liste elle güncellenmeli; sale.order'a ortak bir pazaryeri
# işareti (ör. marketplace_name) eklenirse liste kalkar.
_CARGO_MARKETPLACES = (
    ('trendyol_order_id', 'Trendyol'), ('hb_order_id', 'Hepsiburada'), ('amazon_order_id', 'Amazon'),
    ('pazarama_order_id', 'Pazarama'), ('n11_order_id', 'N11'), ('flo_order_id', 'Flo'),
    ('idefix_order_id', 'Idefix'), ('pttavm_order_id', 'PttAvm'), ('shopify_order_id', 'Shopify'),
)
# NEDEN: shopify_integration transferi ``shopify.order.sale_order_id`` ile tanır; sale.shopify_order_id boş olan
# (alan eklenmeden önceki, elle bağlanan) siparişte yalnız alana bakmak takip noyu Shopify'a yanlış firmayla
# gönderirdi (05-inceleme Shopify). (model, siparişe bağlayan alan, ad)
_CARGO_MARKETPLACE_MODELS = (('shopify.order', 'sale_order_id', 'Shopify'),)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    cargo_marketplace_name = fields.Char(
        string='Pazaryeri', compute='_compute_cargo_marketplace_name',
        help='Sipariş bir pazaryerinden geldiyse adı; takip numarası pazaryerine gittiği için kargo '
             'gönderisi bu transfere takip yazmaz.')
    cargo_shipment_ids = fields.One2many('cargo.shipment', 'picking_id', string='Kargo gönderileri', copy=False)

    @api.depends('sale_id')
    def _compute_cargo_marketplace_name(self):
        for picking in self:
            sale = picking.sudo().sale_id
            name = next((name for field, name in _CARGO_MARKETPLACES if field in sale._fields and sale[field]), False)
            if not name and sale:
                name = next((name for model, field, name in _CARGO_MARKETPLACE_MODELS if model in self.env
                             and self.env[model].sudo().search_count([(field, '=', sale.id)], limit=1)), False)
            picking.cargo_marketplace_name = name

    def action_cargo_shipment_open(self):
        """Transferin açık kargo gönderisini açar; yoksa teslimat adresinden taslak oluşturur (02-tasarim §4.6)."""
        self.ensure_one()
        if not self.env.user.has_group('cargo.group_cargo_user'):
            raise AccessError(_('Kargo gönderisi açmak için "Kargo / Kullanıcı" yetkisi gerekir.'))
        if self.picking_type_code != 'outgoing' or self.state == 'cancel':
            raise UserError(_('Kargo gönderisi yalnız iptal edilmemiş giden transferden açılır.'))
        # NEDEN: picking_id sistem alanıdır (yalnız sudo yazar); şirket transferin şirketidir (check_company).
        picking = self.sudo()
        shipment = picking.cargo_shipment_ids.filtered(lambda s: s.state not in ('cancelled', 'failed'))[:1]
        if not shipment:
            shipment = self._cargo_shipment_create()
        return {
            'type': 'ir.actions.act_window', 'res_model': 'cargo.shipment', 'res_id': shipment.id,
            'view_mode': 'form', 'views': [(False, 'form')],
        }

    def _cargo_shipment_create(self):
        partner = self.partner_id.sudo()
        # NEDEN: Odoo 19 res.partner'da ``mobile`` alanı yok; telefon yalnız ``phone``.
        street = ' '.join(part for part in (partner.street, partner.street2) if part)
        Shipment = self.env['cargo.shipment'].sudo().with_company(self.company_id)
        # NEDEN: iş referansı (transfer adı) tüm şirketlerde tek aktif gönderiye aittir (benzersiz indeks). Aynı
        # referansla elle/API ile açılmış başka bir gönderi düğmeyi sunucu hatasıyla kilitlemesin; engelleyen
        # gönderinin adı söylenir (05-guvenlik D-2).
        blocking = Shipment.search([('origin_ref', '=', self.name), ('state', 'not in', ('cancelled', 'failed'))], limit=1)
        if blocking:
            raise UserError(_('"%(ref)s" iş referansıyla başka bir kargo gönderisi açık: %(name)s. Bu transfer için '
                              'gönderi açmadan önce o gönderiyi iptal edin.', ref=self.name, name=blocking.name))
        try:
            with self.env.cr.savepoint():
                return Shipment.create({
                    'company_id': self.company_id.id,
                    'picking_id': self.id,
                    'source_model': self._name,
                    'source_id': self.id,
                    'origin_ref': self.name,
                    'partner_id': partner.id,
                    'recipient_name': partner.name,
                    'recipient_phone': partner.phone,
                    'recipient_email': partner.email,
                    'recipient_street': street,
                    'recipient_state_id': partner.state_id.id,
                    'recipient_district': partner.city,
                })
        except pg_errors.UniqueViolation:
            # eşzamanlı ikinci tıklama ya da henüz commit'lenmemiş (görünmeyen) kayıt
            raise UserError(_('Bu transfer adıyla açık bir kargo gönderisi zaten var. Birkaç saniye sonra '
                              'yeniden deneyin.')) from None
