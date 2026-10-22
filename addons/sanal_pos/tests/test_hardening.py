# -*- coding: utf-8 -*-
"""G12 / yetki, sır ve KVKK sertleştirme. KK-5, KK-35, KK-36, KK-37, KK-39, KK-49, NFR-4, U-3.

test_security.py (kabul testleri) tek tek yüzeyleri sınar; bu dosya ona EK olarak şunları yapar:

* RPC yüzeyi TARAMASI: modülün tanımladığı, ``_`` ile başlamayan her metot ya ``@api.private``
  (call_kw ile çağrılamaz) ya da burada AÇIKÇA listelenmiş ve rol matrisiyle sınanmıştır.
  Yeni bir public metot eklenip listeye girmezse bu test kırılır (gözden geçirme zorunlu).
* Rol matrisi: grupsuz iç kullanıcı / Sanal POS Kullanıcısı / Yöneticisi / sistem yöneticisi (U-3).
* Gerçek HTTP JSON-RPC (oturumsuz, grupsuz, kullanıcı): özel metotlar ve kayıtlar kapalı.
* Sırlar ve kişisel veri: tüm akışlar (oluştur, zaman aşımı, hata, iade) sonrası her yüzey taranır.
"""
import json
from unittest.mock import patch

import requests
from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.service.model import get_public_method
from odoo.tests import tagged

from .common import (
    BASE_SETTINGS, CRON_SYNC, CUSTOMER_NAME, EMAIL, INV_NO, MSSQL_USER, PASSWORD, SECRET_KEY,
    RawResponse, SanalPosCase, SanalPosHttpCase, err_body, tran,
)
from .test_security import FULL_PHONE_FORMS, NOTIFY, SECRETS, SecurityCase

MODULE_PREFIX = 'odoo.addons.sanal_pos'

# Modülün RPC'ye açık bıraktığı (``@api.private`` olmayan) metotlar. Her biri ya ACL'e ya da
# metot içi grup denetimine dayanır; ikisi de aşağıdaki rol matrisiyle sınanır.
EXPECTED_PUBLIC = {
    'sanal.pos.payment': {
        'create', 'action_new_link', 'action_check_status', 'action_resend', 'action_cancel_link',
        'action_review_accept', 'action_review_close', 'action_void', 'action_refund',
        'action_open_refund_wizard', 'action_open_void_wizard',
        # Mail Order (G3): ikisi de metot içi grup denetimi ile korunur (_check_sanal_pos_user)
        'action_open_card_page', 'action_mail_order_close',
    },
    'sanal.pos.refund': {'write', 'unlink'},
    'sanal.pos.payment.create.wizard': {'create', 'write', 'action_fetch_invoice', 'action_create_link'},
    # create_wizard'dan miras: aynı korumalı alan denetimi ve fatura getirme + yeni eylem
    'sanal.pos.mail.order.wizard': {'create', 'write', 'action_fetch_invoice', 'action_create_link',
                                    'action_create_mail_order'},
    'sanal.pos.payment.resend.wizard': {'default_get', 'action_confirm'},
    'sanal.pos.payment.refund.wizard': {'action_confirm'},
    'sanal.pos.payment.review.close.wizard': {'action_confirm'},
    # default_get/create/write: yalnız yönetici ACL'i; aşama/rapor alanlarını atar (D-1, test_refund_migration)
    'sanal.pos.refund.approval.wizard': {'default_get', 'create', 'write', 'action_compare',
                                         'action_apply'},
    'res.config.settings': {'action_copy_tailor_mssql', 'action_sanal_pos_test_connection',
                            'default_get', 'set_values'},
}

# Sanal POS Kullanıcısına KAPALI olması gereken (yönetici) eylemler.
MANAGER_ONLY = ('action_review_accept', 'action_review_close', 'action_void', 'action_refund',
                'action_open_refund_wizard', 'action_open_void_wizard')
ACTION_ARGS = {
    'action_resend': (['sms'],),
    'action_void': ('Müşteri vazgeçti',),
    'action_refund': (100.0, 'Müşteri talebi'),
}
SP_MODELS = ('sanal.pos.payment', 'sanal.pos.refund', 'sanal.pos.log',
             'sanal.pos.payment.create.wizard', 'sanal.pos.mail.order.wizard',
             'sanal.pos.payment.resend.wizard',
             'sanal.pos.payment.refund.wizard', 'sanal.pos.payment.review.close.wizard')


def own_public_methods(model):
    """``model`` için modülümüzün sınıflarında tanımlı, ``_`` ile başlamayan çağrılabilir adlar."""
    names = set()
    for klass in type(model).mro():
        if not (klass.__module__ or '').startswith(MODULE_PREFIX):
            continue
        for name, attr in vars(klass).items():
            if name.startswith('_') or isinstance(attr, (fields.Field, property)):
                continue
            if callable(attr) or isinstance(attr, (staticmethod, classmethod)):
                names.add(name)
    return names


