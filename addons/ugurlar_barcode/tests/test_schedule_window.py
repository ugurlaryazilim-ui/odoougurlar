"""Dal C / KK-C1 - C7: zamanlama, rota temizliği, stok durumu, rota adı, sayım filtresi.

- TestScheduleWindow (G8 C1): "Şimdi Oluştur" şu anı içeren pencereyi kullanır.
  Saat `picking_schedule.datetime` yamasıyla dondurulur (eski ve yeni kod aynı şekilde çalışır);
  ayrıca `now_tz` seam'i doğrudan denenir.
- TestRouteCleanup (G8 C2): temizlik cron'u açık siparişli rotalarda takılmaz.
- TestAvailabilityStatus (G9 C3, C4): FAZ 5 availability_status yazar, teşhis yazmaz.
- TestBatchExtAndNames (G9 C5, C6): write içi hata yutulmaz, rota adı tam eşleşme.
- TestCountTodayFilter (G10 C7): "Bugün" filtreleri yerel gün sınırını UTC'ye çevirir.
"""
from datetime import date, datetime, time as dt_time, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytz
from lxml import etree

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.ugurlar_barcode.models import picking_schedule
from odoo.addons.ugurlar_barcode.tests.common import BarcodeCase

IST = pytz.timezone('Europe/Istanbul')


def _today_ist():
    return datetime.now(pytz.UTC).astimezone(IST).date()


def _ist_to_utc(day, hour, minute):
    """Yerel (İstanbul) gün + saat -> naive UTC."""
    return IST.localize(datetime.combine(day, dt_time(hour, minute))) \
        .astimezone(pytz.UTC).replace(tzinfo=None)


