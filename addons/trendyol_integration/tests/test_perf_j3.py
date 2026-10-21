from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


class CargoApi:
    """Kargo faturası kalem servisi: hangi seri numaraları sorulduğunu kaydeder."""

    def __init__(self):
        self.asked = []

    def get_cargo_invoice_items(self, serial, page=0):
        self.asked.append(serial)
        return {'success': True, 'data': {'content': [], 'totalPages': 1}}


@tagged('post_install', '-at_install', 'trendyol_integration')
class TestTrendyolPerfJ3(TransactionCase):
    """TODO-24/25: finans cron'u sınırlı + toplu sorgu, İşlem Kontrol penceresi, sipariş cron'u paket başına
    commit, paket araması indeksli."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.S = cls.env['trendyol.settlement']
        cls.TO = cls.env['trendyol.order']
        cls.store = cls.env['trendyol.store'].create({
            'name': 'TY J3', 'api_key': 'k', 'api_secret': 's', 'seller_id': '9931',
        })

    def _order(self, number, package):
        return self.TO.create({'store_id': self.store.id, 'trendyol_order_number': number,
                               'shipment_package_id': package})

    def _settle(self, tid, days_ago, **kw):
        vals = {'trendyol_id': tid, 'store_id': self.store.id, 'source': 'settlements',
                'transaction_type': 'sale', 'credit': 100.0, 'debt': 0.0,
                'transaction_date': fields.Datetime.now() - timedelta(days=days_ago)}
        vals.update(kw)
        return self.S.create(vals)

    # ── KK-1: finans ──────────────────────────────────────────

    def test_relink_window_limit_and_full(self):
        order_new = self._order('J3-N', 'J3-NP')
        order_old = self._order('J3-O', 'J3-OP')
        recent = self._settle('j3r', 2, order_number='J3-N')
        old = self._settle('j3o', 90, order_number='J3-O')
        self.S._relink_unlinked_settlements(self.store)
        self.assertEqual(recent.order_id, order_new)
        self.assertFalse(old.order_id, "30 günden eski bağsız kayıt cron'da denenmez")
        self.S._relink_unlinked_settlements(self.store, full=True)
        self.assertEqual(old.order_id, order_old, "geçmişi tamamla tüm bağsız kayıtları tarar")

    def test_relink_batch_limit_takes_newest(self):
        o1, o2 = self._order('J3-A', 'J3-AP'), self._order('J3-B', 'J3-BP')
        older = self._settle('j3a', 5, order_number='J3-A')
        newer = self._settle('j3b', 1, order_number='J3-B')
        with patch.object(type(self.S), '_RELINK_LIMIT', 1):
            self.S._relink_unlinked_settlements(self.store)
        self.assertEqual(newer.order_id, o2)
        self.assertFalse(older.order_id)
        self.S._relink_unlinked_settlements(self.store)
        self.assertEqual(older.order_id, o1)

    def test_find_order_cache_matches_single_lookup(self):
        """Toplu önbellek tek tek aramayla aynı sonucu verir: önce paket, sonra sipariş no."""
        a = self._order('J3-X', 'J3-XP')
        self._order('J3-Y', 'J3-YP')
        cases = [('J3-XP', 'J3-Y'), ('', 'J3-Y'), ('J3-NOPE', 'J3-X'), ('J3-NOPE', 'J3-NOPE'), ('', '')]
        cache = self.S._order_cache(self.store, set(cases))
        for pkg, num in cases:
            self.assertEqual(self.S._find_order(self.store, pkg, num, cache=cache),
                             self.S._find_order(self.store, pkg, num), (pkg, num))
        self.assertEqual(self.S._find_order(self.store, 'J3-XP', 'J3-Y', cache=cache), a.id)

    def test_settlement_page_query_count_is_constant(self):
        """Değişmeyen kayıtlar için sayfa maliyeti öğe sayısına bağlı değil (öğe başına 3 sorgu yoktu)."""
        self._order('J3-Q', 'J3-QP')

        def items(n):
            return [{'id': f'q{i}', 'transactionType': 'Satış', 'credit': 5.0, 'debt': 0.0,
                     'orderNumber': 'J3-Q', 'shipmentPackageId': 'J3-QP', 'transactionDate': 1788385121995}
                    for i in range(n)]

        self.assertEqual(self.S._process_settlement_page(items(40), self.store, 'settlements'), 40)
        self.env.flush_all()
        cr = self.env.cr

        def cost(n):
            self.env.invalidate_all()
            before = cr.sql_log_count
            self.assertEqual(self.S._process_settlement_page(items(n), self.store, 'settlements'), 0)
            return cr.sql_log_count - before

        self.assertEqual(cost(5), cost(40))
        rec = self.S.search([('trendyol_id', '=', 'q3'), ('store_id', '=', self.store.id)])
        self.assertTrue(rec.order_id, "sayfa yolunda sipariş yine bağlanır")

    def test_cargo_invoices_only_recent_unprocessed_in_cron(self):
        def inv(tid, days_ago):
            return self._settle(tid, days_ago, source='otherfinancials', transaction_type='shipping_cargo')
        inv('c-recent', 3)             # yeni, işlenmemiş → sorulur
        inv('c-mid', 30)               # 60 günden yeni, işlenmemiş → sorulur
        inv('c-old', 100)              # eski, kalemi hiç dönmemiş → cron denemez
        inv('c-done-old', 100)
        inv('c-done-recent', 2)
        for serial in ('c-done-old', 'c-done-recent'):
            self._settle(f'cargo_{serial}_1', 1, source='cargo_invoice', transaction_type='shipping_cargo',
                         receipt_id=serial)
        api = CargoApi()
        self.S._process_cargo_invoices(api, self.store, recent_only=True)
        # işlenmiş ama son 7 gün içindeki fatura yine kontrol edilir; eski işlenmiş/eski boş atlanır
        self.assertEqual(sorted(api.asked), ['c-done-recent', 'c-mid', 'c-recent'])

        api = CargoApi()
        self.S._process_cargo_invoices(api, self.store, recent_only=False)
        # geçmişi tamamla: yalnız işlenmemişler (eski dahil)
        self.assertEqual(sorted(api.asked), ['c-mid', 'c-old', 'c-recent'])

    # ── KK-2: İşlem Kontrol ───────────────────────────────────

    def test_transaction_check_limited_to_recent_orders(self):
        self._settle('t-new', 5, order_number='J3-T-NEW')
        self._settle('t-old', 400, order_number='J3-T-OLD')
        # eski siparişin yeni hareketi: siparişin TÜM hareketleri toplanır
        self._settle('t-mix-old', 400, order_number='J3-T-MIX', credit=70.0)
        self._settle('t-mix-new', 3, order_number='J3-T-MIX', credit=30.0)
        self.env.flush_all()
        Check = self.env['trendyol.transaction.check']
        found = {r.order_number: r for r in Check.search([('store_id', '=', self.store.id)])}
        self.assertIn('J3-T-NEW', found)
        self.assertNotIn('J3-T-OLD', found)
        self.assertAlmostEqual(found['J3-T-MIX'].sale_amount, 100.0)

    # ── KK-3: sipariş cron'u ──────────────────────────────────

    def _pkgs(self, n):
        return [{'id': 9000 + i, 'orderNumber': f'J3-P{i}', 'status': 'Created'} for i in range(n)]

    def test_package_batch_commits_per_package_in_cron_only(self):
        counters = {'created': 0, 'updated': 0, 'errors': 0}
        errors = []

        def one(self_, package, store, cutoff):
            if package['id'] == 9001:
                raise ValueError('bozuk paket')
            return 'created'

        with patch.object(type(self.TO), '_sync_one_package', one), \
                patch.object(self.env.cr, 'commit') as commit:
            self.TO.with_context(ty_commit_per_package=True)._process_package_batch(
                self._pkgs(3), self.store, fields.Datetime.now(), counters, errors)
            self.assertEqual(commit.call_count, 2, "yalnız başarılı paketler commit edilir")
            self.assertEqual((counters['created'], counters['errors']), (2, 1))
            commit.reset_mock()
            self.TO._process_package_batch(self._pkgs(3), self.store, fields.Datetime.now(), counters, errors)
            self.assertEqual(commit.call_count, 0, "elle senkron tek işlemde kalır")

    def test_cron_runs_commit_mode_with_separate_lock_cursor(self):
        seen = {}

        def locked(self_, store):
            seen['ctx'] = self_.env.context.get('ty_commit_per_package')
            return {'created': 0, 'updated': 0, 'errors': 0}

        with patch.object(type(self.TO), '_sync_orders_locked', locked), \
                patch.object(type(self.TO), 'sync_orders_from_trendyol',
                             lambda s, commit=False: seen.setdefault('commit', commit)):
            self.TO.cron_sync_trendyol_orders()
        self.assertTrue(seen['commit'])

        with patch.object(type(self.TO), '_sync_orders_locked', locked):
            self.TO.sync_orders_for_store(self.store, commit=True)
            self.assertTrue(seen['ctx'])
            seen.clear()
            self.TO.sync_orders_for_store(self.store)
            self.assertFalse(seen['ctx'])

    def test_busy_lock_skips_sync_in_commit_mode(self):
        lock_cr = MagicMock()
        lock_cr.fetchone.return_value = (False,)
        cm = MagicMock()
        cm.__enter__.return_value = lock_cr
        body = MagicMock()
        with patch.object(type(self.TO.pool), 'cursor', return_value=cm), \
                patch.object(type(self.TO), '_sync_orders_locked', body):
            res = self.TO.sync_orders_for_store(self.store, commit=True)
        self.assertTrue(res.get('busy'))
        body.assert_not_called()

    # ── KK-4: paket araması ───────────────────────────────────

    def test_split_package_lookup_indexed(self):
        self.assertEqual(self.TO._fields['split_package_ids'].index, 'trigram')
        if self.registry.has_trigram:
            self.env.cr.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'trendyol_order' "
                                "AND indexdef ILIKE %s", ['%split_package_ids%'])
            defs = [r[0] for r in self.env.cr.fetchall()]
            self.assertTrue(any('gin_trgm_ops' in d for d in defs), f"GIN trigram indeksi yok: {defs}")
        head = self._order('J3-S', 'J3-SP')
        head.split_package_ids = ',J3-SP,J3-S2,'
        self.assertEqual(self.TO._find_existing_package('J3-S2', 'J3-S', self.store), head)
        self.assertFalse(self.TO._find_existing_package('J3-S9', '', self.store))
