"""İYS "İzin Al" sihirbazı: rehberde zaten olan (aktif/arşivli) numarada tek kayıt, hata yok."""
from unittest.mock import patch

from odoo.tests.common import tagged

from odoo.addons.sms_system.services.smartadm import SmartAdmClient

from .common import SmsTestCase


@tagged('post_install', '-at_install')
class TestIysConsentExistingContact(SmsTestCase):

    def setUp(self):
        super().setUp()
        # _save_contact ayrı işlemde (registry.cursor) çalışır; testte o imleç test imlecini sarar.
        self.registry_enter_test_mode()
        self.configure_sms(iys=True)
        self.Contact = self.env['sms.system.contact']
        self.Wizard = self.env['sms.system.iys.consent']
        for name in ('approve', 'contact_api_load'):
            patcher = patch.object(SmartAdmClient, name, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _count(self, mobile):
        return self.Contact.with_context(active_test=False).search_count([('mobile', '=', mobile)])

    def _by_code(self, mobile, **extra):
        wiz = self.Wizard.create(dict({'mobile': mobile, 'method': 'code', 'step': 'code',
                                       'trigger_id': 'T1', 'activation_key': '123456'}, **extra))
        wiz.action_approve()
        return wiz

    def _by_form(self, mobile, **extra):
        wiz = self.Wizard.create(dict({'mobile': mobile, 'method': 'form', 'source': 'HS_WEB'}, **extra))
        wiz.action_load_form()
        return wiz

    def _check_approved(self, mobile):
        self.assertEqual(self._count(mobile), 1, 'numara için tek kayıt olmalı')
        contact = self.Contact.with_context(active_test=False).search([('mobile', '=', mobile)])
        contact.invalidate_recordset()
        self.assertEqual(contact.iys_status, 'approved')
        self.assertTrue(contact.iys_checked_at)
        return contact

    def test_arsivli_kisi_kod_yolu(self):
        old = self.Contact.create({'mobile': '5102204616', 'name': 'Eski', 'active': False})
        self._by_code('0510 220 46 16', name='Yeni Ad')
        contact = self._check_approved('5102204616')
        self.assertEqual(contact, old)
        self.assertEqual(contact.name, 'Eski', 'mevcut ad ezilmemeli')
        self.assertTrue(contact.active, 'izin alınan kişi arşivden çıkar')

    def test_arsivli_kisi_form_yolu(self):
        old = self.Contact.create({'mobile': '5102204616', 'active': False})
        lst = self.env['sms.system.list'].create({'name': 'L'})
        self._by_form('+90 510 220 46 16', name='Ad', list_id=lst.id)
        contact = self._check_approved('5102204616')
        self.assertEqual(contact, old)
        self.assertEqual(contact.name, 'Ad')
        self.assertIn(lst, contact.list_ids)
        self.assertEqual(contact.iys_source, 'HS_WEB')

    def test_aktif_kisi_tek_kayit(self):
        old = self.Contact.create({'mobile': '5102204616'})
        self._by_code('5102204616')
        self.assertEqual(self._check_approved('5102204616'), old)
        self._by_form('5102204616')
        self.assertEqual(self._check_approved('5102204616'), old)

    def test_yeni_numara_kayit_olusur(self):
        self._by_form('5102204617')
        self._check_approved('5102204617')

    def test_kara_listedeki_arsivli_kisi_kara_listede_kalir(self):
        """İYS izni alınır ama kara liste kararı sessizce kaldırılmaz."""
        old = self.Contact.create({'mobile': '5102204618', 'active': False, 'opt_out': True})
        self._by_form('5102204618')
        contact = self._check_approved('5102204618')
        self.assertEqual(contact, old)
        self.assertTrue(contact.opt_out)