class ScheduleCase(BarcodeCase):
    """İzole ana / yedek / iade depolu ve 10:00 - 14:00 - 18:00 saatli plan."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pri = cls._new_warehouse('Pencere Ana Depo', 'WCA')
        cls.fbk = cls._new_warehouse('Pencere Yedek Depo', 'WCB')
        cls.ret = cls._new_warehouse('Pencere Iade Depo', 'WCR')
        # Odoo'nun otomatik tek-sipariş rotası pencere seçimini etkilemesin
        cls.pri.out_type_id.auto_batch = False
        cls.pri_shelf = cls._new_shelf('WC-RAF-A', 'WC-RAF-A', parent=cls.pri.lot_stock_id)
        cls.fbk_shelf = cls._new_shelf('WC-RAF-B', 'WC-RAF-B', parent=cls.fbk.lot_stock_id)
        cls.ret_shelf = cls._new_shelf('WC-RAF-C', 'WC-RAF-C', parent=cls.ret.lot_stock_id)
        cls.prod1 = cls._new_product('Pencere Ürünü 1', 'WC-P1')
        cls.prod2 = cls._new_product('Pencere Ürünü 2', 'WC-P2')
        cls.prod3 = cls._new_product('Pencere Ürünü 3', 'WC-P3')
        cls.prod4 = cls._new_product('Pencere Ürünü 4', 'WC-P4')
        cls.schedule = cls.env['ugurlar.picking.schedule'].create({
            'name': 'Pencere Test Planı',
            'warehouse_id': cls.pri.id,
            'fallback_warehouse_id': cls.fbk.id,
            'return_warehouse_id': cls.ret.id,
            'schedule_line_ids': [
                (0, 0, {'hour': 10, 'minute': 0}),
                (0, 0, {'hour': 14, 'minute': 0}),
                (0, 0, {'hour': 18, 'minute': 0}),
            ],
        })
        lines = cls.schedule.schedule_line_ids.sorted(lambda l: l.hour)
        cls.line10, cls.line14, cls.line18 = lines

    # ─── yardımcılar ───────────────────────────────────
    def _pri_picking(self, product, demand, **kw):
        kw.setdefault('assign', False)
        return self._picking(product, demand, picking_type=self.pri.out_type_id, **kw)

    def _created_at(self, pickings, hour, minute, day=None):
        """create_date ORM ile yazılamaz: SQL ile yerel saate (İstanbul) alınır."""
        when = _ist_to_utc(day or _today_ist(), hour, minute)
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE stock_picking SET create_date=%s WHERE id IN %s", (when, tuple(pickings.ids)))
        pickings.invalidate_recordset(['create_date'])

    def _frozen(self, hour, minute):
        """`picking_schedule.datetime.now` bugünün verilen yerel saatine sabitlenir."""
        fixed = IST.localize(datetime.combine(_today_ist(), dt_time(hour, minute)))

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

        return patch.object(picking_schedule, 'datetime', FrozenDatetime)

    def _now_ist(self, hour, minute):
        return IST.localize(datetime.combine(_today_ist(), dt_time(hour, minute)))

    def _run_window(self, pickings, line=None):
        """Pickings'i 14:00 - 18:00 penceresi içine alıp doğrudan FAZ 1-5'i çalıştırır."""
        self._created_at(pickings, 15, 0)
        now = datetime.now(pytz.UTC).astimezone(IST)
        batch = self.schedule._create_batch_for_window(line or self.line18, now.date(), now)
        pickings.invalidate_recordset()
        pickings.move_ids.invalidate_recordset()
        self.assertTrue(batch, 'ön koşul: pencere rotası oluşmalı')
        return batch


# ═══════════════════════════════════════════════════════════
# G8 / C1
# ═══════════════════════════════════════════════════════════
@tagged('post_install', '-at_install')
class TestScheduleWindow(ScheduleCase):

    def _stocked_picking(self, product, hour, minute):
        self._add_stock(product, self.pri_shelf, 5)
        picking = self._pri_picking(product, 1, assign=True)
        self._created_at(picking, hour, minute)
        return picking

    # ─── KK-C1 ─────────────────────────────────────────
    def test_c1_now_inside_second_window_uses_it(self):
        """14:20'de 'Şimdi Oluştur': 14:00-18:00 penceresi; 14:05'te oluşan sipariş rotaya girer."""
        picking = self._stocked_picking(self.prod1, 14, 5)
        with self._frozen(14, 20):
            batch = self.schedule._create_batch_for_current_window()
        self.assertTrue(batch, '14:05 siparişi için rota oluşmalı')
        self.assertEqual(picking.batch_id, batch)
        self.assertEqual(batch.time_window, '14:01-18:00')

    def test_c1_now_tz_seam_selects_window(self):
        """now_tz parametresi: aynı sonuç, gerçek saatten bağımsız."""
        picking = self._stocked_picking(self.prod1, 14, 5)
        batch = self.schedule._create_batch_for_current_window(now_tz=self._now_ist(14, 20))
        self.assertTrue(batch)
        self.assertEqual(picking.batch_id, batch)
        self.assertEqual(batch.time_window, '14:01-18:00')

    def test_c1_after_last_line_window_extends_to_now(self):
        """19:00'da: son saatten (18:00) sonra oluşan 18:30 siparişi 'şimdi' penceresine girer."""
        picking = self._stocked_picking(self.prod1, 18, 30)
        with self._frozen(19, 0):
            batch = self.schedule._create_batch_for_current_window()
        self.assertTrue(batch, 'son saatten sonraki sipariş için rota oluşmalı')
        self.assertEqual(picking.batch_id, batch)

    def test_c1_before_first_line_uses_first_window(self):
        """Koruma: 09:00'da ilk pencere (dünün son saati, 10:00] kullanılır."""
        picking = self._stocked_picking(self.prod1, 8, 0)
        with self._frozen(9, 0):
            batch = self.schedule._create_batch_for_current_window()
        self.assertTrue(batch)
        self.assertEqual(picking.batch_id, batch)
        self.assertEqual(batch.time_window, '18:01-10:00')

    def test_c1_exact_line_time_uses_that_window(self):
        """Koruma: tam 14:00'te (10:00, 14:00] penceresi; 13:30 siparişi girer."""
        picking = self._stocked_picking(self.prod1, 13, 30)
        with self._frozen(14, 0):
            batch = self.schedule._create_batch_for_current_window()
        self.assertTrue(batch)
        self.assertEqual(picking.batch_id, batch)
        self.assertEqual(batch.time_window, '10:01-14:00')

    # ─── Cron yolu değişmez (koruma) ───────────────────
    def test_c1_get_time_window_unchanged(self):
        today = _today_ist()
        with self._frozen(14, 20):
            second = self.schedule._get_time_window(self.line14)
            first = self.schedule._get_time_window(self.line10)
        self.assertEqual((second[0], second[1], second[2]), (
            datetime.combine(today, dt_time(10, 0)), datetime.combine(today, dt_time(14, 0)),
            '10:01-14:00'))
        self.assertEqual((first[0], first[1], first[2]), (
            datetime.combine(today - timedelta(days=1), dt_time(18, 0)),
            datetime.combine(today, dt_time(10, 0)), '18:01-10:00'))

    def test_c1_cron_path_creates_window_batch_and_marks_completed(self):
        """Koruma: cron 14:03'te 14:00 satırının (10:00, 14:00] penceresini kurar."""
        picking = self._stocked_picking(self.prod1, 13, 30)
        with self._frozen(14, 3):
            self.schedule._check_and_create_batch()
        self.assertTrue(picking.batch_id, 'cron rotayı kurmalı')
        self.assertEqual(picking.batch_id.time_window, '10:01-14:00')
        self.assertTrue(self.schedule._get_completed_times(_today_ist()).get('14:00'))

    def test_c1_window_batch_creation_unchanged(self):
        """Koruma: pencereli rota oluşturma (picking + kalıcı liste + sale order rota adı)."""
        sale = self.env['sale.order'].create({'partner_id': self.customer.id})
        self._add_stock(self.prod1, self.pri_shelf, 5)
        picking = self._pri_picking(self.prod1, 1, assign=True, origin=sale.name)
        batch = self._run_window(picking)
        self.assertEqual(picking.batch_id, batch)
        self.assertIn(picking, batch.all_picking_ids)
        self.assertEqual(batch.time_window, '14:01-18:00')
        self.assertEqual(sale.picking_batch_names, batch.name)