def rpc_callable(model, name):
    try:
        get_public_method(model, name)
    except AccessError:
        return False
    return True


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRpcSurfaceInventory(SanalPosCase):
    """Public metot taraması (447a791 kalıbı, tüm modeller ve sihirbazlar)."""

    def scanned_models(self):
        names = sorted(m for m in self.env.registry if m.startswith('sanal.pos.'))
        return names + ['res.config.settings']

    def test_modelde_listelenmemis_public_metot_yok(self):
        found = {}
        for name in self.scanned_models():
            model = self.env(user=self.user_sp)[name]
            public = {m for m in own_public_methods(model) if rpc_callable(model, m)}
            if public:
                found[name] = public
        for name, public in found.items():
            extra = public - EXPECTED_PUBLIC.get(name, set())
            self.assertFalse(extra, '%s: RPC\'ye açık ve listelenmemiş metot: %s. @api.private yapın '
                                    'ya da EXPECTED_PUBLIC + rol matrisine ekleyin.' % (name, sorted(extra)))

    def test_beklenen_public_metotlar_gercekten_var(self):
        """Liste bayatlamasın: silinen/özel yapılan metot listeden de çıkarılmalı."""
        for name, expected in EXPECTED_PUBLIC.items():
            model = self.env(user=self.user_sp)[name]
            missing = {m for m in expected if not rpc_callable(model, m)}
            self.assertFalse(missing, '%s: listede ama RPC\'ye kapalı/yok: %s' % (name, sorted(missing)))

    def test_saglayici_ve_fatura_kaynagi_tamamen_ozel(self):
        for name in ('sanal.pos.provider', 'sanal.pos.provider.paratika', 'sanal.pos.invoice.source.nebim'):
            model = self.env(user=self.user_mgr)[name]
            public = {m for m in own_public_methods(model) if rpc_callable(model, m)}
            self.assertFalse(public, '%s: dış çağrı/PII yüzeyi RPC\'ye açık: %s' % (name, sorted(public)))

    def test_cron_ve_ic_metotlar_rpc_ile_cagrilamaz(self):
        payment = self.env(user=self.user_mgr)['sanal.pos.payment']
        for name in ('_cron_sync', '_cron_daily', '_sync_status', '_apply_status', '_sp_commit',
                     '_call_provider_safely', '_review_close', '_notify_creator'):
            with self.subTest(method=name):
                with self.assertRaises(AccessError):
                    get_public_method(payment, name)
        with self.assertRaises(AccessError):
            get_public_method(self.env(user=self.user_mgr)['sanal.pos.log'], '_purge_old')

    def test_yeni_alan_adlarinda_sir_yok(self):
        """Hiçbir Sanal POS modeli sır saklayan bir alana sahip değildir (yalnız ayar parametreleri)."""
        for name in SP_MODELS:
            for fname, field in self.env[name]._fields.items():
                low = fname.lower()
                self.assertFalse('password' in low or 'secret' in low or 'sifre' in low,
                                 '%s.%s sır gibi görünüyor' % (name, fname))
                self.assertFalse(field.type == 'binary', '%s.%s ikili alan' % (name, fname))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRoleMatrix(SecurityCase):
    """Dört rol x tüm eylemler. Reddedilen her çağrıda Paratika ve MSSQL'e istek gitmez, durum değişmez."""

    def public_actions(self):
        return sorted(n for n in EXPECTED_PUBLIC['sanal.pos.payment'] if n.startswith('action_'))

    def assertDenied(self, user, method):
        payment = self.paid_payment
        args = ACTION_ARGS.get(method, ())
        before = (payment.state, payment.refunded_amount, len(payment.refund_ids))
        with self.assertRaises(AccessError, msg='%s -> %s reddedilmedi' % (user.login, method)):
            getattr(payment.with_user(user), method)(*args)
        payment.invalidate_recordset()
        self.assertEqual((payment.state, payment.refunded_amount, len(payment.refund_ids)), before)
        self.assertNoParatikaCalls('%s -> %s: Paratika\'ya istek gitti' % (user.login, method))
        self.assertEqual(self.mssql_calls, [])

    def assertBlocked(self, func, msg=None):
        """``func`` AccessError ya da UserError ile reddedilmeli (assertRaises demet kabul etmez)."""
        try:
            func()
        except (AccessError, UserError):
            return
        self.fail(msg or 'çağrı reddedilmedi')

    def setUp(self):
        super().setUp()
        self.paid_payment = self.make_paid()

    def test_eylem_listesi_tam(self):
        self.assertEqual(set(self.public_actions()),
                         {n for n in EXPECTED_PUBLIC['sanal.pos.payment'] if n != 'create'})

    def test_grupsuz_ic_kullanici_hicbir_eylemi_yapamaz(self):
        for method in self.public_actions():
            with self.subTest(method=method):
                self.assertDenied(self.user_plain, method)

    def test_sistem_yoneticisi_otomatik_yetkili_degil_U3(self):
        """U-3: base.group_system Sanal POS yetkisi (iade/iptal dahil) kazandırmaz."""
        for method in self.public_actions():
            with self.subTest(method=method):
                self.assertDenied(self.user_sys, method)

    def test_kullanici_yonetici_eylemlerini_yapamaz(self):
        for method in MANAGER_ONLY:
            with self.subTest(method=method):
                self.assertDenied(self.user_sp, method)

    def test_yonetici_inceleme_eylemleri_icin_kayit_inceleme_durumunda_olmali(self):
        """Yönetici de durum dışı çağrıda (paid kayıtta review eylemi) hata alır, istek gitmez."""
        for method in ('action_review_accept', 'action_review_close'):
            with self.subTest(method=method):
                self.assertBlocked(getattr(self.paid_payment.with_user(self.user_mgr), method),
                                   '%s durum dışında reddedilmedi' % method)
        self.assertNoParatikaCalls()

    def test_yazma_silme_olusturma_rol_matrisi(self):
        payment = self.paid_payment
        line = self.make_refund_line(payment, 100.0, provider_ref='R-ACL')
        log = self.env['sanal.pos.log'].sudo().create(
            {'action': 'X', 'provider': 'paratika', 'environment': 'test', 'success': True})
        for user in (self.user_plain, self.user_sp, self.user_mgr, self.user_sys):
            for rec in (payment, line, log):
                with self.subTest(user=user.login, model=rec._name, op='unlink'):
                    self.assertBlocked(rec.with_user(user).unlink)
                with self.subTest(user=user.login, model=rec._name, op='write'):
                    self.assertBlocked(
                        lambda: rec.with_user(user).write({'create_date': '2020-01-01 00:00:00'}))
        self.assertTrue(payment.exists() and line.exists() and log.exists())

    def test_okuma_matrisi(self):
        payment = self.paid_payment
        log = self.env['sanal.pos.log'].sudo().create(
            {'action': 'X', 'provider': 'paratika', 'environment': 'test', 'success': True})
        line = self.make_refund_line(payment, 100.0, provider_ref='R-RD')
        expected = {  # kullanıcı: (ödeme, iade satırı, log)
            self.user_plain: (False, False, False),
            self.user_sys: (False, False, False),
            self.user_sp: (True, True, False),
            self.user_mgr: (True, True, True),
        }
        for user, (can_pay, can_line, can_log) in expected.items():
            for rec, allowed in ((payment, can_pay), (line, can_line), (log, can_log)):
                with self.subTest(user=user.login, model=rec._name):
                    if allowed:
                        self.assertEqual(rec.with_user(user).search([('id', '=', rec.id)]), rec)
                    else:
                        with self.assertRaises(AccessError):
                            rec.with_user(user).search([('id', '=', rec.id)])
                        with self.assertRaises(AccessError):
                            rec.with_user(user).read(['create_date'])

    def test_sihirbaz_olusturma_matrisi(self):
        allowed = {
            'sanal.pos.payment.create.wizard': (self.user_sp, self.user_mgr),
            'sanal.pos.mail.order.wizard': (self.user_sp, self.user_mgr),
            'sanal.pos.payment.resend.wizard': (self.user_sp, self.user_mgr),
            'sanal.pos.payment.refund.wizard': (self.user_mgr,),
            'sanal.pos.payment.review.close.wizard': (self.user_mgr,),
        }
        for model, users in allowed.items():
            for user in (self.user_plain, self.user_sp, self.user_mgr, self.user_sys):
                if user in users:
                    continue
                with self.subTest(model=model, user=user.login):
                    with self.assertRaises(AccessError):
                        self.env[model].with_user(user).create({})

    def test_sihirbaz_baska_kullanicinin_kaydini_okuyamaz(self):
        """Yeni-link sihirbazı faturadan gelen kişisel veriyi taşır; yalnız oluşturanı görür."""
        wiz = self.wizard(user=self.user_sp)
        self.assertEqual(wiz.customer_phone, '5321112233')
        for user in (self.user_sp2, self.user_mgr, self.user_plain, self.user_sys):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    wiz.with_user(user).read(['customer_phone', 'customer_email', 'customer_name'])

    def test_acl_tablosu_degismezleri(self):
        """ir.model.access: grupsuz (herkese açık) satır yok, hiçbir satır silme izni vermez,
        kalıcı modellerde yazma/oluşturma yok (değişiklik yalnız model metotlarıyla)."""
        Access = self.env['ir.model.access'].sudo()
        groups = self.env.ref('sanal_pos.group_sanal_pos_user') | self.env.ref('sanal_pos.group_sanal_pos_manager')
        for name in SP_MODELS:
            model = self.env['ir.model']._get(name)
            rows = Access.search([('model_id', '=', model.id)])
            self.assertTrue(rows, '%s için ACL yok' % name)
            for row in rows:
                self.assertTrue(row.group_id, '%s: grupsuz (herkese açık) ACL satırı %s' % (name, row.name))
                self.assertFalse(row.perm_unlink, '%s: silme izni %s' % (name, row.name))
                self.assertIn(row.group_id, groups, '%s: Sanal POS grubu dışında satır %s' % (name, row.name))
                if not self.env[name]._transient:
                    self.assertFalse(row.perm_write or row.perm_create,
                                     '%s: kalıcı modelde yazma/oluşturma izni %s' % (name, row.name))

    def test_kayit_kurali_yalniz_sihirbazlarda_ve_olusturana_ozel(self):
        """S-4/V-1: kalıcı modellerde kayıt kuralı yok (tek şirket, herkes tüm talepleri görür).
        Sihirbazlar (TransientModel) Odoo 19'da oluşturanla sınırlı değildir; kural bunu sağlar."""
        rules = self.env['ir.rule'].sudo().search([('model_id.model', 'in', list(SP_MODELS))])
        for rule in rules:
            self.assertTrue(self.env[rule.model_id.model]._transient,
                            'Kalıcı modelde beklenmeyen kayıt kuralı: %s' % rule.name)
            self.assertFalse(rule.groups, '%s: global kural olmalı' % rule.name)
            self.assertEqual(rule.domain_force.replace(' ', ''), "[('create_uid','=',user.id)]")
        self.assertEqual(set(rules.mapped('model_id.model')),
                         {m for m in SP_MODELS if self.env[m]._transient})


