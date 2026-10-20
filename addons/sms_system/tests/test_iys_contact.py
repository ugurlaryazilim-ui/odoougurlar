"""İYS kişi kartı akışı: Session → Query → Contact (kişi yoksa) → Trigger/ContactApiLoad; -613/-607 bilgi sayılır;
RemoteStoreId başlığı (boşsa "MERKEZ"); ad/soyad bölme.

SmartADM taklidi FakeNet'te: 'missing' numarada Contact çağrılana kadar trigger/contactapiload -6/-601 verir.
"""
from datetime import datetime

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from odoo.addons.sms_system.services.smartadm import SmartAdmClient, SmartAdmError, split_name

from .common import SmsTestCase, smart_error

NEW = '5102205001'     # İYS'de kaydı olmayan numara
KNOWN = '5102205002'   # İYS'de kayıtlı numara


def _client(store=None):
    return SmartAdmClient('CUST', 'iysuser', 'iyspass', store=store)


@tagged('post_install', '-at_install')
class TestSplitName(SmsTestCase):

    def test_son_bosluktan_boler(self):
        self.assertEqual(split_name('Ayşe Yılmaz'), ('Ayşe', 'Yılmaz'))
        self.assertEqual(split_name('Ayşe Nur  Yılmaz '), ('Ayşe Nur', 'Yılmaz'))

    def test_tek_kelime_soyad_yok(self):
        self.assertEqual(split_name('Ayşe'), ('Ayşe', None))

    def test_bos_girdi(self):
        for value in (None, False, '', '   '):
            self.assertEqual(split_name(value), (None, None))


@tagged('post_install', '-at_install')
class TestSmartAdmContactClient(SmsTestCase):

    def test_create_contact_govde_ve_uc(self):
        self.assertTrue(_client().create_contact(NEW, 'Ayşe', 'Yılmaz', 'odoo-contact-7'))
        call = self.net.smart_calls('contact')[0]
        self.assertTrue(call['url'].endswith('/webservice/api/Contact'))
        self.assertEqual(call['payload'], {
            'CommunicationTools': {'Msisdn': '90' + NEW},
            'ContactDetails': {'Name': 'Ayşe', 'Surname': 'Yılmaz', 'RemoteReferenceId': 'odoo-contact-7'},
            'SessionId': 'SESS'})

    def test_create_contact_bos_alanlar_gonderilmez(self):
        _client().create_contact(NEW, 'Ayşe', None, '')
        self.assertEqual(self.net.smart_calls('contact')[0]['payload']['ContactDetails'], {'Name': 'Ayşe'})
        _client().create_contact('5102205009')
        self.assertNotIn('ContactDetails', self.net.smart_calls('contact')[1]['payload'])

    def test_create_contact_613_basari_sayilir(self):
        self.net.smart_contact = smart_error(-6, -613)
        self.assertFalse(_client().create_contact(NEW, 'Ayşe'))

    def test_create_contact_diger_hata_istisna(self):
        self.net.smart_contact = smart_error(-6, -9999)
        with self.assertRaises(SmartAdmError):
            _client().create_contact(NEW, 'Ayşe')

    def test_create_contact_gecersiz_numara_istek_atmaz(self):
        with self.assertRaises(SmartAdmError) as ctx:
            _client().create_contact('05321234567')
        self.assertTrue(ctx.exception.invalid_number)
        self.assertEqual(self.net.smartadm_calls, [])

    def test_ensure_contact_kayitli_kisi_icin_contact_cagirmaz(self):
        self.assertFalse(_client().ensure_contact(KNOWN, 'Ayşe Yılmaz', 'x'))
        self.assertEqual(self.net.smart_paths, ['session', 'query'])

    def test_ensure_contact_yeni_kisi_ad_soyad_boler(self):
        self.net.iys[NEW] = 'missing'
        self.assertTrue(_client().ensure_contact(NEW, 'Ayşe Nur Yılmaz', 'ref-1'))
        self.assertEqual(self.net.smart_paths, ['session', 'query', 'contact'])
        self.assertEqual(self.net.smart_calls('contact')[0]['payload']['ContactDetails'],
                         {'Name': 'Ayşe Nur', 'Surname': 'Yılmaz', 'RemoteReferenceId': 'ref-1'})

    def test_trigger_607_none_doner(self):
        self.net.smart_trigger = smart_error(-6, -607)
        self.assertIsNone(_client().trigger(KNOWN))

    def test_trigger_basarili_kimligi_doner(self):
        self.assertEqual(_client().trigger(KNOWN), 'TRIG1')

    def test_contact_api_load_607_false_doner(self):
        self.net.smart_load = smart_error(-6, -607)
        self.assertFalse(_client().contact_api_load(KNOWN, True, datetime.now(), 'HS_WEB'))
        self.net.smart_load = None
        self.assertTrue(_client().contact_api_load(KNOWN, True, datetime.now(), 'HS_WEB'))

    def test_hic_kisi_karti_olmadan_trigger_601_verir(self):
        """Taklidin dayanağı: kart yokken trigger -601 (canlıdaki hatanın aynısı)."""
        self.net.iys[NEW] = 'missing'
        with self.assertRaises(SmartAdmError) as ctx:
            _client().trigger(NEW)
        self.assertEqual(ctx.exception.code, (-6, -601))

    def test_remote_store_id_bos_ise_merkez(self):
        for store in (None, '', '  '):
            self.net.calls.clear()
            _client(store).query(KNOWN)
            for call in self.net.smartadm_calls:
                self.assertEqual(call['headers'].get('RemoteStoreId'), 'MERKEZ')

    def test_remote_store_id_ayar_degeri(self):
        _client('KADIKOY').query(KNOWN)
        for call in self.net.smartadm_calls:
            self.assertEqual(call['headers'].get('RemoteStoreId'), 'KADIKOY')