# ═══════════════════════════════════════════════════════════
# G8 / C2
# ═══════════════════════════════════════════════════════════
@tagged('post_install', '-at_install')
class TestRouteCleanup(BarcodeCase):

    def setUp(self):
        super().setUp()
        self.prod = self._new_product('Temizlik Ürünü', 'RC-P1')
        self._add_stock(self.prod, self.stock, 50)
        self.Batch = self.env['stock.picking.batch']
        self.seq = 0

    def _batch(self, open_picking=None, done_picking=None, days=3):
        """Eski, kapanmamış (draft) rota. open_picking: açık sipariş; done_picking: sevk edilmiş."""
        self.seq += 1
        vals = {
            'name': 'RC-TEST-%d' % self.seq,
            'picking_type_id': self.out_type.id,
            'schedule_time': fields.Datetime.now() - timedelta(days=days),
            'time_window': '10:01-14:00',
        }
        pickings = (open_picking or self.env['stock.picking']) | (done_picking or self.env['stock.picking'])
        if pickings:
            vals['all_picking_ids'] = [(6, 0, pickings.ids)]
        return self.Batch.create(vals)

    def _done_picking(self):
        picking = self._picking(self.prod, 1)
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, 'done', 'ön koşul')
        return picking

    def _closable_pair(self):
        """(boş rota -> İptal, sevk edilmiş siparişli rota -> Tamamlandı)"""
        return self._batch(), self._batch(done_picking=self._done_picking())

    # ─── KK-C2 ─────────────────────────────────────────
    def test_c2_open_routes_do_not_block_closable_ones_batch_size(self):
        """batch_size=2: id sırasında ilk 2 rota açık siparişli, sonrakiler kapanmaya uygun."""
        open_p = self._picking(self.prod, 1)
        open1 = self._batch(open_picking=open_p)
        open2 = self._batch(open_picking=open_p)
        empty, shipped = self._closable_pair()

        self.Batch._cron_cleanup_route_batches(batch_size=2)
        (open1 | open2 | empty | shipped).invalidate_recordset()

        self.assertEqual(empty.state, 'cancel')
        self.assertEqual(shipped.state, 'done')
        self.assertEqual((open1.state, open2.state), ('draft', 'draft'),
                         'açık siparişli rotalara dokunulmaz')

    def test_c2_more_open_routes_than_default_limit_do_not_block(self):
        """Varsayılan sınırdan (500) çok açık siparişli rota: sonrakiler yine kapanır."""
        open_p = self._picking(self.prod, 1)
        self.seq += 1
        base = self.seq
        self.Batch.create([{
            'name': 'RC-BULK-%d-%d' % (base, i),
            'picking_type_id': self.out_type.id,
            'schedule_time': fields.Datetime.now() - timedelta(days=3),
            'time_window': '10:01-14:00',
            'all_picking_ids': [(6, 0, open_p.ids)],
        } for i in range(501)])
        empty, shipped = self._closable_pair()

        self.Batch._cron_cleanup_route_batches()
        (empty | shipped).invalidate_recordset()

        self.assertEqual(empty.state, 'cancel')
        self.assertEqual(shipped.state, 'done')

    def test_c2_page_ceiling_logs_warning(self):
        """Sayfa tavanına ulaşılırsa (işlenmemiş rota kalabilir) uyarı loglanır."""
        open_p = self._picking(self.prod, 1)
        self._batch(open_picking=open_p)
        self._batch(open_picking=open_p)
        self._batch(open_picking=open_p)
        with self.assertLogs('odoo.addons.ugurlar_barcode', level='WARNING') as logs:
            self.Batch._cron_cleanup_route_batches(batch_size=1, max_pages=2)
        self.assertTrue(any('sayfa' in line for line in logs.output), logs.output)

    # ─── Normal yol (koruma) ───────────────────────────
    def test_c2_normal_path_closes_finished_keeps_open(self):
        open_batch = self._batch(open_picking=self._picking(self.prod, 1))
        empty, shipped = self._closable_pair()
        self.Batch._cron_cleanup_route_batches()
        (open_batch | empty | shipped).invalidate_recordset()
        self.assertEqual(open_batch.state, 'draft')
        self.assertEqual(empty.state, 'cancel')
        self.assertEqual(shipped.state, 'done')

    def test_c2_all_cancelled_pickings_cancel_the_route(self):
        picking = self._picking(self.prod, 1)
        batch = self._batch(open_picking=picking)
        picking.action_cancel()
        self.Batch._cron_cleanup_route_batches()
        batch.invalidate_recordset()
        self.assertEqual(batch.state, 'cancel')

    def test_c2_recent_route_is_not_touched(self):
        recent = self._batch(days=0)
        self.Batch._cron_cleanup_route_batches()
        recent.invalidate_recordset()
        self.assertEqual(recent.state, 'draft')


