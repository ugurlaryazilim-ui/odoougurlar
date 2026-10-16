"""Dal F / G18 backend: KK-F1, F2, F3, F4, F8 (küçük düzeltmeler).

K = bugün kırmızı (özellik/düzeltme yok), Y = yeşil koruma (çalışan davranışı sabitler).
"""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from odoo import http as odoo_http
from odoo.tests import tagged
from odoo.tools import file_open

from odoo.addons.ugurlar_barcode.controllers import (
    counting_api, discount_api, operations_api, product_api)
from odoo.addons.ugurlar_barcode.tests.common import BarcodeCase

CTRL = 'ugurlar_barcode/controllers/'


def _src(name):
    with file_open(CTRL + name) as f:
        return f.read()


# ═══ KK-F1, KK-F8: product_api ═════════════════════════════════
@tagged('post_install', '-at_install')
class TestProductSearchF(BarcodeCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # İsimler sıralamayı sabitler (product.product _order: priority, default_code, name, id):
        # 'Alfa' önce gelir. Alfa'nın nebim_barcode değeri aranan dizeyi ALT DİZE olarak taşır.
        cls.sub = cls._new_product('F1 Alfa Alt Dize', 'F1-ALFA-OWN')
        cls.sub.nebim_barcode = 'NB-1234567'
        cls.exact = cls._new_product('F1 Beta Tam Eşleşme', 'F1-BETA-OWN')
        cls.exact.nebim_barcode = 'NB-123,ZZ-9'
        cls.shelf_a = cls._new_shelf('F8-RAF-A', 'F8-A')
        cls.shelf_b = cls._new_shelf('F8-RAF-B', 'F8-B')
        cls.shelf_neg = cls._new_shelf('F8-RAF-NEG', 'F8-N')

    def setUp(self):
        super().setUp()
        self._patch_request(product_api)
        self.ctl = product_api.ProductApiController()

    def _search(self, query, search_type='barcode'):
        return self.ctl.product_search(barcode=query, search_type=search_type)

    # ─── KK-F1 ─────────────────────────────────────────
    def test_f1_exact_nebim_token_found_even_if_substring_product_sorts_first(self):
        """K: 'NB-123', Alfa'nın 'NB-1234567' değerinin alt dizesi; ürün Beta'da virgüllü
        listede TAM eşleşir. `like`+`limit=1` ilk adayı (Alfa) alıp eler, Beta bulunamaz."""
        res = self._search('NB-123')
        self.assertFalse(res.get('error'), res)
        self.assertEqual(res['product']['id'], self.exact.id,
                         'nebim_barcode listesinde tam eşleşen ürün dönmeli (alt dize değil)')

    def test_f1_substring_alone_never_returns_a_product(self):
        """Y: 'NB-12345' yalnız Alfa'nın alt dizesi; hiçbir ürünün tam barkodu değil."""
        res = self._search('NB-12345')
        self.assertTrue(res.get('error'), 'alt dize eşleşmesi ürün döndürmemeli')
        self.assertNotIn('product', res)

    def test_f1_exact_single_nebim_barcode_still_found(self):
        """Y: tek değerli nebim_barcode tam eşleşme."""
        res = self._search('NB-1234567')
        self.assertFalse(res.get('error'), res)
        self.assertEqual(res['product']['id'], self.sub.id)

    def test_f1_second_token_in_list_found(self):
        """Y/K: listedeki ikinci değer de tam eşleşir (Beta, 'ZZ-9')."""
        res = self._search('ZZ-9')
        self.assertFalse(res.get('error'), res)
        self.assertEqual(res['product']['id'], self.exact.id)

    def test_f1_odoo_barcode_has_priority_and_default_code_fallback(self):
        """Y: barcode alanı ve default_code ile arama bozulmaz."""
        res = self._search('F1-BETA-OWN')
        self.assertEqual(res['product']['id'], self.exact.id)
        self.sub.default_code = 'F1-KOD-77'
        res = self._search('F1-KOD-77')
        self.assertEqual(res['product']['id'], self.sub.id)

    # ─── KK-F8: _read_group, davranış aynı ─────────────
    def test_f8_variant_stock_sums_positive_internal_quants_only(self):
        """Y: stok toplamı yalnız iç lokasyon + pozitif quant. `_read_group` geçişinde
        toplam, negatifin dışlanması ve müşteri lokasyonunun dışlanması korunmalı."""
        prod = self._new_product('F8 Stok Ürünü', 'F8-STOK')
        self._add_stock(prod, self.shelf_a, 3)
        self._add_stock(prod, self.shelf_b, 2)
        self._add_stock(prod, self.shelf_neg, -4)
        self._add_stock(prod, self.loc_customers, 7)
        res = self._search('F8-STOK')
        self.assertFalse(res.get('error'), res)
        self.assertEqual(res['total_stock'], 5)
        self.assertEqual([v['stock'] for v in res['variants']], [5])
        self.assertEqual(res['total_all_variants_stock'], 5)
        self.assertEqual(sorted(l['quantity'] for l in res['locations']), [2, 3])

    def test_f8_product_without_stock_has_zero(self):
        """Y: stoksuz ürün 0 döner (grup satırı yok -> sözlükte yok)."""
        self._new_product('F8 Stoksuz', 'F8-ZERO')
        res = self._search('F8-ZERO')
        self.assertEqual(res['total_stock'], 0)
        self.assertEqual([v['stock'] for v in res['variants']], [0])

    def test_f8_product_api_uses_private_read_group(self):
        """K: Odoo 19'da `read_group` kullanımdan kalkmış; `_read_group` kullanılmalı."""
        src = _src('product_api.py')
        self.assertNotRegex(src, r'(?<![_\w])read_group\(',
                            'product_api.py hâlâ eski read_group() çağırıyor')
        self.assertIn('_read_group(', src)

    def test_f1_product_api_uses_shared_find_product(self):
        """K: barkod araması ortak `_find_product` yardımcısını kullanmalı (PROJE.md kuralı)."""
        src = _src('product_api.py')
        self.assertIn('_find_product(', src)
        self.assertNotRegex(src, r"nebim_barcode['\"],\s*['\"]like['\"]",
                            "eski `nebim_barcode like` + limit=1 araması kaldırılmalı")


# ═══ KK-F8: base_api ölü except ═════════════════════════════════
@tagged('post_install', '-at_install')
class TestGetAllPickingsF(BarcodeCase):

    def setUp(self):
        super().setUp()
        self._patch_request()

    def test_f8_dead_except_around_all_picking_ids_removed(self):
        """K: `batch.all_picking_ids` okuması gerçek bir alan; tablo yoksa hata işlemi
        zaten bozar (except kurtaramaz). Ölü try/except kaldırılmalı."""
        src = _src('base_api.py')
        self.assertNotRegex(
            src, r'try:\s*\n\s*pickings\s*=\s*batch\.all_picking_ids',
            '_get_all_pickings içindeki ölü try/except (all_picking_ids) kaldırılmalı')

    def test_f8_returns_persistent_list_including_done_pickings(self):
        """Y: kalıcı liste (batch_id temizlenmiş done picking dahil) önceliklidir."""
        prod = self._new_product('F8 Rota Ürünü', 'F8-ROTA')
        self._add_stock(prod, self.stock, 5)
        p1 = self._picking(prod, 1)
        p2 = self._picking(prod, 1)
        batch = self._route(p1 | p2)
        # Odoo, done picking'in batch_id'sini temizler; ORM yazımı yerine ham SQL ile
        # (kalıcı m2m satırına dokunmadan) aynı durum.
        self.env.flush_all()
        self.env.cr.execute('UPDATE stock_picking SET batch_id = NULL WHERE id = %s', [p1.id])
        p1.invalidate_recordset(['batch_id'])
        batch.invalidate_recordset()
        self.assertFalse(p1.batch_id, 'ön koşul: batch_id temizlendi')
        got = self.api._get_all_pickings(batch)
        self.assertEqual(set(got.ids), {p1.id, p2.id})

    def test_f8_fallback_to_batch_id_fills_persistent_list(self):
        """Y: kalıcı liste boşsa batch_id'li picking'ler bulunur ve liste doldurulur."""
        prod = self._new_product('F8 Fallback', 'F8-FB')
        self._add_stock(prod, self.stock, 5)
        p1 = self._picking(prod, 1)
        batch = self.env['stock.picking.batch'].create({'picking_type_id': self.out_type.id})
        p1.write({'batch_id': batch.id})
        batch.all_picking_ids = [(5, 0, 0)]
        got = self.api._get_all_pickings(batch)
        self.assertEqual(got.ids, p1.ids)
        batch.invalidate_recordset(['all_picking_ids'])
        self.assertEqual(batch.all_picking_ids.ids, p1.ids)


# ═══ KK-F2, KK-F3: operations_api / counting_api ═══════════════
@tagged('post_install', '-at_install')
class TestOperationsF(BarcodeCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod = cls._new_product('F2 Hareket Ürünü', 'F2-MOV')
        cls.shelf_a = cls._new_shelf('F2-RAF-A', 'F2-A')
        cls.shelf_b = cls._new_shelf('F2-RAF-B', 'F2-B')
        cls.shelf_c = cls._new_shelf('F2-RAF-C', 'F2-C')   # yalnız hacim testleri (izole sayım)

    def setUp(self):
        super().setUp()
        self._patch_request(operations_api, counting_api)
        self.ops = operations_api.OperationsApiController()
        self.cnt = counting_api.CountingApiController()

    # ─── yardımcılar ───────────────────────────────────
    def _mobile_shelf_move(self, qty=2):
        """Mobil raf taşıma: picking tipi OLMAYAN iç stok hareketi."""
        self._add_stock(self.prod, self.shelf_a, qty + 1)
        ok, err = self.api._safe_move_quant(self.prod, self.shelf_a, self.shelf_b, qty)
        self.assertTrue(ok, err)
        move = self._done_moves(self.prod, location_dest_id=self.shelf_b)
        self.assertEqual(len(move), 1)
        self.assertFalse(move.picking_type_id, 'ön koşul: mobil hareketin picking tipi yok')
        return move

    def _listed_ids(self, move_type):
        res = self.ops.stock_movements(days=7, move_type=move_type)
        return {m['id'] for m in res['movements']}

    def _op(self, op_type='counting', n=1, loc=None):
        vals = [{'operation_type': op_type, 'barcode': 'OP-%d' % i, 'product_id': self.prod.id,
                 'location_id': (loc or self.shelf_a).id, 'quantity': 1} for i in range(n)]
        return self.env['ugurlar.barcode.operation'].create(vals)

    def _age(self, ops, days):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE ugurlar_barcode_operation SET create_date = now() - (%s || ' days')::interval "
            "WHERE id = ANY(%s)", [str(days), ops.ids])
        ops.invalidate_recordset()

    # ─── KK-F2 ─────────────────────────────────────────
    def test_f2_mobile_shelf_move_listed_under_internal_filter(self):
        """K: picking tipi olmayan mobil raf hareketi 'internal' filtresinde de listelenir."""
        move = self._mobile_shelf_move()
        self.assertIn(move.id, self._listed_ids('all'), 'ön koşul: "all" listesinde var')
        self.assertIn(move.id, self._listed_ids('internal'))

    def test_f2_mobile_shelf_move_not_listed_under_in_or_out(self):
        """Y: mobil raf hareketi Giriş/Çıkış filtresine sızmaz."""
        move = self._mobile_shelf_move()
        self.assertNotIn(move.id, self._listed_ids('in'))
        self.assertNotIn(move.id, self._listed_ids('out'))

    def test_f2_internal_filter_item_has_internal_type(self):
        """K: listelenen mobil hareket 'internal' / 'İç Transfer' etiketiyle döner."""
        move = self._mobile_shelf_move()
        res = self.ops.stock_movements(days=7, move_type='internal')
        item = next((m for m in res['movements'] if m['id'] == move.id), None)
        self.assertIsNotNone(item, 'mobil hareket internal listede yok')
        self.assertEqual(item['move_type'], 'internal')
        self.assertEqual(item['move_type_label'], 'İç Transfer')

    def test_f2_picking_internal_transfer_still_listed(self):
        """Y: iç transfer tipli (picking'li) hareket 'internal' filtresinde kalır."""
        self._add_stock(self.prod, self.stock, 3)
        picking = self._picking(self.prod, 2, picking_type=self.wh.int_type_id,
                                src=self.stock, dest=self.shelf_a)
        picking.move_ids.quantity = 2
        picking.move_ids.picked = True
        picking.with_context(skip_backorder=True)._action_done()
        self.assertEqual(picking.state, 'done')
        self.assertIn(picking.move_ids.id, self._listed_ids('internal'))

    def test_f2_inventory_adjustment_not_listed_under_internal(self):
        """Y (tasarım: kaynak+hedef iç lokasyon): envanter düzeltmesi (iç <-> envanter
        lokasyonu) 'internal' filtresine girmez."""
        self.api._safe_update_quant(self.prod, self.shelf_a, 4, 'F2 test düzeltme')
        adj = self._done_moves(self.prod, location_dest_id=self.shelf_a)
        self.assertEqual(len(adj), 1)
        self.assertNotIn(adj.id, self._listed_ids('internal'))

    # ─── KK-F3: operator_performance ──────────────────
    def test_f3_operator_performance_days_clamped_to_90(self):
        """K: days=365 -> 90."""
        res = self.ops.operator_performance(days=365)
        self.assertEqual(res['period_days'], 90)

    def test_f3_operator_performance_days_lower_bound_is_1(self):
        """K: days=0 ve negatif -> 1."""
        self.assertEqual(self.ops.operator_performance(days=0)['period_days'], 1)
        self.assertEqual(self.ops.operator_performance(days=-5)['period_days'], 1)

    def test_f3_operator_performance_valid_days_unchanged(self):
        """Y: 1-90 arası değerler ve metin gelen değer (select value) olduğu gibi kalır."""
        self.assertEqual(self.ops.operator_performance(days=7)['period_days'], 7)
        self.assertEqual(self.ops.operator_performance(days='30')['period_days'], 30)
        self.assertEqual(self.ops.operator_performance(days=90)['period_days'], 90)

    def test_f3_operator_performance_excludes_ops_older_than_90_days(self):
        """K: 100 gün önceki kayıt days=365 ile bile sayılmaz; 60 gün önceki sayılır."""
        before = self.ops.operator_performance(days=365)['total_operations']
        old = self._op('putaway')
        mid = self._op('putaway')
        self._age(old, 100)
        self._age(mid, 60)
        after = self.ops.operator_performance(days=365)['total_operations']
        # Test DB kalıcı veri içerir: mutlak sayı yerine fark. 90 günlük sınır varsa yalnız
        # 60 günlük kayıt eklenir (+1); sınır yoksa 100 günlük de girer (+2).
        self.assertEqual(after - before, 1)

    def test_f3_operator_performance_total_not_truncated_at_500(self):
        """Y (koruma): özet sayaçları liste değil toplamdır; limit=500 ile sessizce kesilmemeli
        (500'den fazla işlem olan yoğun haftada 'Toplam İşlem' yanlış çıkardı)."""
        before = self.ops.operator_performance(days=7)
        self._op('putaway', n=520)
        res = self.ops.operator_performance(days=7)
        self.assertEqual(res['total_operations'] - before['total_operations'], 520)
        self.assertEqual(sum(o['total'] for o in res['operators'])
                         - sum(o['total'] for o in before['operators']), 520)

    # ─── KK-F3: count_list ────────────────────────────
    def test_f3_count_list_days_clamped_to_90(self):
        """K: 100 gün önceki sayım days=365 ile listelenmez; 60 gün önceki listelenir."""
        old = self._op('counting', loc=self.shelf_a)
        mid = self._op('counting', loc=self.shelf_b)
        self._age(old, 100)
        self._age(mid, 60)
        res = self.cnt.count_list(days=365)
        locs = {c['location_id'] for c in res['counts']}
        self.assertIn(self.shelf_b.id, locs, 'ön koşul: 60 günlük sayım görünür')
        self.assertNotIn(self.shelf_a.id, locs, '100 günlük sayım 90 gün sınırının dışında')

    def test_f3_count_list_valid_days_unchanged(self):
        """Y: days=30 (varsayılan) 60 günlük sayımı getirmez, 10 günlüğü getirir."""
        ten = self._op('counting', loc=self.shelf_a)
        sixty = self._op('counting', loc=self.shelf_b)
        self._age(ten, 10)
        self._age(sixty, 60)
        locs = {c['location_id'] for c in self.cnt.count_list()['counts']}
        self.assertIn(self.shelf_a.id, locs)
        self.assertNotIn(self.shelf_b.id, locs)

    def test_f3_count_list_query_has_limit_500(self):
        """K: 520 sayım kaydı varken en çok 500 satır okunur (en yeniler)."""
        self._op('counting', n=520, loc=self.shelf_c)
        res = self.cnt.count_list(days=7)
        # Aynı raf + aynı dakika tek sayım olarak gruplanır; en yeni 500 kayıt okunur.
        total_items = sum(c['product_count'] for c in res['counts']
                          if c['location_id'] == self.shelf_c.id)
        self.assertEqual(total_items, 500)

    def test_f3_count_list_small_set_unaffected(self):
        """Y: az kayıtta tümü döner."""
        self._op('counting', n=3, loc=self.shelf_c)
        res = self.cnt.count_list(days=7)
        self.assertEqual(sum(c['product_count'] for c in res['counts']
                             if c['location_id'] == self.shelf_c.id), 3)


# ═══ KK-F4: discount_api ═══════════════════════════════════════
@tagged('post_install', '-at_install')
class TestDiscountNebimErrorF(BarcodeCase):

    BASKET = [{'barcode': 'F4-BC-1', 'quantity': 1}]

    def setUp(self):
        super().setUp()
        self._patch_request(discount_api)
        # `_error_text` beklenmeyen hatada `_()` çağırır; çeviri dili `odoo.http.request.env`
        # üzerinden bulunur. Gerçek istek yok -> aynı sahte isteği oraya da tak (aksi halde
        # çeviri katmanı AttributeError verir ve test yanlış nedenle kırılır).
        p = patch.object(odoo_http, 'request', SimpleNamespace(env=self.env))
        p.start()
        self.addCleanup(p.stop)
        self.ctl = discount_api.DiscountApiController()

    @contextmanager
    def _proc(self, *, result=None, exc=None):
        """Nebim connector `run_proc` taklidi: sonuç döner ya da istisna fırlatır."""
        def fake(conn, proc_name, params=None):
            if exc is not None:
                raise exc
            return result
        cls = type(self.env['odoougurlar.nebim.connector'])
        with patch.object(cls, 'run_proc', fake):
            yield

    def _row(self):
        return {'Barcode': 'F4-BC-1', 'Quantity': 1, 'RetailPrice': 100.0,
                'DiscountAmount': 10.0, 'FinalLineTotal': 90.0}

    # ─── nebim_error ───────────────────────────────────
    def test_f4_connector_exception_returns_nebim_error_field(self):
        """K: Nebim'e ulaşılamazsa yanıtta ayrı `nebim_error` alanı döner, başarı değildir."""
        with self._proc(exc=ConnectionError('Nebim down')):
            res = self.ctl.calculate_discounts(basket=self.BASKET)
        self.assertTrue(res.get('nebim_error'), res)
        self.assertFalse(res.get('success'))
        self.assertNotIn('lines', res)

    def test_f4_nebim_exception_message_returned_as_nebim_error(self):
        """K: Nebim'in kendi hatası (ExceptionMessage) de `nebim_error` olarak döner."""
        with self._proc(result={'ExceptionMessage': 'SP bulunamadı'}):
            res = self.ctl.calculate_discounts(basket=self.BASKET)
        self.assertTrue(res.get('nebim_error'), res)
        self.assertFalse(res.get('success'))

    def test_f4_nebim_error_does_not_leak_internals(self):
        """Y: istemciye bağlantı ayrıntısı (host, şifre) sızmaz."""
        with self._proc(exc=ConnectionError('tcp://10.1.2.3:1433 pwd=SECRET123')):
            res = self.ctl.calculate_discounts(basket=self.BASKET)
        self.assertNotIn('SECRET123', str(res))
        self.assertNotIn('10.1.2.3', str(res))

    def test_f4_empty_basket_is_plain_error_not_nebim_error(self):
        """Y: Nebim'le ilgisiz hata `nebim_error` almaz."""
        res = self.ctl.calculate_discounts(basket=[])
        self.assertTrue(res.get('error'))
        self.assertFalse(res.get('nebim_error'))

    def test_f4_success_has_no_nebim_error(self):
        """Y: başarılı hesaplama değişmez."""
        with self._proc(result=[self._row()]):
            res = self.ctl.calculate_discounts(basket=self.BASKET)
        self.assertTrue(res.get('success'), res)
        self.assertFalse(res.get('nebim_error'))
        self.assertEqual(len(res['lines']), 1)
        self.assertEqual(res['summary']['total_final'], 90.0)

    # ─── search_customer: yutulan hata ────────────────
    def test_f4_search_customer_failure_reports_nebim_error(self):
        """K: arama Nebim hatasında boş liste ile 'sonuç yok' arasında fark yok; ayrı alan."""
        with self._proc(exc=ConnectionError('Nebim down')):
            res = self.ctl.search_customer(query='ahmet')
        self.assertTrue(res.get('nebim_error'), res)
        self.assertEqual(res.get('customers'), [])

    def test_f4_search_customer_success_and_short_query_unchanged(self):
        """Y."""
        rows = [{'name': 'Ahmet Y.', 'phone': '555', 'customer_code': 'C1'}]
        with self._proc(result=rows):
            res = self.ctl.search_customer(query='ahmet')
        self.assertEqual(res['customers'][0]['customer_code'], 'C1')
        self.assertFalse(res.get('nebim_error'))
        self.assertEqual(self.ctl.search_customer(query='ab'), {'customers': []})
