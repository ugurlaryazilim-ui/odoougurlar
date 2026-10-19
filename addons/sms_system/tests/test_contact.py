"""KK-A21: rehber aktarımında toplu liste bağlama."""
import math
from unittest.mock import patch

from odoo.tests.common import tagged

from odoo.addons.sms_system.models import sms_contact

from .common import SmsTestCase

TOTAL = 10000
FILL = 200   # adı doldurulacak kişi sayısı


@tagged('post_install', '-at_install')
class TestContactUpsert(SmsTestCase):

    def _seed_existing(self):
        """10.000 mevcut kişi (SQL ile hızlı), hiçbir listeye bağlı değil."""
        cr = self.env.cr
        self.env.flush_all()
        cr.execute("""
            INSERT INTO sms_system_contact
                (mobile, source, iys_status, opt_out, active, create_uid, write_uid, create_date, write_date)
            SELECT '533' || lpad(i::text, 7, '0'), 'manual', 'unknown', false, true, 1, 1,
                   now() at time zone 'utc', now() at time zone 'utc'
              FROM generate_series(1, %s) AS i
        """, (TOTAL,))
        self.env.invalidate_all()

    @staticmethod
    def _number(i):
        return '533%07d' % i

    def _count_writes(self):
        Contact = self.env['sms.system.contact']
        calls = []
        real = type(Contact).write

        def spy(this, vals):
            calls.append((len(this), sorted(vals)))
            return real(this, vals)

        return calls, patch.object(type(Contact), 'write', spy)

    def test_kk_a21_10000_kisi_yeni_listeye_toplu_baglanir(self):
        self._seed_existing()
        lst = self.env['sms.system.list'].create({'name': 'Yeni'})
        rows = [{'mobile': self._number(i)} for i in range(1, TOTAL + 1)]
        calls, spy = self._count_writes()
        with spy:
            result = self.env['sms.system.contact'].upsert_numbers(rows, 'excel', lists=[lst])
        self.assertEqual(result, {'created': 0, 'updated': TOTAL, 'invalid': [], 'duplicate': 0})
        self.env.cr.execute('SELECT count(*) FROM sms_system_contact_list_rel WHERE list_id = %s', (lst.id,))
        self.assertEqual(self.env.cr.fetchone()[0], TOTAL, '10.000 kişinin hepsi listeye bağlanmalı')
        chunks = math.ceil(TOTAL / sms_contact.UPSERT_CHUNK)
        self.assertLessEqual(len(calls), 0 + chunks,
                             'liste bağlama kişi başına write ile yapılmamalı (write çağrısı: %s)' % len(calls))

    def test_kk_a21_adi_doldurulacak_kisiler_icin_write_siniri(self):
        self._seed_existing()
        lst = self.env['sms.system.list'].create({'name': 'Yeni'})
        rows = [{'mobile': self._number(i), 'name': 'Ad %s' % i if i <= FILL else None}
                for i in range(1, TOTAL + 1)]
        calls, spy = self._count_writes()
        with spy:
            result = self.env['sms.system.contact'].upsert_numbers(rows, 'excel', lists=[lst])
        self.assertEqual(result['updated'], TOTAL)
        chunks = math.ceil(TOTAL / sms_contact.UPSERT_CHUNK)
        self.assertLessEqual(len(calls), FILL + chunks, 'write çağrısı: %s' % len(calls))
        Contact = self.env['sms.system.contact']
        self.assertEqual(Contact.search_count([('list_ids', 'in', lst.id)]), TOTAL)
        named = Contact.search([('list_ids', 'in', lst.id), ('name', '!=', False)])
        self.assertEqual(len(named), FILL)
        self.assertEqual(Contact.search([('mobile', '=', self._number(7))]).name, 'Ad 7')

    def test_kk_a21_donus_anahtarlari_ve_sayilari_degismez(self):
        Contact = self.env['sms.system.contact']
        lst = self.env['sms.system.list'].create({'name': 'Yeni'})
        Contact.create({'mobile': '5330000001', 'opt_out': True, 'iys_status': 'rejected'})
        rows = [{'mobile': '05330000001'}, {'mobile': '5330000001'},      # mevcut + dosya içi tekrar
                {'mobile': '5330000002', 'name': 'Yeni Kişi'},               # yeni
                {'mobile': '123'}, {'mobile': 'abc'}, {'mobile': ''}]       # geçersizler (boş sayılmaz)
        result = Contact.upsert_numbers(rows, 'excel', lists=[lst])
        self.assertEqual(set(result), {'created', 'updated', 'invalid', 'duplicate'})
        self.assertEqual((result['created'], result['updated'], result['duplicate']), (1, 1, 1))
        self.assertEqual(result['invalid'], ['123', 'abc'])
        existing = Contact.search([('mobile', '=', '5330000001')])
        self.assertTrue(existing.opt_out, 'kara liste değişmemeli')
        self.assertEqual(existing.iys_status, 'rejected', 'İYS durumu değişmemeli')
        self.assertIn(lst, existing.list_ids)
        self.assertIn(lst, Contact.search([('mobile', '=', '5330000002')]).list_ids)

    def test_kk_a21_pasif_kisi_aktiflenir_ve_listeye_baglanir(self):
        Contact = self.env['sms.system.contact']
        lst = self.env['sms.system.list'].create({'name': 'Yeni'})
        old = Contact.create({'mobile': '5330000003', 'active': False})
        Contact.upsert_numbers([{'mobile': '5330000003'}], 'excel', lists=[lst])
        old.invalidate_recordset()
        self.assertTrue(old.active)
        self.assertIn(lst, old.list_ids)

    def test_kk_a21_liste_verilmezse_baglama_yapilmaz(self):
        Contact = self.env['sms.system.contact']
        old = Contact.create({'mobile': '5330000004'})
        result = Contact.upsert_numbers([{'mobile': '5330000004'}], 'excel')
        self.assertEqual(result['updated'], 1)
        self.assertFalse(old.list_ids)