# ═══════════════════════════════════════════════════════════
# G9 / C3, C4
# ═══════════════════════════════════════════════════════════
@tagged('post_install', '-at_install')
class TestAvailabilityStatus(ScheduleCase):

    # ─── KK-C3 ─────────────────────────────────────────
    def test_c3_phase5_writes_status_and_batch_counters(self):
        """Ana depoda / yedekte / hiçbir yerde stoku olan siparişler: durum ve rota sayaçları."""
        self._add_stock(self.prod1, self.pri_shelf, 2)
        self._add_stock(self.prod3, self.fbk_shelf, 2)
        p_av = self._pri_picking(self.prod1, 1)
        p_un = self._pri_picking(self.prod2, 1)
        p_fb = self._pri_picking(self.prod3, 1)
        pickings = p_av | p_un | p_fb

        batch = self._run_window(pickings)
        batch.invalidate_recordset()

        self.assertEqual(p_av.availability_status, 'available')
        self.assertEqual(p_un.availability_status, 'unavailable')
        self.assertEqual(p_fb.availability_status, 'other_warehouse')
        self.assertEqual(batch.total_orders, 3)
        self.assertEqual(batch.available_count, 1)
        self.assertEqual(batch.other_warehouse_count, 1)
        self.assertEqual(batch.unavailable_count, 1)

    def test_c3_cancelled_move_is_ignored_in_status(self):
        """İptal edilmiş satır + ana depoda rezerve satır: sipariş 'available' (stoksuz değil)."""
        self._add_stock(self.prod1, self.pri_shelf, 2)
        picking = self._pri_picking(self.prod1, 1)
        src, dest = picking.location_id, picking.location_dest_id
        picking.write({'move_ids': [(0, 0, {
            'product_id': self.prod2.id, 'product_uom_qty': 1,
            'product_uom': self.prod2.uom_id.id,
            'location_id': src.id, 'location_dest_id': dest.id,
        })]})
        picking.action_confirm()
        picking.move_ids.filtered(lambda m: m.product_id == self.prod2)._action_cancel()

        batch = self._run_window(picking)
        batch.invalidate_recordset()

        self.assertEqual(picking.availability_status, 'available')
        self.assertEqual((batch.available_count, batch.unavailable_count), (1, 0))

    def test_c3_mixed_labels_status_mapping(self):
        """Karışık move etiketlerinin sipariş durumu."""
        f = self.schedule._status_from_move_labels
        self.assertEqual(f({'primary'}), 'available')
        self.assertEqual(f({'primary', 'fallback'}), 'partial')
        self.assertEqual(f({'primary', 'return'}), 'partial')
        self.assertEqual(f({'primary', 'unavailable'}), 'unavailable')
        self.assertEqual(f({'fallback', 'unavailable'}), 'unavailable')
        self.assertEqual(f({'fallback', 'return'}), 'other_warehouse')
        self.assertEqual(f({'return'}), 'return_warehouse')

    def test_c3_counters_cover_partial_and_return_and_sum_to_total(self):
        """Rota sayaçları 5 durumun hepsini sayar: toplam total_orders'a eşit olur."""
        statuses = ['available', 'other_warehouse', 'partial', 'return_warehouse', 'unavailable']
        self._add_stock(self.prod1, self.stock, 10)
        pickings = self.env['stock.picking']
        for _status in statuses:
            pickings |= self._picking(self.prod1, 1)
        for picking, status in zip(pickings, statuses):
            picking.availability_status = status
        batch = self._route(pickings)
        batch.invalidate_recordset()

        self.assertEqual(batch.total_orders, 5)
        self.assertEqual(batch.available_count, 1)
        self.assertEqual(batch.other_warehouse_count, 3, 'other_warehouse + partial + return_warehouse')
        self.assertEqual(batch.unavailable_count, 1)
        self.assertEqual(
            batch.available_count + batch.other_warehouse_count + batch.unavailable_count,
            batch.total_orders)

    def test_c3_only_return_warehouse_stock(self):
        self._add_stock(self.prod4, self.ret_shelf, 2)
        picking = self._pri_picking(self.prod4, 1)
        self._run_window(picking)
        self.assertEqual(picking.availability_status, 'return_warehouse')

    def test_c3_phase5_status_write_leaves_no_chatter_noise(self):
        """Tasarım: durum yazımı tracking_disable ile yapılır, sipariş geçmişine not düşmez."""
        self._add_stock(self.prod1, self.pri_shelf, 2)
        picking = self._pri_picking(self.prod1, 1)
        self._run_window(picking)
        self.assertEqual(picking.availability_status, 'available', 'ön koşul')
        tracked = picking.message_ids.tracking_value_ids.filtered(
            lambda t: t.field_id.name == 'availability_status')
        self.assertFalse(tracked, 'Stok Durumu izleme kaydı oluşmamalı')

    # ─── KK-C4 ─────────────────────────────────────────
    def _aged_pickings(self):
        """Pencereye girmeyecek kadar eski (30 gün) ama açık iki sevkiyat; write_date sabit 2000-01-01."""
        self._add_stock(self.prod1, self.pri_shelf, 2)
        p_av = self._pri_picking(self.prod1, 1, assign=True)
        p_un = self._pri_picking(self.prod2, 1)
        pickings = p_av | p_un
        old = datetime(2000, 1, 1)
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE stock_picking SET create_date=%s, write_date=%s WHERE id IN %s",
            (datetime.utcnow() - timedelta(days=30), old, tuple(pickings.ids)))
        self.env.invalidate_all()
        return pickings, old

    def _picking_db_state(self, pickings):
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT id, write_date, availability_status FROM stock_picking WHERE id IN %s ORDER BY id",
            (tuple(pickings.ids),))
        return self.env.cr.fetchall()

    def _message_count(self, pickings):
        return self.env['mail.message'].search_count(
            [('model', '=', 'stock.picking'), ('res_id', 'in', pickings.ids)])

    def test_c4_diagnosis_does_not_write_to_pickings(self):
        pickings, old = self._aged_pickings()
        admin = self.env.ref('base.user_admin')
        self.assertTrue(admin.has_group('stock.group_stock_manager'), 'ön koşul')
        before = self._picking_db_state(pickings)
        messages_before = self._message_count(pickings)
        self.assertTrue(all(row[1] == old and row[2] is None for row in before), 'ön koşul')

        try:
            self.schedule.with_user(admin).action_create_batch_now()
        except UserError as e:
            text = str(e)
        else:
            self.fail('bekleyen sipariş penceresi yok: teşhis UserError ile bitmeli')

        self.assertEqual(self._picking_db_state(pickings), before,
                         'teşhis picking.write_date / availability_status değiştirmemeli')
        self.assertEqual(self._message_count(pickings), messages_before,
                         'teşhis tracking mesajı üretmemeli')
        # aynı teşhis metni
        self.assertIn('Uygun (confirmed/waiting/assigned + batch yok): 2', text)
        self.assertIn('Ana depoda stokta: 1', text)
        self.assertIn('Yedek depoda stokta: 0', text)
        self.assertIn('Stoksuz (unavailable): 1', text)

    def test_c4_check_status_write_false_returns_status_without_writing(self):
        pickings, old = self._aged_pickings()
        p_av, p_un = pickings
        before = self._picking_db_state(pickings)
        messages_before = self._message_count(pickings)

        status_av = p_av._check_availability_status(self.pri, self.fbk, self.ret, write=False)
        status_un = p_un._check_availability_status(self.pri, self.fbk, self.ret, write=False)

        self.assertEqual((status_av, status_un), ('available', 'unavailable'))
        self.assertEqual(self._picking_db_state(pickings), before)
        self.assertEqual(self._message_count(pickings), messages_before)

    def test_c4_check_status_default_still_writes(self):
        """Koruma: elle 'stok durumunu kontrol et' ve FAZ 5 yazımı için varsayılan yazar."""
        pickings, _old = self._aged_pickings()
        p_av = pickings[0]
        status = p_av._check_availability_status(self.pri, self.fbk, self.ret)
        self.assertEqual(status, 'available')
        self.assertEqual(p_av.availability_status, 'available')