@tagged('post_install', '-at_install', 'sanal_pos')
class TestSecretSurfaces(SecurityCase):
    """KK-36: sırlar ayar ekranı dışında hiçbir okuma yolundan görünmez."""

    SECRET_PARAMS = ('sanal_pos.paratika_merchant_password', 'sanal_pos.paratika_secret_key',
                     'sanal_pos.mssql_password', 'sanal_pos.mssql_user')

    def test_config_parameter_yoneticiye_ve_kullaniciya_okunmaz(self):
        for user in (self.user_plain, self.user_sp, self.user_mgr):
            Param = self.env['ir.config_parameter'].with_user(user)
            for key in self.SECRET_PARAMS:
                with self.subTest(user=user.login, key=key):
                    with self.assertRaises(AccessError):
                        Param.get_param(key)
            with self.subTest(user=user.login, op='search_read'):
                with self.assertRaises(AccessError):
                    Param.search_read([('key', 'like', 'sanal_pos.')], ['key', 'value'])
            with self.subTest(user=user.login, op='export'):
                with self.assertRaises(AccessError):
                    Param.search([]).export_data(['key', 'value'])

    def test_ayar_modeli_yoneticiye_kapali(self):
        Settings = self.env['res.config.settings']
        for user in (self.user_plain, self.user_sp, self.user_mgr):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    Settings.with_user(user).create({})
                with self.assertRaises(AccessError):
                    Settings.with_user(user).action_copy_tailor_mssql()
                with self.assertRaises(AccessError):
                    Settings.create({}).with_user(user).action_sanal_pos_test_connection()
        self.assertNoParatikaCalls()
        # Bağlantı testi sonuç penceresi yalnız sistem yöneticisine açık
        for user in (self.user_plain, self.user_sp, self.user_mgr):
            with self.subTest(user=user.login, model='sanal.pos.connection.test.wizard'):
                with self.assertRaises(AccessError):
                    self.env['sanal.pos.connection.test.wizard'].with_user(user).create({})

    def test_g2_set_values_dogrudan_cagrisi_sistem_yoneticisine_ozel(self):
        """G-2: çekirdek set_values yönetici denetimi yapmaz (yalnız execute yapar); boş kayıt
        kümesiyle çağrı tüm config parametrelerini boş değerle ezebilirdi."""
        ICP = self.env['ir.config_parameter'].sudo()
        portal = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Test sp_portal', 'login': 'sp_portal_g2', 'email': 'sp_portal_g2@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])]})
        before = {key: ICP.get_param(key) for key in BASE_SETTINGS}
        Settings = self.env['res.config.settings']
        writes = []
        real_set_param = type(ICP).set_param

        def spy_set_param(this, key, value):
            writes.append(key)
            return real_set_param(this, key, value)

        with patch.object(type(ICP), 'set_param', spy_set_param):
            for user in (self.user_plain, self.user_sp, self.user_mgr, portal):
                with self.subTest(user=user.login, method='set_values'):
                    with self.assertRaises(AccessError):
                        Settings.with_user(user).set_values()
                    # Çekirdek, sır alanını okurken AccessError verene kadar parametreleri
                    # siliyordu (yalnız işlem geri alımı kurtarıyordu). Denetim yazmadan önce olmalı.
                    self.assertEqual(writes, [], 'yetkisiz set_values parametre yazdı')
                with self.subTest(user=user.login, method='execute'):
                    # Çekirdek execute: ensure_one + is_admin denetimi (boş kümede ValueError).
                    try:
                        with self.env.cr.savepoint():
                            Settings.with_user(user).execute()
                    except (AccessError, ValueError):
                        pass
                    else:
                        self.fail('yetkisiz execute reddedilmedi')
        self.assertEqual({key: ICP.get_param(key) for key in BASE_SETTINGS}, before)
        self.assertNotEqual(ICP.get_param('sanal_pos.require_contact'), 'False')

    def test_g2_sistem_yoneticisi_ayar_kaydedebilir(self):
        settings = self.env['res.config.settings'].with_user(self.user_sys).create(
            {'sanal_pos_require_contact': False})
        settings.execute()
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('sanal_pos.require_contact'), 'False')

    def test_ayar_alanlari_okuma_yollari_sirsiz(self):
        """fields_get + default_get: sır alanları yalnız sistem yöneticisinde."""
        secret_fields = {n for n, f in self.env['res.config.settings']._fields.items()
                         if getattr(f, 'config_parameter', None) in self.SECRET_PARAMS}
        self.assertEqual(len(secret_fields), 4, 'sır ayar alanları değişti')
        for user in (self.user_plain, self.user_sp, self.user_mgr):
            visible = self.env['res.config.settings'].with_user(user).fields_get()
            self.assertFalse(secret_fields & set(visible), 'fields_get sır alanı gösterdi: %s' % user.login)
        sys_visible = self.env['res.config.settings'].with_user(self.user_sys).fields_get()
        self.assertTrue(secret_fields <= set(sys_visible))

    def test_sir_degerleri_hicbir_ayar_okumasinda_baska_alana_sizmaz(self):
        """Sistem dışı kullanıcıların okuyabildiği ayar alanları sır değeri taşımaz."""
        settings = self.env['res.config.settings'].with_user(self.user_sys).create({})
        data = settings.read()[0]
        for fname, value in data.items():
            if fname in ('sanal_pos_paratika_merchant_password', 'sanal_pos_paratika_secret_key',
                         'sanal_pos_mssql_password', 'sanal_pos_mssql_user'):
                continue
            for label, secret in SECRETS.items():
                self.assertNotIn(secret, str(value), '%s sızdı: %s' % (label, fname))
            self.assertNotIn(MSSQL_USER, str(value))

    def test_loglar_ve_odemeler_export_edilince_sirsiz(self):
        self.create_link(channel_sms=True, channel_email=True)
        export_group = self.env.ref('base.group_allow_export')
        (self.user_mgr | self.user_sp).sudo().write({'group_ids': [(4, export_group.id)]})
        fields_log = ['action', 'request_body', 'response_body', 'error_code']
        exported = self.env['sanal.pos.log'].with_user(self.user_mgr).search([]).export_data(fields_log)
        self.assertTrue(exported['datas'])
        self.assertNoSecrets(json.dumps(exported['datas'], ensure_ascii=False), where='log export')
        fields_pay = ['invoice_no', 'customer_name', 'last_error_message', 'last_error_code', 'provider_token']
        # G-8: provider_token yalnız yöneticiye açık; Sanal POS kullanıcısı onu dışa aktaramaz
        with self.assertRaises(AccessError):
            self.env['sanal.pos.payment'].with_user(self.user_sp).search([]).export_data(fields_pay)
        for user, fnames in ((self.user_sp, fields_pay[:-1]), (self.user_mgr, fields_pay)):
            with self.subTest(user=user.login):
                exported = self.env['sanal.pos.payment'].with_user(user).search([]).export_data(fnames)
                self.assertTrue(exported['datas'])
                self.assertNoSecrets(json.dumps(exported['datas'], ensure_ascii=False),
                                     where='ödeme export')

    def test_chatter_grupsuz_kullaniciya_gorunmez(self):
        """Chatter (KK-5 notları dahil) kişisel veri taşır: model okuma yetkisi olmayan görmez."""
        payment = self.create_link(channel_sms=True, channel_email=True)
        Message = self.env['mail.message']
        self.assertTrue(Message.with_user(self.user_sp).search([('model', '=', 'sanal.pos.payment'),
                                                                ('res_id', '=', payment.id)]))
        for user in (self.user_plain, self.user_sys):
            with self.subTest(user=user.login):
                try:
                    found = Message.with_user(user).search([('model', '=', 'sanal.pos.payment'),
                                                            ('res_id', '=', payment.id)])
                except AccessError:
                    found = Message
                self.assertFalse(found, 'chatter mesajları yetkisiz kullanıcıya göründü')
                with self.assertRaises(AccessError):
                    payment.with_user(user).message_post(body='deneme')

    def test_chatter_html_enjeksiyonu_kacirilir(self):
        """Paratika'dan (veya kullanıcıdan) gelen metin chatter'a ham HTML olarak girmez."""
        evil = '<script>alert(1)</script><img src=x onerror=alert(2)>'
        self.mock.queue('PAYBYLINKPAYMENT', err_body('ERR99001', evil))
        self.user_message(self.wizard(channel_sms=True, channel_email=True).action_create_link)
        payment = self.last_payment()
        body = '\n'.join(self.env['mail.message'].sudo().search(
            [('model', '=', 'sanal.pos.payment'), ('res_id', '=', payment.id)]).mapped('body'))
        self.assertIn('Link oluşturulamadı', body)
        # Etiketler kaçırılır (&lt;...): ham '<' ile başlayan etiket kalmamalı
        self.assertNotIn('<script', body.lower())
        self.assertNotIn('<img', body.lower())


