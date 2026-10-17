"""Ortak test yardımcıları (ugurlar_barcode kabul testleri).

Controller çağrıları gerçek ORM üzerinde çalışır; yalnız `request` nesnesi
`SimpleNamespace(env=self.env)` ile yamalanır (test_batch_flows.py kalıbı).
"""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.ugurlar_barcode.controllers import base_api, packing_api


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


class PackingCase(BarcodeCase):
    """Dal B (paketleme / fatura) ortak yardımcıları.

    - `cr.commit` ve Nebim connector taklit edilir (TransactionCase içinde commit hata verir).
    - `cr.savepoint` derinliği izlenir: `cr.commit()` ve Nebim çağrısı hiçbir savepoint
      bloğunun içinden yapılmamalıdır (PROJE.md kuralı, KK-B3.2).
    - `button_validate` seçili picking'ler için hata verecek şekilde yamalanabilir.
    """

    def setUp(self):
        super().setUp()
        self._patch_request(packing_api)
        self.pack_ctl = packing_api.PackingApiController()
        self.sp_depth = [0]
        self._track_savepoints()

    # ─── savepoint derinliği ───────────────────────────
    def _track_savepoints(self):
        cr = self.env.cr
        original = cr.savepoint
        depth = self.sp_depth

        @contextmanager
        def tracked(*args, **kwargs):
            depth[0] += 1
            try:
                with original(*args, **kwargs) as sp:
                    yield sp
            finally:
                depth[0] -= 1

        p = patch.object(cr, 'savepoint', tracked)
        p.start()
        self.addCleanup(p.stop)

    # ─── doğrulama hatası ──────────────────────────────
    def _break_validate(self, pickings, message='Test doğrulama hatası'):
        """Verilen picking'lerin `button_validate` çağrısı UserError verir.
        Dönen sözlükte `ids` boşaltılırsa doğrulama yeniden çalışır; `calls` çağrı sayısıdır."""
        picking_cls = type(self.env['stock.picking'])
        original = picking_cls.button_validate
        state = {'ids': set(pickings.ids), 'calls': 0}

        def fake(rec, *args, **kwargs):
            if set(rec.ids) & state['ids']:
                state['calls'] += 1
                raise UserError(message)
            return original(rec, *args, **kwargs)

        p = patch.object(picking_cls, 'button_validate', fake)
        p.start()
        self.addCleanup(p.stop)
        return state

    # ─── Nebim taklidi (gerçek _trigger_nebim_sync çalışır) ───
    def _nebim_real(self, invoice=True):
        """Connector, fatura yükü ve `cr.commit` taklit edilir. Returns sözlük:
        `sent` gönderilen fatura kayıtları, `commits` her commit anındaki
        (post_data çağrı sayısı, savepoint derinliği, nebim_sent DB değerleri)."""
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('odoougurlar.nebim_sync_customer_enabled', 'False')
        icp.set_param('odoougurlar.nebim_sync_order_enabled', 'False')
        icp.set_param('odoougurlar.nebim_sync_invoice_enabled', 'True' if invoice else 'False')

        rec = {'sent': [], 'posts': 0, 'commits': []}
        proc_cls = type(self.env['odoougurlar.invoice.processor'])
        conn_cls = type(self.env['odoougurlar.nebim.connector'])

        def fake_payload(proc, inv):
            rec['sent'].append(inv)
            return {'invoice': inv.id}

        def fake_post(conn, endpoint, payload):
            rec['posts'] += 1
            return {'DocumentNumber': 'UGE-TEST-%s' % rec['posts']}

        def fake_commit():
            self.env.flush_all()
            self.env.cr.execute(
                "SELECT id, nebim_sent FROM account_move WHERE nebim_sent IS TRUE")
            rec['commits'].append({
                'posts': rec['posts'],
                'depth': self.sp_depth[0],
                'sent_ids': sorted(r[0] for r in self.env.cr.fetchall()),
            })

        for target, name, fn in (
                (proc_cls, '_build_invoice_payload', fake_payload),
                (conn_cls, 'post_data', fake_post)):
            p = patch.object(target, name, fn)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(self.env.cr, 'commit', fake_commit)
        p.start()
        self.addCleanup(p.stop)
        return rec

    # ─── satış siparişi ────────────────────────────────
    def _sale(self, product, qty, price=10.0, stock_qty=None):
        """Teslimata göre faturalanan onaylı satış siparişi. Returns (sale, giden picking)."""
        product.product_tmpl_id.invoice_policy = 'delivery'
        self._add_stock(product, self.stock, stock_qty if stock_qty is not None else qty + 5)
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id, 'product_uom_qty': qty, 'price_unit': price})],
        })
        sale.action_confirm()
        picking = sale.picking_ids.filtered(lambda p: p.picking_type_code == 'outgoing')
        self.assertEqual(len(picking), 1, 'ön koşul: tek giden sevkiyat')
        picking.action_assign()
        self.assertEqual(picking.state, 'assigned', 'ön koşul: rezerv tam')
        return sale, picking

    def _out_invoices(self, sale):
        sale.invalidate_recordset(['invoice_ids'])
        return sale.invoice_ids.filtered(lambda i: i.move_type == 'out_invoice')