# ═══════════════════════════════════════════════════════════
# G9 / C5, C6
# ═══════════════════════════════════════════════════════════
@tagged('post_install', '-at_install')
class TestBatchExtAndNames(ScheduleCase):

    # ─── KK-C5 ─────────────────────────────────────────
    def test_c5_write_inner_step_error_is_not_swallowed(self):
        """picking_ids yazımı sonrası kalıcı liste adımı hata verirse yutulmaz:
        ya yükseltilir ya da loglanır."""
        batch = self.env['stock.picking.batch'].create({
            'picking_type_id': self.out_type.id, 'name': 'WC-C5-BATCH'})
        self._add_stock(self.prod1, self.stock, 5)
        picking = self._picking(self.prod1, 1)

        batch_cls = type(batch)
        original = batch_cls.write
        calls = {'n': 0}

        def fake_write(rec, vals):
            if 'all_picking_ids' in vals:
                calls['n'] += 1
                if calls['n'] == 1:
                    return True  # picking tarafındaki ekleme atlanır: iç adım yazmak zorunda kalır
                raise ValueError('iç adım hatası')
            return original(rec, vals)

        with patch.object(batch_cls, 'write', fake_write):
            try:
                with self.assertLogs('odoo.addons.ugurlar_barcode', level='WARNING'):
                    batch.write({'picking_ids': [(4, picking.id)]})
            except ValueError:
                pass  # hata yükseltildi (kabul)
        self.assertGreaterEqual(calls['n'], 2, 'ön koşul: iç adım çalışmalı')

    def test_c5_normal_picking_ids_write_keeps_permanent_list(self):
        """Koruma: picking_ids yazımı kalıcı listeye eklenir."""
        batch = self.env['stock.picking.batch'].create({
            'picking_type_id': self.out_type.id, 'name': 'WC-C5-OK'})
        self._add_stock(self.prod1, self.stock, 5)
        picking = self._picking(self.prod1, 1)
        batch.write({'picking_ids': [(4, picking.id)]})
        self.assertIn(picking, batch.all_picking_ids)

    # ─── KK-C6 ─────────────────────────────────────────
    def _names_after(self, existing, new_name):
        sale = self.env['sale.order'].create({'partner_id': self.customer.id})
        if existing:
            sale.picking_batch_names = existing
        self._add_stock(self.prod1, self.stock, 5)
        picking = self._picking(self.prod1, 1, origin=sale.name)
        self.schedule._update_sale_order_batch_names(picking, new_name)
        sale.invalidate_recordset()
        return sale.picking_batch_names

    def test_c6_longer_name_does_not_match_shorter_new_name(self):
        """'R100000' içeren siparişe 'R10000' eklenir (alt dize eşleşmesi olmaz)."""
        self.assertEqual(self._names_after('R100000', 'R10000'), 'R100000, R10000')

    def test_c6_prefix_of_existing_name_is_appended(self):
        self.assertEqual(self._names_after('R10000, R2', 'R1'), 'R10000, R2, R1')

    def test_c6_exact_match_in_list_is_kept_once(self):
        self.assertEqual(self._names_after('R10000, R2', 'R10000'), 'R10000, R2')
        self.assertEqual(self._names_after('R10000, R2', 'R2'), 'R10000, R2')
        self.assertEqual(self._names_after('R10000,R2', 'R2'), 'R10000,R2')

    def test_c6_first_and_additional_names(self):
        """Koruma: boşsa yazılır, farklı rota virgülle eklenir."""
        self.assertEqual(self._names_after('', 'R10000'), 'R10000')
        self.assertEqual(self._names_after('R2', 'R10000'), 'R2, R10000')