@tagged('post_install', '-at_install')
class TestIysConsentContactFlow(SmsTestCase):

    def setUp(self):
        super().setUp()
        # _save_contact ayrı işlemde çalışır; testte o imleç test imlecini sarar
        self.registry_enter_test_mode()
        self.configure_sms(iys=True)
        self.Contact = self.env['sms.system.contact']
        self.Wizard = self.env['sms.system.iys.consent']
        self.net.iys[NEW] = 'missing'

    def _contact_already_created(self):
        """Contact -6/-613 döner: kart az önce oluşturulmuş (kart artık var, sonraki uçlar çalışır)."""
        def already(call):
            self.net.cards.add(call['number'])
            return smart_error(-6, -613)
        self.net.smart_contact = already

    def _flow(self):
        """Oturum çağrıları hariç sırayla çağrılan SmartADM uçları."""
        return [p for p in self.net.smart_paths if p != 'session']

    def _code(self, mobile=NEW, **extra):
        wiz = self.Wizard.create(dict({'mobile': mobile, 'method': 'code'}, **extra))
        wiz.action_send_code()
        return wiz

    def _form(self, mobile=NEW, **extra):
        wiz = self.Wizard.create(dict({'mobile': mobile, 'method': 'form', 'source': 'HS_WEB'}, **extra))
        wiz.action_load_form()
        return wiz

    def _contact(self, mobile=NEW):
        return self.Contact.with_context(active_test=False).search([('mobile', '=', mobile)])

    # ── kod yolu ──
    def test_kod_yolu_yeni_kisi_query_contact_trigger_sirasi(self):
        wiz = self._code(name='Ayşe Yılmaz')
        self.assertEqual(self._flow(), ['query', 'contact', 'trigger'])
        self.assertEqual((wiz.step, wiz.trigger_id), ('code', 'TRIG1'))
        details = self.net.smart_calls('contact')[0]['payload']['ContactDetails']
        self.assertEqual(details['Name'], 'Ayşe')
        self.assertEqual(details['Surname'], 'Yılmaz')
        self.assertEqual(details['RemoteReferenceId'], NEW, 'rehberde yoksa normalize numara')

    def test_kod_yolu_tek_kelime_ad_soyad_gonderilmez(self):
        self._code(name='Ayşe')
        details = self.net.smart_calls('contact')[0]['payload']['ContactDetails']
        self.assertNotIn('Surname', details)
        self.assertEqual(details['Name'], 'Ayşe')

    def test_kod_yolu_adsiz_yalniz_referans(self):
        self._code(mobile='0510 220 50 01')
        self.assertEqual(self.net.smart_calls('contact')[0]['payload']['ContactDetails'], {'RemoteReferenceId': NEW})

    def test_kod_yolu_rehberdeki_kisinin_kimligi_referans_olur(self):
        old = self.Contact.create({'mobile': NEW, 'name': 'Eski', 'active': False})
        self._code(name='Ayşe Yılmaz')
        self.assertEqual(self.net.smart_calls('contact')[0]['payload']['ContactDetails']['RemoteReferenceId'],
                         'odoo-contact-%s' % old.id)

    def test_kod_yolu_613_akis_surer(self):
        self._contact_already_created()
        wiz = self._code()
        self.assertEqual(self._flow(), ['query', 'contact', 'trigger'])
        self.assertEqual(wiz.step, 'code')
        self.assertTrue(wiz.trigger_id)

    def test_kod_yolu_kayitli_kisi_contact_cagrilmaz(self):
        wiz = self._code(mobile=KNOWN)
        self.assertEqual(self._flow(), ['query', 'trigger'])
        self.assertEqual(wiz.step, 'code')

    def test_kod_yolu_contact_hatasi_trigger_cagrilmaz(self):
        self.net.smart_contact = smart_error(-6, -9999)
        with self.assertRaises(UserError):
            self._code()
        self.assertEqual(self._flow(), ['query', 'contact'])

    def test_kod_yolu_607_bilgi_rehber_onayli_yazilir(self):
        old = self.Contact.create({'mobile': KNOWN, 'name': 'K', 'iys_source': 'HS_WEB'})
        self.net.smart_trigger = smart_error(-6, -607)
        wiz = self._code(mobile=KNOWN)
        self.assertEqual(wiz.step, 'done')
        self.assertIn('zaten', wiz.result)
        self.assertNotIn('approve', self._flow(), 'kod gönderilmedi, onay adımı yok')
        old.invalidate_recordset()
        self.assertEqual(old.iys_status, 'approved')
        self.assertTrue(old.iys_checked_at)
        self.assertEqual(old.iys_source, 'HS_WEB', 'bilinmeyen kaynak mevcut kaynağı ezmez')
        self.assertEqual(self.Contact.with_context(active_test=False).search_count([('mobile', '=', KNOWN)]), 1)

    def test_kod_yolu_607_yeni_numara_rehbere_eklenir(self):
        self.net.smart_trigger = smart_error(-6, -607)
        self._code()
        contact = self._contact()
        self.assertEqual(len(contact), 1)
        self.assertEqual(contact.iys_status, 'approved')

    def test_onay_adimi_degismedi(self):
        wiz = self._code()
        wiz.activation_key = '123456'
        wiz.action_approve()
        self.assertEqual(self._flow(), ['query', 'contact', 'trigger', 'approve'])
        self.assertEqual(wiz.step, 'done')
        self.assertEqual(self._contact().iys_source, 'HS_MESAJ')

    # ── form yolu ──
    def test_form_yolu_yeni_kisi_query_contact_load_sirasi(self):
        wiz = self._form(name='Ayşe Nur Yılmaz')
        self.assertEqual(self._flow(), ['query', 'contact', 'contactapiload'])
        self.assertEqual(wiz.step, 'done')
        self.assertEqual(self.net.smart_calls('contact')[0]['payload']['ContactDetails'],
                         {'Name': 'Ayşe Nur', 'Surname': 'Yılmaz', 'RemoteReferenceId': NEW})
        contact = self._contact()
        self.assertEqual((contact.iys_status, contact.iys_source), ('approved', 'HS_WEB'))

    def test_form_yolu_613_akis_surer(self):
        self._contact_already_created()
        wiz = self._form()
        self.assertEqual(self._flow(), ['query', 'contact', 'contactapiload'])
        self.assertEqual(wiz.step, 'done')

    def test_form_yolu_kayitli_kisi_contact_cagrilmaz(self):
        self._form(mobile=KNOWN)
        self.assertEqual(self._flow(), ['query', 'contactapiload'])

    def test_form_yolu_contact_hatasi_load_cagrilmaz(self):
        self.net.smart_contact = smart_error(-6, -9999)
        with self.assertRaises(UserError):
            self._form()
        self.assertEqual(self._flow(), ['query', 'contact'])
        self.assertFalse(self._contact(), 'hata durumunda rehbere yazılmaz')

    def test_form_yolu_607_bilgi_rehber_onayli_yazilir(self):
        old = self.Contact.create({'mobile': KNOWN, 'iys_source': 'HS_FIZIKSEL_ORTAM'})
        self.net.smart_load = smart_error(-6, -607)
        wiz = self._form(mobile=KNOWN)
        self.assertEqual(wiz.step, 'done')
        self.assertIn('zaten', wiz.result)
        old.invalidate_recordset()
        self.assertEqual(old.iys_status, 'approved')
        self.assertEqual(old.iys_source, 'HS_FIZIKSEL_ORTAM', 'yüklemediğimiz iznin kaynağı yazılmaz')

    # ── RemoteStoreId (ayardan) ──
    def test_ayar_bos_iken_tum_cagrilarda_merkez(self):
        self._code()
        self.assertTrue(self.net.smartadm_calls)
        for call in self.net.smartadm_calls:
            self.assertEqual(call['headers'].get('RemoteStoreId'), 'MERKEZ', call['path'])

    def test_ayar_doluysa_ayar_degeri(self):
        self.icp.set_param('sms_system.iys_store', 'ANKARA')
        self._form()
        for call in self.net.smartadm_calls:
            self.assertEqual(call['headers'].get('RemoteStoreId'), 'ANKARA', call['path'])

    # ── kaynak listesi ──
    def test_kaynak_listesinde_mobil_var(self):
        sources = dict(self.Wizard._fields['source'].selection)
        for code in ('HS_FIZIKSEL_ORTAM', 'HS_WEB', 'HS_MOBIL', 'HS_CAGRI_MERKEZI'):
            self.assertIn(code, sources)
