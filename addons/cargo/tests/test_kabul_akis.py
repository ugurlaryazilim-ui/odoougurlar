# -*- coding: utf-8 -*-
"""KABUL: gonder / uzlastir / iptal akisi (KK-6, KK-9, KK-10, KK-11, KK-12, KK-23, KK-24) - sahte saglayici ile.

Yesile donecegi gorev: G4 (akis + eszamanlilik). KK-12 GERCEK eszamanlilik sinifi (TestKabulEszamanlilik) ayri
imleclerle COMMIT'li veri kullanir ve kendi verisini SQL ile siler (DERSLER: Barrier + is parcasi basina imlec).
"""
import base64
import threading
from unittest.mock import patch

from odoo import SUPERUSER_ID, api, sql_db
from odoo.exceptions import UserError
from odoo.tests import tagged

from .kabul_taban import CargoKabulCase, make_label_png


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulGonderim(CargoKabulCase):

    def test_basarili_gonderim(self):
        """KK-6: created, takip no, tek saglayici cagrisi, paket sayisi kadar PNG eki, PDF eki, chatter."""
        shipment = self.mk(package_count=2)
        shipment.action_send()
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(self.provider.count('send'), 1)
        ref = shipment.tracking_ref
        self.assertRegex(ref or '', r'^1ZKABUL\d{7}$')
        self.assertTrue(shipment.sent_at)
        self.assertFalse(shipment.error_code)
        self.assertFalse(shipment.label_missing)
        self.assertTrue(shipment.test_mode)
        pngs = self.attachments(shipment, 'image/png')
        self.assertEqual(sorted(pngs.mapped('name')),
                         sorted('%s-%d.png' % (shipment.name, i) for i in (1, 2)), 'PNG ekleri <name>-<n>.png')
        by_name = {a.name: a for a in pngs}
        for index in (1, 2):
            data = base64.b64decode(by_name['%s-%d.png' % (shipment.name, index)].datas)
            self.assertEqual(data, make_label_png(index - 1), 'PNG saglayicidan geldigi gibi (yeniden kodlanmadan) saklanmali')
        self.assertTrue(shipment.label_pdf_id)
        self.assertEqual(shipment.label_pdf_id.mimetype, 'application/pdf')
        self.assertEqual(shipment.label_pdf_id.res_model, 'cargo.shipment')
        self.assertEqual(shipment.label_pdf_id.res_id, shipment.id)
        chat = self.chatter(shipment)
        self.assertRegex(chat, r'(?i)olu[sş]turuldu')
        self.assertIn(ref, chat)

    def test_saglayici_kayit_verisini_gorur(self):
        shipment = self.mk(cod_amount=250.0, cod_method='cash', origin_ref='SIP-77', invoice_no='F-1')
        shipment.action_send()
        call = self.provider.of('send')[0]
        self.assertEqual((call['recipient_phone'], call['recipient_district'], call['state_code']),
                         ('05321234567', 'Cankaya', '06'))
        self.assertEqual(call['area_code'], self.area_cankaya.area_code)
        self.assertEqual((call['origin_ref'], call['invoice_no']), ('SIP-77', 'F-1'))
        self.assertEqual(call['carrier_id'], self.carrier.id)
        self.assertTrue(call['test_mode'])

    def test_ikinci_gonder_reddedilir(self):
        """KK-12 (seri): created gonderi tekrar gonderilemez, saglayici cagri sayisi 1 kalir."""
        shipment = self.sent()
        self.assert_user_error(shipment.action_send, r'(?i)zaten|oluşturuldu')
        self.assertEqual(self.provider.count('send'), 1)
        self.assertEqual(shipment.state, 'created')

    def test_gonderilemeyen_durumlar(self):
        for state in ('created', 'uncertain', 'cancelled', 'in_transit', 'out_for_delivery', 'delivered', 'returned'):
            with self.subTest(state=state):
                shipment = self.mk()
                shipment.sudo().write({'state': state})
                self.assert_user_error(shipment.action_send)
                self.assertEqual(shipment.state, state)
        sending = self.mk()
        sending.sudo().write({'state': 'sending'})
        self.assert_user_error(sending.action_send, r'(?i)zaten')
        self.no_provider_calls()

    def test_hata_yaniti_failed(self):
        """KK-9: ErrorCode != 0 -> failed; kod + mesaj kayitta ve chatter'da."""
        self.provider.plan['send'] = self.provider.err_send('9001', 'Alici adresi hatali')
        shipment = self.mk()
        shipment.action_send()
        self.assertEqual(shipment.state, 'failed')
        self.assertEqual(shipment.error_code, '9001')
        self.assertIn('Alici adresi hatali', shipment.error_message)
        self.assertFalse(shipment.tracking_ref)
        chat = self.chatter(shipment)
        self.assertIn('9001', chat)
        self.assertIn('Alici adresi hatali', chat)
        self.assertFalse(self.attachments(shipment, 'image/png'))

    def test_failed_yeniden_gonder(self):
        self.provider.plan['send'] = [self.provider.err_send(), lambda s: self.provider.ok_send(shipment=s)]
        shipment = self.mk()
        shipment.action_send()
        self.assertEqual(shipment.state, 'failed')
        shipment.action_send()
        self.assertEqual(shipment.state, 'created')
        self.assertFalse(shipment.error_code)
        self.assertEqual(self.provider.count('send'), 2)

    def test_belirsiz_yanit_uncertain(self):
        """KK-10: zaman asimi -> uncertain; otomatik yeniden gonderim yok; elle 'Gonder' de reddedilir."""
        self.provider.plan['send'] = self.provider.uncertain_send('Okuma zaman asimi')
        shipment = self.mk()
        shipment.action_send()
        self.assertEqual(shipment.state, 'uncertain')
        self.assertEqual(self.provider.count('send'), 1)
        self.assert_user_error(shipment.action_send)
        self.assertEqual(self.provider.count('send'), 1, 'belirsiz gonderi otomatik/elle yeniden gonderilmez')
        self.assertEqual(shipment.state, 'uncertain')

    def test_saglayici_istisnasi_uncertain(self):
        """Saglayici istisna firlatirsa: durum uncertain, istisna kullaniciya sizmaz (saglayicidan sonra raise yok)."""
        self.provider.plan['send'] = RuntimeError('ag koptu')
        shipment = self.mk()
        shipment.action_send()
        self.assertEqual(shipment.state, 'uncertain')
        self.assertEqual(self.provider.count('send'), 1)
        self.assertTrue(shipment.sent_at)

    def test_yan_is_hatasi_created_durumunu_bozmaz(self):
        """Saglayici ok dondukten sonra chatter hatasi created durumunu geri almaz (UPS'te kargo olusmus!)."""
        shipment = self.mk()
        original = type(shipment).message_post

        def flaky(this, *args, **kwargs):
            if self.provider.count('send'):          # yalniz saglayici cagrisindan SONRA coker
                raise RuntimeError('chatter coktu')
            return original(this, *args, **kwargs)
        with patch.object(type(shipment), 'message_post', flaky):
            shipment.action_send()
        self.assertEqual(shipment.state, 'created')
        self.assertTrue(shipment.tracking_ref)
        self.assertEqual(self.provider.count('send'), 1)

    def test_bozuk_etiket_created_durumunu_bozmaz(self):
        self.provider.plan['send'] = lambda s: dict(self.provider.ok_send(shipment=s), labels=[b'bu png degil'])
        shipment = self.mk()
        shipment.action_send()
        self.assertEqual(shipment.state, 'created')
        self.assertTrue(shipment.tracking_ref)

    def test_etiketsiz_ok_label_missing(self):
        self.provider.plan['send'] = lambda s: dict(self.provider.ok_send(shipment=s), labels=[])
        shipment = self.mk()
        shipment.action_send()
        self.assertEqual(shipment.state, 'created')
        self.assertTrue(shipment.label_missing)
        self.assertFalse(self.attachments(shipment, 'image/png'))

    def test_kullanici_yetkisi(self):
        shipment = self.mk()
        for user in (self.plain, self.plain_sales):
            with self.assertRaises(UserError, msg=user.login):
                shipment.with_user(user).action_send()
        self.no_provider_calls()
        self.assertEqual(shipment.state, 'draft')

    # -- KK-11
    def test_sending_commit_saglayiciden_once(self):
        """KK-11: saglayiciya gitmeden once 'sending' + sent_at + benzersiz ad (<=40) commit edilmis olmali."""
        shipment = self.mk()
        shipment.action_send()
        events = self.timeline
        sent_index = next(i for i, e in enumerate(events) if e[:2] == ('provider', 'send'))
        commits_before = [e for e in events[:sent_index] if e[0] == 'commit']
        self.assertTrue(commits_before, 'saglayici cagrisindan once commit yapilmali')
        state, sent_at, name = commits_before[-1][1][shipment.id]
        self.assertEqual(state, 'sending', 'saglayiciya gitmeden hemen onceki commit anlik goruntusu')
        self.assertTrue(sent_at)
        self.assertLessEqual(len(name), 40)
        self.assertRegex(name, r'^KRG/\d{4}/')
        call = self.provider.of('send')[0]
        self.assertEqual(call['state'], 'sending', 'saglayici cagrisi sirasinda SQL durumu sending')
        self.assertTrue(call['sent_at'])
        final_commits = [e for e in events[sent_index + 1:] if e[0] == 'commit']
        self.assertTrue(final_commits, 'saglayici sonucundan sonra da commit (nihai durum) yapilmali')
        self.assertEqual(final_commits[-1][1][shipment.id][0], 'created')

    def test_sending_commit_hata_ve_belirsizde_de(self):
        for plan, final in ((self.provider.err_send(), 'failed'), (self.provider.uncertain_send(), 'uncertain')):
            with self.subTest(final=final):
                del self.timeline[:]
                self.provider.plan['send'] = plan
                shipment = self.mk()
                shipment.action_send()
                sent_index = next(i for i, e in enumerate(self.timeline) if e[:2] == ('provider', 'send'))
                before = [e for e in self.timeline[:sent_index] if e[0] == 'commit']
                self.assertEqual(before[-1][1][shipment.id][0], 'sending')
                after = [e for e in self.timeline[sent_index + 1:] if e[0] == 'commit']
                self.assertEqual(after[-1][1][shipment.id][0], final)

    def test_dogrulama_hatasinda_commit_yok(self):
        """On-dogrulama hatasinda 'sending' commit EDILMEZ (kayit takili kalmamali)."""
        shipment, error = self.try_call(lambda: self.mk(recipient_phone='123'))
        if error is None:
            _, error = self.try_call(shipment.action_send)
            self.assertEqual(shipment.state, 'draft')
            self.assertFalse(shipment.sent_at)
        self.assertIsNotNone(error)
        self.assertEqual([e for e in self.timeline if e[0] == 'commit'], [])


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulUzlastir(CargoKabulCase):
    """KK-10: belirsiz gonderi uzlastirma."""

    def uncertain(self, minutes_ago=20):
        self.provider.plan['send'] = self.provider.uncertain_send()
        shipment = self.mk()
        shipment.action_send()
        self.assertEqual(shipment.state, 'uncertain')
        shipment.sudo().write({'sent_at': self.minutes_ago(minutes_ago)})
        return shipment

    def test_bulundu_created(self):
        shipment = self.uncertain()
        self.provider.plan['find'] = self.provider.found('1ZBULUNDU0001')
        shipment.action_reconcile()
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(shipment.tracking_ref, '1ZBULUNDU0001')
        self.assertTrue(shipment.label_missing, 'uzlastirmada etiket gelmez: label_missing')
        self.assertEqual(self.provider.count('find'), 1)
        self.assertEqual(self.provider.count('send'), 1, 'uzlastirma yeniden gonderim yapmaz')
        self.assertIn('1ZBULUNDU0001', self.chatter(shipment))
        self.assert_user_error(shipment.action_print_label, r'(?i)etiket')

    def test_birden_cok_kayit_uyari(self):
        shipment = self.uncertain()
        self.provider.plan['find'] = self.provider.found('1ZBULUNDU0002', count=2)
        shipment.action_reconcile()
        self.assertEqual(shipment.state, 'created')
        self.assertRegex(self.chatter(shipment), r'(?i)(birden|\b2\b)')

    def test_bulunamadi_genc_beklenir(self):
        """sent_at 15 dk'dan gencse 'bulunamadi' kesin degildir: durum uncertain kalir."""
        shipment = self.uncertain(minutes_ago=14)
        self.provider.plan['find'] = self.provider.not_found()
        self.try_call(shipment.action_reconcile)
        self.assertEqual(shipment.state, 'uncertain')
        self.assertEqual(self.provider.count('send'), 1)

    def test_bulunamadi_eski_failed_ve_yeniden_gonder(self):
        shipment = self.uncertain(minutes_ago=16)
        self.provider.plan['find'] = self.provider.not_found()
        shipment.action_reconcile()
        self.assertEqual(shipment.state, 'failed')
        self.provider.plan['send'] = lambda s: self.provider.ok_send(shipment=s)
        shipment.action_send()
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(self.provider.count('send'), 2)

    def test_sorgu_hatasi_uncertain_kalir(self):
        shipment = self.uncertain()
        self.provider.plan['find'] = self.provider.find_error('Sorgu servisi yanit vermiyor')
        self.try_call(shipment.action_reconcile)
        self.assertEqual(shipment.state, 'uncertain')

    def test_yalniz_belirsiz_uzlastirilir(self):
        draft = self.mk()
        created = self.sent()
        for shipment in (draft, created):
            self.assert_user_error(shipment.action_reconcile)
        self.assertEqual(self.provider.count('find'), 0)

    def test_yetkisiz_kullanici(self):
        shipment = self.uncertain()
        with self.assertRaises(UserError):
            shipment.with_user(self.plain).action_reconcile()


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulIptal(CargoKabulCase):

    def test_iptal_basarili(self):
        """KK-23."""
        shipment = self.sent()
        shipment.action_cancel()
        self.assertEqual(shipment.state, 'cancelled')
        self.assertTrue(shipment.cancelled_at)
        self.assertEqual(self.provider.count('cancel'), 1)
        self.assertIn(shipment.tracking_ref, self.chatter(shipment))

    def test_iptal_hata_durum_degismez(self):
        shipment = self.sent()
        self.provider.plan['cancel'] = {'status': 'error', 'error_code': '7', 'error_message': 'Iptal edilemedi'}
        shipment.action_cancel()
        self.assertEqual(shipment.state, 'created')
        self.assertFalse(shipment.cancelled_at)
        self.assertIn('Iptal edilemedi', self.chatter(shipment))

    def test_iptal_belirsiz_durum_degismez(self):
        shipment = self.sent()
        self.provider.plan['cancel'] = {'status': 'uncertain', 'error_code': '', 'error_message': 'zaman asimi'}
        self.try_call(shipment.action_cancel)
        self.assertEqual(shipment.state, 'created')
        self.assertFalse(shipment.cancelled_at)

    def test_iptal_edilen_yeniden_iptal_edilemez(self):
        shipment = self.sent()
        shipment.action_cancel()
        before = self.provider.count('cancel')
        self.assert_user_error(shipment.action_cancel)
        self.assertEqual(self.provider.count('cancel'), before)

    def test_taslakta_iptal_yok(self):
        shipment = self.mk()
        self.assert_user_error(shipment.action_cancel)
        self.assertEqual(self.provider.count('cancel'), 0)

    def test_kargoya_verilmis_iptal_edilemez(self):
        """KK-24."""
        for state in ('in_transit', 'out_for_delivery', 'delivered', 'returned'):
            with self.subTest(state=state):
                shipment = self.sent()
                shipment.sudo().write({'state': state})
                self.assert_user_error(shipment.action_cancel, r'Kargoya verilmiş gönderi iptal edilemez')
                self.assertEqual(shipment.state, state)
        self.assertEqual(self.provider.count('cancel'), 0, 'dis cagri yapilmamali')

    def test_yetkisiz_iptal(self):
        shipment = self.sent()
        with self.assertRaises(UserError):
            shipment.with_user(self.plain).action_cancel()
        self.assertEqual(self.provider.count('cancel'), 0)

    def test_iptalden_sonra_ayni_referansla_yeni_gonderi(self):
        shipment = self.sent(origin_ref='SIP-IPTAL')
        shipment.action_cancel()
        again = self.sent(origin_ref='SIP-IPTAL')
        self.assertNotEqual(again, shipment)
        self.assertEqual(again.state, 'created')