# ═══════════════════════════════════════════════════════════
# G10 / C7
# ═══════════════════════════════════════════════════════════
class _LocalDatetime(datetime):
    """Odoo istemci domain değerlendiricisinin `to_utc()` davranışı: kullanıcı saat diliminde
    (İstanbul) yerel zamandan UTC'ye çevirir."""

    def to_utc(self):
        local = IST.localize(datetime(
            self.year, self.month, self.day, self.hour, self.minute, self.second))
        return local.astimezone(pytz.UTC).replace(tzinfo=None)


@tagged('post_install', '-at_install')
class TestCountTodayFilter(BarcodeCase):
    """KK-C7: yerel saat 2026-10-16 01:30 (İstanbul, UTC+3) iken 'Bugün' filtresi."""

    TODAY = date(2026, 10, 16)

    def _filter_domain(self, model, filter_name):
        views = self.env[model].get_views([(False, 'search')])
        node = etree.fromstring(views['views']['search']['arch']).xpath(
            "//filter[@name='%s']" % filter_name)
        self.assertEqual(len(node), 1, 'filtre bulunamadı: %s' % filter_name)
        namespace = SimpleNamespace(
            datetime=_LocalDatetime, time=dt_time, timedelta=timedelta, date=date)
        domain = safe_eval(node[0].get('domain'), {
            'datetime': namespace, 'context_today': lambda: self.TODAY,
            'time': dt_time, 'timedelta': timedelta})
        return domain

    def _session(self, local_day, hour, minute):
        return self.env['ugurlar.barcode.count.session'].create({
            'location_id': self.stock.id,
            'date': _ist_to_utc(local_day, hour, minute),
        })

    def test_c7_today_filter_uses_local_day_boundaries(self):
        today, yesterday, tomorrow = self.TODAY, self.TODAY - timedelta(days=1), self.TODAY + timedelta(days=1)
        early = self._session(today, 0, 30)         # UTC 15.10 21:30 (bugün, yerel)
        late = self._session(today, 23, 30)         # UTC 16.10 20:30 (bugün, yerel)
        prev = self._session(yesterday, 23, 30)     # UTC 15.10 20:30 (dün, yerel)
        nxt = self._session(tomorrow, 0, 30)        # UTC 16.10 21:30 (yarın, yerel)
        domain = self._filter_domain('ugurlar.barcode.count.session', 'today')
        found = self.env['ugurlar.barcode.count.session'].search(
            [('id', 'in', (early | late | prev | nxt).ids)] + domain)
        self.assertEqual(found, early | late,
                         'yerel 00:30 görünmeli, önceki gün 23:30 ve ertesi gün 00:30 görünmemeli')

    def test_c7_route_today_filter_already_converts_to_utc(self):
        """Koruma / değerlendirici doğrulaması: Toplama Listeleri 'Bugün' filtresi aynı kuraldadır."""
        Batch = self.env['stock.picking.batch']
        values = {'early': (self.TODAY, 0, 30), 'prev': (self.TODAY - timedelta(days=1), 23, 30)}
        batches = {}
        for key, (day, hour, minute) in values.items():
            batches[key] = Batch.create({
                'name': 'C7-%s' % key, 'picking_type_id': self.out_type.id,
                'time_window': '10:01-14:00',
                'schedule_time': _ist_to_utc(day, hour, minute)})
        domain = self._filter_domain('stock.picking.batch', 'filter_today')
        found = Batch.search([('id', 'in', [b.id for b in batches.values()])] + domain)
        self.assertEqual(found, batches['early'])