@tagged('post_install', '-at_install', 'sanal_pos')
class TestFullFlowLeaks(SecurityCase):
    """Tam akış: oluştur -> zaman aşımı -> uzlaştırma -> hata -> ödeme -> iade (hata, zaman aşımı, başarı).

    Tüm yüzeyler (log tablosu, chatter, kayıt hata alanları, Python log, kullanıcıya dönen metin)
    sır ve tam telefon için taranır (KK-37, NFR-4).
    """

    # MSSQL şifresi Paratika yanıtlarında bulunmaz; MSSQL yolu test_security'deki kk37 testlerinde sınanır.
    LEAKY = ' password=%s key=%s' % (PASSWORD, SECRET_KEY)

    def test_tam_akis_sizinti_yok(self):
        errors = []
        with self.capture_logs() as logged:
            # 1) zaman aşımı -> belirsiz
            self.mock.queue('PAYBYLINKPAYMENT', requests.exceptions.ReadTimeout('timeout' + self.LEAKY))
            errors.append(self.user_message(self.wizard(channel_sms=True, channel_email=True).action_create_link))
            self.assertEqual(self.last_payment().state, 'unknown')
            # 2) cron uzlaştırması hata alır (sır yankılar)
            self.mock.queue('QUERYTRANSACTION', err_body('ERR10001', 'q' + self.LEAKY))
            self.mock.queue('QUERYPAYBYLINKPAYMENT', requests.exceptions.ConnectionError('c' + self.LEAKY))
            self.run_cron(CRON_SYNC)
            # 3) hata yanıtı: yeni deneme için kayıt hataya düşer
            self.last_payment().sudo().write({'state': 'error'})
            self.mock.queue('PAYBYLINKPAYMENT', err_body('ERR10199', 'telefon' + self.LEAKY))
            errors.append(self.user_message(self.wizard(channel_sms=True, channel_email=True).action_create_link))
            self.last_payment().sudo().write({'state': 'error'})
            # 4) başarılı link -> ödendi
            payment = self.create_link(channel_sms=True, channel_email=True)
            self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'))
            payment.with_user(self.user_sp).action_check_status()
            self.assertEqual(payment.state, 'paid')
            # 5) iade: hata, zaman aşımı, başarı
            self.mock.queue('REFUND', err_body('ERR10031', 'iade' + self.LEAKY))
            errors.append(self.user_message(payment.with_user(self.user_mgr).action_refund, 100.0, 'Müşteri talebi'))
            self.mock.queue('REFUND', requests.exceptions.ReadTimeout('iade-zaman' + self.LEAKY))
            errors.append(self.user_message(payment.with_user(self.user_mgr).action_refund, 100.0, 'Müşteri talebi'))
            self.run_cron(CRON_SYNC)
        self.assertGreaterEqual(self.mock.count('PAYBYLINKPAYMENT'), 3)
        self.assertCleanEverywhere(logged, errors, 'tam akış')
        named = dict(self.surfaces(), **{'Python log': '\n'.join(logged), 'kullanıcı mesajı': '\n'.join(errors)})
        for where, text in named.items():
            for form in FULL_PHONE_FORMS:
                i = text.find(form)
                self.assertEqual(i, -1, 'tam telefon sızdı (%s): %s ...%s' % (where, form, text[max(0, i - 80):i + 40]))
            if where != 'chatter':  # KK-5: elle girilen e-posta denetim notuna bilerek yazılır (yalnız Sanal POS grupları okur)
                self.assertNotIn(EMAIL, text, where)
            self.assertNotIn(MSSQL_USER, text, where)

    def test_sirlar_yaniti_bozuk_govdede_de_sizmaz(self):
        """JSON olmayan / HTML hata gövdesi sırrı yankılasa bile kayıtlara ham girmez."""
        self.mock.queue('PAYBYLINKPAYMENT',
                        RawResponse(500, '<html>%s %s</html>' % (PASSWORD, SECRET_KEY), 'text/html'))
        with self.capture_logs() as logged:
            message = self.user_message(self.wizard(channel_sms=True, channel_email=True).action_create_link)
        self.assertCleanEverywhere(logged, [message], 'HTTP 500 gövdesi')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestWebhookLeaks(SanalPosHttpCase):
    """Açık (oturumsuz) uç noktalar: sır ve kişisel veri ne yanıtta, ne başlıkta, ne Python log'unda."""

    def post_hostile(self, path=NOTIFY, **extra):
        payment = self.make_payment()
        data = {'MERCHANTPAYMENTID': payment.merchant_payment_id, 'MERCHANTPASSWORD': PASSWORD,
                'secretKey': SECRET_KEY, 'CUSTOMERPHONE': '5321112233', 'CUSTOMEREMAIL': EMAIL,
                'CUSTOMERNAME': payment.customer_name, 'pan': '4508034508034509', 'hash': 'x' * 20}
        data.update(extra)
        with self.capture_logs() as logged:
            response = self.url_open(path, data=data, timeout=12)
        return payment, response, logged

    def assertNoLeak(self, texts):
        blob = '\n'.join(texts)
        for secret in list(SECRETS.values()) + ['5321112233', EMAIL, '4508034508034509', CUSTOMER_NAME]:
            self.assertNotIn(secret, blob)

    def test_bildirim_yanit_basliklari_ve_loglar_temiz(self):
        payment, response, logged = self.post_hostile()
        self.assertEqual(response.text.strip(), 'OK')
        self.assertNoLeak([response.text, str(dict(response.headers)), '\n'.join(logged), self.all_log_text()])
        self.assertNotIn('set-cookie', {k.lower() for k in response.headers})

    def test_donus_yaniti_ve_loglar_temiz(self):
        payment, response, logged = self.post_hostile(path='/sanal_pos/paratika/return')
        self.assertEqual(response.status_code, 200)
        self.assertNoLeak([response.text, str(dict(response.headers)), '\n'.join(logged), self.all_log_text()])
        self.assertNotIn(payment.merchant_payment_id, response.text)
        self.assertNotIn('set-cookie', {k.lower() for k in response.headers})

    def test_get_ve_asiri_buyuk_govde_ic_bilgi_vermez(self):
        get = self.url_open(NOTIFY, timeout=12)
        self.assertEqual(get.status_code, 405)
        big = self.url_open(NOTIFY, data={'MERCHANTPAYMENTID': 'X-1', 'pad': 'A' * 20000, 'MERCHANTPASSWORD': PASSWORD},
                            timeout=12)
        self.assertEqual(big.status_code, 413)
        for response in (get, big):
            self.assertNotIn(PASSWORD, response.text)
            self.assertNotIn('Traceback', response.text)

    def test_webhook_kayit_bilgisi_sizdirmaz_bilinen_bilinmeyen_ayni(self):
        payment, known, _ = self.post_hostile()
        unknown = self.url_open(NOTIFY, data={'MERCHANTPAYMENTID': 'NOPE-9', 'CUSTOMERPHONE': '5321112233'}, timeout=12)
        self.assertEqual((known.status_code, known.text, known.headers.get('Content-Type')),
                         (unknown.status_code, unknown.text, unknown.headers.get('Content-Type')))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestHttpRpcSurface(SanalPosHttpCase):
    """Gerçek HTTP JSON-RPC (/web/dataset/call_kw): özel metotlar ve kayıtlar uçtan uca kapalı."""

    PW = 'Pw-Hardening-12345'

    def call_kw(self, model, method, args=None, kwargs=None):
        payload = {'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                   'params': {'model': model, 'method': method, 'args': args or [], 'kwargs': kwargs or {}}}
        response = self.url_open('/web/dataset/call_kw/%s/%s' % (model, method), data=json.dumps(payload),
                                 headers={'Content-Type': 'application/json'}, timeout=15)
        self.assertLess(response.status_code, 500)
        try:
            return response.json()
        except ValueError:
            return {'error': {'message': 'json değil', 'status': response.status_code}}

    def login_as(self, user):
        user.sudo().write({'password': self.PW})
        self.authenticate(user.login, self.PW)

    def test_oturumsuz_kayitlara_ve_metotlara_erisemez(self):
        self.make_payment()
        for model, method, args in (('sanal.pos.payment', 'search_read', [[]]),
                                    ('sanal.pos.log', 'search_read', [[]]),
                                    ('sanal.pos.invoice.source.nebim', 'find_invoice', [INV_NO]),
                                    ('sanal.pos.provider.paratika', 'query_status', [[1]])):
            with self.subTest(model=model, method=method):
                body = self.call_kw(model, method, args)
                self.assertIn('error', body)
                self.assertNotIn('result', body)
                self.assertNotIn(CUSTOMER_NAME, json.dumps(body, ensure_ascii=False))
        self.assertEqual(self.mssql_calls, [])
        self.assertNoParatikaCalls()

    def test_grupsuz_kullanici_kayitlara_erisemez(self):
        self.make_payment()
        self.login_as(self.user_plain)
        for model, method, args in (('sanal.pos.payment', 'search_read', [[]]),
                                    ('sanal.pos.payment', 'action_check_status', [[1]]),
                                    ('sanal.pos.log', 'search_read', [[]])):
            with self.subTest(model=model, method=method):
                body = self.call_kw(model, method, args)
                self.assertIn('error', body)
                self.assertNotIn(CUSTOMER_NAME, json.dumps(body, ensure_ascii=False))
        self.assertNoParatikaCalls()

    def test_sanal_pos_kullanicisi_ozel_metotlari_cagiramaz(self):
        payment = self.make_paid()
        self.login_as(self.user_sp)
        for model, method, args in (
                ('sanal.pos.invoice.source.nebim', 'find_invoice', [INV_NO]),
                ('sanal.pos.provider.paratika', 'refund', [[], payment.id, 1]),
                ('sanal.pos.provider.paratika', 'query_status', [[], payment.id]),
                ('sanal.pos.payment', '_sync_status', [[payment.id]]),
                ('sanal.pos.payment', '_apply_status', [[payment.id]]),
                ('sanal.pos.payment', 'action_refund', [[payment.id], 100.0, 'Müşteri talebi']),
                ('sanal.pos.payment', 'action_void', [[payment.id], 'Müşteri vazgeçti']),
                ('sanal.pos.payment', 'unlink', [[payment.id]]),
                ('sanal.pos.payment', 'write', [[payment.id], {'amount': 1.0}])):
            with self.subTest(model=model, method=method):
                body = self.call_kw(model, method, args)
                self.assertIn('error', body, 'RPC reddedilmedi')
                self.assertNotIn('result', body)
        payment.invalidate_recordset()
        self.assertEqual((payment.state, payment.amount), ('paid', 9000.0))
        self.assertNoParatikaCalls()
        self.assertEqual(self.mssql_calls, [])

    def test_g2_set_values_rpc_ile_ayar_ezilemez(self):
        """G-2: /web/dataset/call_kw ile set_values (boş kayıt kümesi) sistem yöneticisi
        olmayan iç kullanıcı ve portal kullanıcısı için reddedilir; parametreler değişmez."""
        ICP = self.env['ir.config_parameter'].sudo()
        portal = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Test sp_portal', 'login': 'sp_portal_rpc', 'email': 'sp_portal_rpc@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])]})
        before = {key: ICP.get_param(key) for key in BASE_SETTINGS}
        for user in (self.user_sp, self.user_mgr, portal):
            self.login_as(user)
            for method in ('set_values', 'execute'):
                with self.subTest(user=user.login, method=method):
                    body = self.call_kw('res.config.settings', method, [[]])
                    self.assertIn('error', body, '%s RPC ile reddedilmedi' % method)
                    self.env.invalidate_all()
                    self.assertEqual({key: ICP.get_param(key) for key in BASE_SETTINGS}, before)
                    self.assertNotEqual(ICP.get_param('sanal_pos.require_contact'), 'False')

    def test_sanal_pos_kullanicisi_ayarlari_ve_sirlari_okuyamaz(self):
        self.login_as(self.user_sp)
        for model, method, args in (('ir.config_parameter', 'get_param', ['sanal_pos.paratika_merchant_password']),
                                    ('ir.config_parameter', 'search_read', [[('key', 'like', 'sanal_pos.')]]),
                                    ('res.config.settings', 'default_get', [['sanal_pos_paratika_secret_key']])):
            with self.subTest(model=model, method=method):
                body = self.call_kw(model, method, args)
                text = json.dumps(body, ensure_ascii=False)
                for secret in SECRETS.values():
                    self.assertNotIn(secret, text)