# ---------------------------------------------------------------------------------------------
# KK-12: GERCEK eszamanlilik (commit'li veri + ayri imecler)
# ---------------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul', 'cargo_esz')
class TestKabulEszamanlilik(CargoKabulCase):
    """Iki oturum ayni gonderiyi ayni anda gonderirse saglayiciya en fazla 1 CreateShipment gider.

    NEDEN ayri imec: test kipinde registry.cursor() ana islemi paylasir; gercek yarisma icin sql_db.db_connect
    ile yeni baglanti acilir. _cargo_commit YAMALANMAZ (gercek commit gerekir). Kendi verisini SQL ile temizler.
    """
    FAKE_COMMIT = False

    @classmethod
    def _kur(cls):
        # NEDEN (G4, T1): taban _kur sinif isleminde res.company adini yazar; benzersiz indeksli satir kilidi
        # (tuple res_company) ayri baglantidaki INSERT'in FK denetimini (FOR KEY SHARE) sonsuza dek bekletir.
        # Bu sinif yalniz prepare()'in commit'li verisini kullanir.
        pass

    def setUp(self):
        super().setUp()
        self.committed = {'shipments': [], 'areas': [], 'carriers': []}
        self.admin_id = self.env.ref('base.user_admin').id
        self.group_id = self.env.ref('cargo.group_cargo_user').id
        self.purge_leftovers()
        self.addCleanup(self.purge)
        self.prepare()
        # NEDEN (G4, T2): ayri baglanti commit'li sirketi gorur (adres/ilce bos olabilir); gonderici ilcesi
        # prepare()'in commit'li alanina baglanir, sirket satirina dokunulmaz.
        area_id = self.committed['areas'][0]
        patcher = patch.object(type(self.env['cargo.shipment']), '_cargo_sender_area',
                               lambda shipment: shipment.env['cargo.area'].browse(area_id))
        patcher.start()
        self.addCleanup(patcher.stop)

    def real_cursor(self):
        cr = sql_db.db_connect(self.env.cr.dbname).cursor()
        # NEDEN (G4, T3): kilit sorunu testi sonsuza dek takmasin; hata verir ve purge yine calisir.
        cr.execute("SET lock_timeout = '10s'")
        # NEDEN (G4, T4): Environment, islemi olmayan imlecte Registry(dbname) cagirir; --stop-after-init test
        # kosusunda ana is parcacigi Registry._lock'u tum testler boyunca tutar (server.run) ve yan is
        # parcacigi orada sonsuza dek bekler. Islem nesnesi onceden verilince kilide gidilmez.
        cr.transaction = type(self.env.transaction)(self.registry)
        return cr

    def purge_leftovers(self):
        """(G4, T3) Yarida kesilmis eski kosularin commit'li artiklari (purge calismadan oldurulen surec)."""
        cr = self.real_cursor()
        try:
            cr.execute("SELECT id FROM delivery_carrier WHERE name->>'en_US' = 'KK Esz Kargo'")
            carriers = tuple(r[0] for r in cr.fetchall())
            if carriers:
                cr.execute('SELECT id FROM cargo_shipment WHERE carrier_id IN %s', [carriers])
                self.committed['shipments'] += [r[0] for r in cr.fetchall()]
                self.committed['carriers'] += list(carriers)
            cr.execute("SELECT id FROM cargo_area WHERE provider = 'fixed' AND name = 'CANKAYA'"
                       " AND area_code BETWEEN 990000 AND 999000")
            self.committed['areas'] += [r[0] for r in cr.fetchall()]
        finally:
            cr.close()
        self.committed['group_added'] = True
        self.purge()
        self.committed = {'shipments': [], 'areas': [], 'carriers': []}

    def prepare(self):
        cr = self.real_cursor()
        try:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env['res.users'].browse(self.admin_id).write({'group_ids': [(4, self.group_id)]})
            state = env.ref('base.state_tr_06')
            self.committed['group_added'] = True
            CargoKabulCase._area_seq += 1
            area = env['cargo.area'].create({'provider': 'fixed', 'state_id': state.id, 'name': 'CANKAYA',
                                             'city_code': 6, 'area_code': CargoKabulCase._area_seq + 70000})
            self.committed['areas'].append(area.id)
            product = env.ref('delivery.product_product_delivery', raise_if_not_found=False)
            if not product:
                product = env['product.product'].create({'name': 'Kargo (esz)', 'type': 'service'})
            carrier = env['delivery.carrier'].create({
                'name': 'KK Esz Kargo', 'delivery_type': 'fixed', 'product_id': product.id,
                'integration_level': 'rate'})
            self.committed['carriers'].append(carrier.id)
            self.carrier_id = carrier.id
            self.state_id = state.id
            cr.commit()
        finally:
            cr.close()

    def new_shipment(self):
        cr = self.real_cursor()
        try:
            env = api.Environment(cr, self.admin_id, {})
            shipment = env['cargo.shipment'].create({
                'carrier_id': self.carrier_id, 'recipient_name': 'Esz Test', 'recipient_phone': '05321234567',
                'recipient_street': 'Ataturk Mah. Test Sk. 1', 'recipient_state_id': self.state_id,
                'recipient_district': 'Cankaya', 'package_count': 1, 'package_weight': 1.0})
            self.committed['shipments'].append(shipment.id)
            cr.commit()
            return shipment.id
        finally:
            cr.close()

    def purge(self):
        cr = self.real_cursor()
        try:
            ids = tuple(self.committed['shipments']) or (0,)
            cr.execute('DELETE FROM cargo_shipment WHERE id IN %s', [ids])
            cr.execute("DELETE FROM ir_attachment WHERE res_model = 'cargo.shipment' AND res_id IN %s", [ids])
            cr.execute("DELETE FROM mail_message WHERE model = 'cargo.shipment' AND res_id IN %s", [ids])
            cr.execute("DELETE FROM mail_followers WHERE res_model = 'cargo.shipment' AND res_id IN %s", [ids])
            if self.committed['areas']:
                cr.execute('DELETE FROM cargo_area WHERE id IN %s', [tuple(self.committed['areas'])])
            if self.committed['carriers']:
                cr.execute('DELETE FROM delivery_carrier WHERE id IN %s', [tuple(self.committed['carriers'])])
            if self.committed.get('group_added'):
                env = api.Environment(cr, SUPERUSER_ID, {})
                env['res.users'].browse(self.admin_id).write({'group_ids': [(3, self.group_id)]})
            cr.commit()
        finally:
            cr.close()

    def db_state(self, shipment_id):
        cr = self.real_cursor()
        try:
            cr.execute('SELECT state, sent_at FROM cargo_shipment WHERE id = %s', [shipment_id])
            return cr.fetchone()
        finally:
            cr.close()

    def run_send(self, shipment_id, results, key, before=None):
        """Ayri imecle action_send; sonuc/istisna results[key]'e yazilir (iplikten assert yapilmaz)."""
        cr = self.real_cursor()
        try:
            if before:
                before()
            env = api.Environment(cr, self.admin_id, {})
            try:
                env['cargo.shipment'].browse(shipment_id).action_send()
                cr.commit()
                results[key] = ('ok', None)
            except Exception as error:      # noqa: BLE001 - sonuc raporu
                cr.rollback()
                results[key] = ('error', error)
        finally:
            cr.close()

    def test_bekleyen_saglayici_varken_ikinci_oturum_reddedilir(self):
        entered, release = threading.Event(), threading.Event()
        observed = {}

        def hook(shipment):
            entered.set()
            observed['committed_state'] = self.db_state(shipment.id)      # ucuncu baglanti: gercek commit goruldu mu
            release.wait(30)
        self.provider.hook['send'] = hook
        shipment_id = self.new_shipment()
        results = {}
        first = threading.Thread(target=self.run_send, args=(shipment_id, results, 'A'))
        first.start()
        self.assertTrue(entered.wait(30), 'A saglayiciya girmedi')
        try:
            self.run_send(shipment_id, results, 'B')
        finally:
            release.set()
            first.join(60)
        self.assertFalse(first.is_alive(), 'A is parcasi tamamlanmadi')
        self.assertEqual(observed['committed_state'][0], 'sending', 'saglayici cagrisi sirasinda baska baglanti sending gormeli')
        self.assertTrue(observed['committed_state'][1], 'sent_at commit edilmis olmali')
        self.assertEqual(results['A'][0], 'ok', 'A hatasi: %r' % (results['A'][1],))
        kind, error = results['B']
        self.assertEqual(kind, 'error', 'ikinci oturum reddedilmeli')
        self.assertIsInstance(error, UserError, 'ham veritabani hatasi kullaniciya sizmamali: %r' % (error,))
        self.assertRegex(str(error), r'(?i)zaten')
        self.assertEqual(self.provider.count('send'), 1, 'UPS\'e en fazla 1 CreateShipment')
        self.assertEqual(self.db_state(shipment_id)[0], 'created')

    def test_es_zamanli_baslangic(self):
        barrier = threading.Barrier(2, timeout=30)

        def slow(shipment):
            threading.Event().wait(1.0)          # pencereyi genislet
        self.provider.hook['send'] = slow
        shipment_id = self.new_shipment()
        results = {}
        threads = [threading.Thread(target=self.run_send, args=(shipment_id, results, key),
                                    kwargs={'before': barrier.wait}) for key in ('A', 'B')]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(90)
        self.assertFalse([t for t in threads if t.is_alive()], 'is parcasi takildi (kilitlenme?)')
        outcomes = sorted(kind for kind, _e in results.values())
        self.assertEqual(self.provider.count('send'), 1, 'iki oturum -> saglayiciya TEK cagri')
        self.assertEqual(outcomes, ['error', 'ok'], 'biri basarili, digeri reddedilmeli: %r' % (results,))
        error = next(e for kind, e in results.values() if kind == 'error')
        self.assertIsInstance(error, UserError, 'ham veritabani hatasi sizmamali: %r' % (error,))
        self.assertRegex(str(error), r'(?i)zaten')
        self.assertEqual(self.db_state(shipment_id)[0], 'created')
