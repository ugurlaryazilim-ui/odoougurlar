"""TODO-26 + TODO-27: paketleme okutması başına tam rota yenileme kalkar; toplama
zamanlayıcısı quant kilitlerini ara commit ile kısa tutar."""
import re
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tools import file_open

from odoo.addons.ugurlar_barcode.models import picking_schedule
from odoo.addons.ugurlar_barcode.tests.test_packing_flows import PackingFlowCase


def _packing_js():
    with file_open('ugurlar_barcode/static/src/js/screens/packing.js') as f:
        return f.read()


@tagged('post_install', '-at_install')
class TestPackingScanItemUpdate(PackingFlowCase):
    """TODO-26: okutma yanıtı satırın yeni durumunu taşır; tam yenileme yalnız gerektiğinde."""

    def _detail_item(self, batch, move):
        res = self.pack_ctl.packing_batch_detail(batch_id=batch.id)
        return next(i for i in res['items'] if i['move_id'] == move.id)

    def test_mid_order_scan_returns_patchable_row_and_no_refresh(self):
        picking = self._routed(self.prod_a, 2, wave=2, origin='SO-PERF-1')
        batch = self._route(picking)
        move = picking.move_ids

        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')

        self.assertTrue(res.get('success'), res)
        self.assertFalse(res['refresh_needed'], 'sıradan okutmada tam yenileme gerekmez')
        upd = res['item_update']
        self.assertEqual(upd['move_id'], move.id)
        # Yamalı satır, tam yenilenen listedeki satırla aynı alanları taşımalı
        item = self._detail_item(batch, move)
        for key in ('target_qty', 'done_qty', 'matched', 'scanned_qty'):
            self.assertEqual(upd[key], item[key], key)
        self.assertEqual(upd['scanned_qty'], 1)
        self.assertFalse(upd['matched'])

    def test_completing_scan_requests_full_refresh(self):
        picking = self._routed(self.prod_a, 1, wave=1, origin='SO-PERF-2')
        batch = self._route(picking)

        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')

        self.assertTrue(res.get('picking_completed'), res)
        self.assertTrue(res['refresh_needed'], 'sipariş tamamlanınca doğrulama/rota durumu yenilenmeli')

    def test_validate_error_requests_full_refresh(self):
        picking = self._routed(self.prod_a, 1, wave=1, origin='SO-PERF-3')
        batch = self._route(picking)
        self._break_validate(picking)

        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')

        self.assertTrue(res.get('validate_error'), res)
        self.assertTrue(res['refresh_needed'])

    def test_soft_match_requests_full_refresh(self):
        other, cancelled = self._with_cancelled(self.prod_a, origin='SO-PERF-4')
        batch = self._route(other)

        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')

        self.assertTrue(res.get('soft_match'), res)
        self.assertTrue(res['refresh_needed'])

    def test_js_patches_row_instead_of_refetching(self):
        """JS kaynak kontrolü (JS test altyapısı yok): başarılı okutma yanıttaki satırı yamar,
        _refreshList yalnız refresh_needed / yama başarısızsa çağrılır."""
        src = _packing_js()
        self.assertRegex(src, r'_applyItemUpdate\(res\.item_update\)')
        self.assertRegex(
            src, r'if \(res\.refresh_needed \|\| !this\._applyItemUpdate\(res\.item_update\)\) \{\s*'
                 r'await this\._refreshList\(batchId, ctx\);')
        # Okutma yolunda koşulsuz yenileme kalmamalı
        scan_body = src.split('async _processScan', 1)[1].split('onReprintLabel', 1)[0]
        self.assertEqual(len(re.findall(r'await this\._refreshList\(', scan_body)), 1)


@tagged('post_install', '-at_install')
class TestScheduleCommitProgress(PackingFlowCase):
    """TODO-27: cron yolunda rezervasyon parti parti commit edilir, elle yolda edilmez."""

    def _unassigned(self, count):
        self._add_stock(self.prod_a, self.shelf, count + 2)
        return self.env['stock.picking'].union(*[
            self._picking(self.prod_a, 1, assign=False) for _i in range(count)])

    def _count_commits(self, schedule, pickings):
        commits = []
        depth = self.sp_depth

        with patch.object(self.env.cr, 'commit', lambda: commits.append(depth[0])), \
                patch.object(picking_schedule, 'ASSIGN_COMMIT_EVERY', 2):
            schedule._safe_assign(pickings)
        return commits

    def test_cron_path_commits_per_batch_outside_savepoint(self):
        pickings = self._unassigned(5)
        schedule = self.env['ugurlar.picking.schedule'].new({})
        commits = self._count_commits(
            schedule.with_context(ugurlar_commit_progress=True), pickings)
        self.assertEqual(len(commits), 3, '5 picking / parti=2 -> 2 ara commit + son commit')
        self.assertEqual(set(commits), {0}, 'commit hiçbir savepoint bloğunun içinde olmamalı')
        self.assertTrue(all(p.state == 'assigned' for p in pickings))

    def test_manual_path_never_commits(self):
        pickings = self._unassigned(3)
        schedule = self.env['ugurlar.picking.schedule'].new({})
        self.assertEqual(self._count_commits(schedule, pickings), [])
        self.assertTrue(all(p.state == 'assigned' for p in pickings))

    def test_cron_run_commits_per_schedule_and_rolls_back_on_error(self):
        plan = self.env['ugurlar.picking.schedule'].create({
            'name': 'Commit Test Planı', 'warehouse_id': self.wh.id})
        self.env['ugurlar.picking.schedule'].search([('id', '!=', plan.id)]).write({'active': False})
        events, flags = [], []
        depth = self.sp_depth

        def check(rec):
            flags.append(rec.env.context.get('ugurlar_commit_progress'))
            raise ValueError('plan hatası')

        with patch.object(self.env.cr, 'commit', lambda: events.append(('commit', depth[0]))), \
                patch.object(self.env.cr, 'rollback', lambda: events.append(('rollback', depth[0]))), \
                patch.object(type(plan), '_check_and_create_batch', check):
            self.env['ugurlar.picking.schedule']._cron_run()

        self.assertEqual(flags, [True], 'cron yolu ara commit bayrağını açmalı')
        self.assertEqual(events, [('commit', 0), ('rollback', 0)],
                         'başlangıç commit + hatalı plan için rollback (savepoint dışında)')
