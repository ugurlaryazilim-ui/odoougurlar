"""Ortak test yardımcıları (ugurlar_barcode kabul testleri).

Controller çağrıları gerçek ORM üzerinde çalışır; yalnız `request` nesnesi
`SimpleNamespace(env=self.env)` ile yamalanır (test_batch_flows.py kalıbı).
"""
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import TransactionCase

from odoo.addons.ugurlar_barcode.controllers import base_api


class BarcodeCase(TransactionCase):
    """Kendi başına test içermeyen taban sınıf."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock = cls.wh.lot_stock_id
        cls.out_type = cls.wh.out_type_id
        cls.loc_customers = cls.env.ref('stock.stock_location_customers')
        cls.loc_suppliers = cls.env.ref('stock.stock_location_suppliers')
        cls.customer = cls.env['res.partner'].create({'name': 'Kabul Test Müşteri'})
        cls.api = base_api.BarcodeApiBase()

    def setUp(self):
        super().setUp()
        # 500 ms çift okutma koruması ardışık test okutmalarını "çift" sayar
        debounce = patch.object(base_api, '_DEBOUNCE_SECONDS', 0)
        debounce.start()
        self.addCleanup(debounce.stop)

    # ─── yamalar ───────────────────────────────────────
    def _patch_request(self, *modules):
        """base_api + verilen controller modüllerinin `request` nesnesini yamala."""
        fake = SimpleNamespace(env=self.env)
        for mod in (base_api, *modules):
            p = patch.object(mod, 'request', fake)
            p.start()
            self.addCleanup(p.stop)

    # ─── veri kurucular ────────────────────────────────
    @classmethod
    def _new_product(cls, name, barcode, uom=None):
        vals = {'name': name, 'type': 'consu', 'is_storable': True, 'barcode': barcode}
        if uom:
            vals.update({'uom_id': uom.id})
        return cls.env['product.product'].create(vals)

    @classmethod
    def _new_shelf(cls, name, barcode=None, parent=None):
        return cls.env['stock.location'].create({
            'name': name, 'barcode': barcode or False,
            'location_id': (parent or cls.stock).id, 'usage': 'internal'})

    @classmethod
    def _new_warehouse(cls, name, code):
        return cls.env['stock.warehouse'].create({'name': name, 'code': code})

    def _add_stock(self, product, location, qty):
        self.env['stock.quant']._update_available_quantity(product, location, qty)

    def _picking(self, product, demand, *, picking_type=None, src=None, dest=None,
                 origin=None, uom=None, assign=True):
        """Giden (varsayılan) sevkiyat: confirm + assign; rezerv KORUNUR (quantity silinmez)."""
        picking_type = picking_type or self.out_type
        src = src or picking_type.warehouse_id.lot_stock_id
        dest = dest or self.loc_customers
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'partner_id': self.customer.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'origin': origin or False,
            'move_ids': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': demand,
                'product_uom': (uom or product.uom_id).id,
                'location_id': src.id,
                'location_dest_id': dest.id,
            })],
        })
        picking.action_confirm()
        if assign:
            picking.action_assign()
        return picking

    def _route(self, pickings, picking_type=None):
        """Pickings'i bir rotaya (batch) bağla; kalıcı liste de doldurulur."""
        picking_type = picking_type or self.out_type
        batch = self.env['stock.picking.batch'].create({'picking_type_id': picking_type.id})
        pickings.write({'batch_id': batch.id})
        batch.all_picking_ids = [(6, 0, pickings.ids)]
        return batch

    # ─── sorgular ──────────────────────────────────────
    def _qty(self, product, location, child=False):
        op = 'child_of' if child else '='
        quants = self.env['stock.quant'].search([
            ('product_id', '=', product.id), ('location_id', op, location.id)])
        return sum(quants.mapped('quantity'))

    def _done_moves(self, product, **domain_extra):
        domain = [('product_id', '=', product.id), ('state', '=', 'done')]
        for key, value in domain_extra.items():
            domain.append((key.replace('__', '.'), '=', value.id if hasattr(value, 'id') else value))
        return self.env['stock.move'].search(domain)

    def _shipped_qty(self, picking):
        return sum(picking.move_ids.filtered(lambda m: m.state == 'done').mapped('quantity'))
