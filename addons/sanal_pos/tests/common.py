# -*- coding: utf-8 -*-
"""Sanal POS kabul testleri için ortak altyapı ve taklitler.

Taklitler
---------
* Paratika: ``requests.Session.send`` yamalanır (bkz. ``mocks.py``). Gerçek
  dış bağlantı yapılmaz.
* Nebim MSSQL: ``sanal.pos.invoice.source.nebim._fetch_rows(invoice_no)``
  yamalanır; ekip MSSQL'e asla bağlanmaz.
* ``sanal.pos.payment._sp_commit``: TransactionCase'te ``cr.commit()`` yasak
  olduğu için ``flush_all`` + sayaç olarak yamalanır. Sayaç ve çağrı anı
  görüntüsü (probe) ile "dış çağrıdan önce commit" kuralı doğrulanır.

Bu dosya modülün Python kodunu import ETMEZ (modül yokken de yüklenebilsin
diye); yalnız model adlarıyla çalışır.
"""
import itertools
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from odoo.tests import HttpCase, TransactionCase
from odoo.tools import html2plaintext

from .mocks import (  # noqa: F401  (testler buradan alır)
    LIVE_URL_PREFIX, TEST_URL_PREFIX, ParatikaMock, RawResponse, connection_exc,
    err_body, installment_body, make_send_patch, ok_body, qt_body, timeout_exc, tran,
)

INV_NO = 'UGR2026000012587'
CUSTOMER_NAME = 'ÇAĞRI ŞAHİN'
EMAIL = 'cagri.sahin@example.com'

PASSWORD = 'S3cretP@ss-9f2'
SECRET_KEY = 'SeCrEtKey-77aaXz'
MSSQL_PASSWORD = 'MssqlPw-123!zz'
MSSQL_USER = 'sa_sanalpos_test'

BASE_SETTINGS = {
    'web.base.url': 'https://odoo.example.com',
    'sanal_pos.provider': 'paratika',
    'sanal_pos.environment': 'test',
    'sanal_pos.paratika_merchant': 'TESTMERCHANT',
    'sanal_pos.paratika_merchant_user': 'api.user@ugurlar.test',
    'sanal_pos.paratika_merchant_password': PASSWORD,
    'sanal_pos.paratika_secret_key': SECRET_KEY,
    'sanal_pos.mssql_server': 'mssql.invalid',
    'sanal_pos.mssql_port': '1433',
    'sanal_pos.mssql_database': 'NebimV3',
    'sanal_pos.mssql_user': MSSQL_USER,
    'sanal_pos.mssql_password': MSSQL_PASSWORD,
}

CRON_SYNC = 'sanal_pos.cron_sanal_pos_sync'
# Y-1: webhook/dönüş tetiği yalnız bayraklı kayıtları işleyen ayrı cron'a kurulur
CRON_SYNC_FLAGGED = 'sanal_pos.cron_sanal_pos_sync_flagged'
CRON_DAILY = 'sanal_pos.cron_sanal_pos_daily'

OPEN_STATES = ('sending', 'sent', 'unknown')
PAID_STATES = ('paid', 'partial_refund', 'review', 'refund_pending')   # K-12
REUSABLE_STATES = ('expired', 'link_cancelled', 'error', 'voided', 'refunded')

# Mail Order (KK-17): Odoo'dan Paratika'ya giden HİÇBİR istek kart verisi taşımamalı.
# Kart bilgisi tarayıcıdan doğrudan Paratika'ya gider; sunucu tarafında bu anahtarlar bulunamaz.
CARD_PARAM_NAMES = frozenset({
    'PAN', 'CVV', 'CVC', 'CARDPAN', 'CARDCVV', 'CARDEXPIRY', 'EXPIRYMONTH', 'EXPIRYYEAR',
    'NAMEONCARD', 'CARDOWNER', 'CARDTOKEN', 'CARDHOLDER', 'CARDNUMBER',
})
MAIL_ORDER_PAY_PATH = '/sanal_pos/mail_order/pay/%d'
MAIL_ORDER_RETURN_PATH = '/sanal_pos/paratika/mo_return'
MAIL_ORDER_RESULT_PATH = '/sanal_pos/mail_order/result'
# Test kart değerleri (Luhn geçerli test PAN'ı; sızıntı aramasında benzersiz iğne olarak kullanılır)
LEAK_PAN = '4355084355084358'
LEAK_CVV = '000'
LEAK_OWNER = 'ZZQXKART TESTI'


def invoice_rows(invoice_no=INV_NO, total='9000.00', currency='TRY', lines=3, **overrides):
    """vw_TerziFaturalar v2 satırları (örnek fatura: 3 satır, 9000,00).

    Satır tutarları (1000/2000/3000) bilerek ``FaturaToplam``'a eşit
    toplanmaz: satır tutarlarını toplayan (6000) ya da FaturaToplam'ı satır
    sayısıyla toplayan (27000) bir uygulama yakalanır.
    """
    rows = []
    for i in range(lines):
        row = {
            'InvoiceHeaderID': '0A1B2C3D-0000-4000-8000-000000000001',
            'UGRFaturaNo': invoice_no,
            'FaturaTarihi': datetime(2026, 10, 19, 10, 30),
            'MusteriKodu': 'M-555',
            'MusteriAdi': CUSTOMER_NAME,
            'MusteriCep': '0532 111 22 33',
            'FaturaGSMNo': None,
            'MusteriEposta': None,
            'FaturaAdresi': None,
            'FaturaIlKodu': None,
            'FaturaIlceKodu': None,
            'ParaBirimi': currency,
            'FaturaToplam': None if total is None else Decimal(str(total)),
            'SatirTutari': Decimal(1000 * (i + 1)),
        }
        row.update(overrides)
        rows.append(row)
    return rows


def field_for_param(model, param):
    """``config_parameter`` değerine göre ayar alanı adı (alan adı tasarımda sabit değil)."""
    for name, field in model._fields.items():
        if getattr(field, 'config_parameter', None) == param:
            return name
    return None


class SanalPosMixin:
    """TransactionCase / HttpCase için ortak kurulum."""

    _payment_seq = itertools.count(1)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        for key, value in BASE_SETTINGS.items():
            ICP.set_param(key, value)
        cls.user_plain = cls._make_user('sp_plain', [])
        cls.user_sp = cls._make_user('sp_user', ['sanal_pos.group_sanal_pos_user'])
        cls.user_sp2 = cls._make_user('sp_user2', ['sanal_pos.group_sanal_pos_user'])
        cls.user_mgr = cls._make_user('sp_manager', ['sanal_pos.group_sanal_pos_manager'])
        cls.user_sys = cls._make_user('sp_sysadmin', ['base.group_system'])
        cls.try_currency = cls.env.ref('base.TRY')

    @classmethod
    def _make_user(cls, login, group_xmlids):
        group_ids = [cls.env.ref('base.group_user').id]
        group_ids += [cls.env.ref(x).id for x in group_xmlids]
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Test %s' % login,
            'login': login,
            'email': '%s@example.com' % login,
            'group_ids': [(6, 0, group_ids)],
        })

    def setUp(self):
        super().setUp()
        self.mock = ParatikaMock()
        self.mock.probe = self._probe
        self.commit_count = 0
        self.mssql_calls = []
        self.mssql_error = None
        self.invoices = {INV_NO: invoice_rows()}

        patcher = make_send_patch(self.mock)
        patcher.start()
        self.addCleanup(patcher.stop)

        test = self

        def fake_commit(this):
            this.env.flush_all()
            test.commit_count += 1

        def fake_fetch_rows(this, invoice_no):
            test.mssql_calls.append(invoice_no)
            if test.mssql_error is not None:
                raise test.mssql_error
            return [dict(r) for r in test.invoices.get(invoice_no, [])]

        for model_name, attr, func in (
            ('sanal.pos.payment', '_sp_commit', fake_commit),
            ('sanal.pos.invoice.source.nebim', '_fetch_rows', fake_fetch_rows),
        ):
            cls = type(self.env[model_name])
            p = patch.object(cls, attr, func, create=True)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._check_unexpected_actions)

    def _check_unexpected_actions(self):
        self.assertEqual(self.mock.unexpected, [],
                         'Testte tanımlı olmayan Paratika action çağrıldı')
        # KK-17 değişmezi: hiçbir testte Paratika'ya giden istekte kart verisi parametresi olmaz
        for call in self.mock.calls:
            leaked = [k for k in call.params
                      if k.upper() in CARD_PARAM_NAMES or k.upper().startswith('CARD')]
            self.assertEqual(leaked, [], 'Paratika %s isteği kart parametresi taşıyor: %s'
                             % (call.action, leaked))

    def _probe(self):
        """Paratika çağrısı anındaki durum: commit sayısı ve DB'deki (flush'sız) satırlar."""
        cr = self.env.cr
        cr.execute("SELECT merchant_payment_id, state FROM sanal_pos_payment")
        return {'commits': self.commit_count, 'rows': dict(cr.fetchall())}

    # ------------------------------------------------------------------ ayarlar
    def set_setting(self, param, value):
        """Ayarı gerçek ayar ekranı yolundan (res.config.settings.execute) değiştirir.

        Boolean ayarlar ekranda kapatılınca ir.config_parameter satırı SİLİNİR;
        ham ``set_param('False')`` bu yolu taklit etmez.
        """
        Settings = self.env['res.config.settings']
        fname = field_for_param(Settings, 'sanal_pos.%s' % param)
        self.assertTrue(fname, 'Ayar alanı yok: sanal_pos.%s' % param)
        Settings.create({fname: value}).execute()

    def get_setting_value(self, param):
        Settings = self.env['res.config.settings']
        fname = field_for_param(Settings, 'sanal_pos.%s' % param)
        self.assertTrue(fname, 'Ayar alanı yok: sanal_pos.%s' % param)
        return Settings.default_get([fname])[fname]

    # ------------------------------------------------------------------ fatura / sihirbaz
    def set_invoice(self, rows, invoice_no=INV_NO):
        self.invoices[invoice_no] = rows

    def wizard(self, user=None, invoice_no=INV_NO, fetch=True, email=EMAIL, **vals):
        """Yeni link sihirbazı: oluştur, faturayı getir, alanları yaz.

        Varsayım: sihirbaz, müşteri/kanal alanlarında ödeme modeliyle aynı
        adları kullanır (customer_name, customer_phone, customer_email,
        customer_address, customer_city, customer_zip, channel_sms,
        channel_email, expiry_hours, amount).
        """
        env = self.env(user=user or self.user_sp)
        wiz = env['sanal.pos.payment.create.wizard'].create({'invoice_no': invoice_no})
        if fetch:
            wiz.action_fetch_invoice()
        if email is not None and 'customer_email' not in vals:
            vals['customer_email'] = email
        if vals:
            wiz.write(vals)
        return wiz

    def create_link(self, **kw):
        """Sihirbazı kurup 'Link Oluştur'a basar; oluşan ödeme kaydını döndürür."""
        wiz = self.wizard(**kw)
        wiz.action_create_link()
        return self.last_payment()

    def payments(self, invoice_no=INV_NO):
        return self.env['sanal.pos.payment'].sudo().search(
            [('invoice_no', '=', invoice_no)], order='id')

    def last_payment(self, invoice_no=INV_NO):
        return self.env['sanal.pos.payment'].sudo().search(
            [('invoice_no', '=', invoice_no)], order='id desc', limit=1)

    # ------------------------------------------------------------------ kayıt üretimi
    def make_payment(self, **vals):
        """Doğrudan (sudo) ödeme kaydı; varsayılan: Gönderildi, SMS+E-posta, 9000 TL."""
        n = next(self._payment_seq)
        invoice_no = vals.pop('invoice_no', INV_NO)
        attempt_no = vals.pop('attempt_no', 1)
        now = datetime.utcnow().replace(microsecond=0)
        data = {
            'provider': 'paratika',
            'environment': 'test',
            'invoice_source': 'nebim',
            'invoice_no': invoice_no,
            'invoice_ref': '0A1B2C3D-0000-4000-8000-000000000001',
            'customer_code': 'M-555',
            'customer_name': CUSTOMER_NAME,
            'customer_phone': '5321112233',
            'customer_email': EMAIL,
            'amount': 9000.0,
            'currency_id': self.try_currency.id,
            'channel_sms': True,
            'channel_email': True,
            'expiry_hours': 168,
            'state': 'sent',
            'attempt_no': attempt_no,
            'merchant_payment_id': '%s-%s' % (invoice_no, attempt_no),
            'provider_token': 'TOK-SEED-%d' % n,
            'sent_at': now,
            'expires_at': now + timedelta(hours=168),
            'user_id': self.user_sp.id,
        }
        data.update(vals)
        payment = self.env['sanal.pos.payment'].sudo().create(data)
        # sudo ile oluşturulduğu için create_uid süper kullanıcı olur; oluşturan = user_id.
        self.env.cr.execute(
            "UPDATE sanal_pos_payment SET create_uid = %s WHERE id = %s",
            [payment.user_id.id or self.user_sp.id, payment.id])
        payment.invalidate_recordset()
        return payment

    def make_mail_order(self, **vals):
        """Doğrudan (sudo) Mail Order kaydı: Gönderildi (= kart sayfası açık), kanal yok, 1 saat."""
        n = next(self._payment_seq)
        now = datetime.utcnow().replace(microsecond=0)
        data = {
            'payment_method': 'mail_order',
            'channel_sms': False,
            'channel_email': False,
            'expiry_hours': 1,
            'provider_token': 'MOT-SEED-%d' % n,
            'expires_at': now + timedelta(minutes=55),
        }
        data.update(vals)
        return self.make_payment(**data)

    def mail_order_wizard(self, user=None, invoice_no=INV_NO, fetch=True, email=EMAIL, **vals):
        """Yeni Mail Order sihirbazı (create.wizard'ı miras alır): oluştur, faturayı getir, alanları yaz."""
        env = self.env(user=user or self.user_sp)
        wiz = env['sanal.pos.mail.order.wizard'].create({'invoice_no': invoice_no})
        if fetch:
            wiz.action_fetch_invoice()
        if email is not None and 'customer_email' not in vals:
            vals['customer_email'] = email
        if vals:
            wiz.write(vals)
        return wiz

    def create_mail_order(self, **kw):
        """Sihirbazı kurup 'Kart Sayfasını Aç'a basar; oluşan ödeme kaydını döndürür."""
        wiz = self.mail_order_wizard(**kw)
        wiz.action_create_mail_order()
        return self.last_payment()

    def make_paid(self, payment=None, paid_at=None, tran_ref='T1', **vals):
        """Ödenmiş kayıt (state='paid')."""
        payment = payment or self.make_payment()
        data = {
            'state': 'paid',
            'provider_tran_ref': tran_ref,
            'paid_at': paid_at or datetime.utcnow().replace(microsecond=0),
            'paid_amount': payment.amount,
            'installment_count': 1,
            'card_last4': '1234',
        }
        data.update(vals)
        payment.sudo().write(data)
        return payment

    def make_refund_line(self, payment, amount, kind='refund', state='done',
                         source='odoo', provider_ref=None, reason='test iade nedeni', **vals):
        data = {
            'payment_id': payment.id,
            'kind': kind,
            'amount': amount,
            'state': state,
            'source': source,
            'reason': reason,
            'user_id': self.user_mgr.id,
            'provider_ref': provider_ref,
        }
        data.update(vals)
        # Kısmi benzersiz indeks DB durumunu görür; ORM create bekleyen UPDATE'leri flush etmez.
        # Testte kardeş satırın önbellekteki durum değişikliği (ör. pending_approval -> rejected)
        # sahte indeks çakışması üretmesin (üretimde satır oluşturma savepoint içinde, flush'lı).
        self.env['sanal.pos.refund'].flush_model(['state'])
        return self.env['sanal.pos.refund'].sudo().create(data)

    def set_query_transactions(self, *transactions):
        """QUERYTRANSACTION kalıcı yanıtı."""
        body = qt_body(*transactions)
        self.mock.default('QUERYTRANSACTION', lambda p: body)

    # ------------------------------------------------------------------ gözlem
    def chatter(self, payment):
        """Ödeme kaydının chatter metni (düz metin, tüm mesajlar birleşik)."""
        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'sanal.pos.payment'), ('res_id', '=', payment.id)])
        return '\n'.join(html2plaintext(m.body or '') for m in messages)

    def notified_partners(self, payment):
        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'sanal.pos.payment'), ('res_id', '=', payment.id)])
        partners = messages.mapped('partner_ids') | messages.mapped('notification_ids.res_partner_id')
        return partners

    def notification_texts(self, payment, partner):
        """Belirli iş ortağına bildirilen (partner_ids / notification) mesajların metni."""
        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'sanal.pos.payment'), ('res_id', '=', payment.id)])
        mine = messages.filtered(
            lambda m: partner in m.partner_ids or partner in m.notification_ids.res_partner_id)
        return '\n'.join(html2plaintext(m.body or '') for m in mine)

    def cron_trigger_count(self, xmlid=CRON_SYNC):
        cron = self.env.ref(xmlid).sudo()
        return self.env['ir.cron.trigger'].sudo().search_count([('cron_id', '=', cron.id)])

    def all_log_text(self):
        """sanal.pos.log kayıtlarının tüm metni (istek+yanıt+hata)."""
        logs = self.env['sanal.pos.log'].sudo().search([])
        parts = []
        for rec in logs:
            parts += [rec.request_body or '', rec.response_body or '',
                      rec.error_code or '']
        return '\n'.join(parts)

    def run_cron(self, xmlid=CRON_SYNC):
        """Cron'un gerçek kodunu (ir.actions.server) çalıştırır; yöntem adından bağımsız."""
        cron = self.env.ref(xmlid).sudo()
        cron.ir_actions_server_id.sudo().run()

    def set_create_date(self, record, when):
        """create_date'i (ve write_date'i) geriye alır (bayat 'Gönderiliyor', 180 gün log temizliği vb.).

        NEDEN: bayat-sending yaşı write_date'ten okunur (``_sending_started_at``, K-15); oluşturulup
        dokunulmamış kayıtta ikisi eşittir.
        """
        self.env.cr.execute(
            "UPDATE %s SET create_date = %%s, write_date = %%s WHERE id = %%s" % record._table,
            [when, when, record.id])
        record.invalidate_recordset()

    def assertNoParatikaCalls(self, msg=None):
        self.assertEqual(self.mock.calls, [], msg or 'Paratika\'ya istek GİTMEMELİYDİ: %s' % self.mock.actions)

    def assertUserErrorContains(self, exc, text):
        self.assertIn(text, str(exc), 'Beklenen metin hata mesajında yok: %r / %r' % (text, str(exc)))

    @contextmanager
    def capture_logs(self):
        """Kodumuzun ürettiği logger çıktılarını (DEBUG dahil) toplar; liste döner.

        ``odoo.sql_db`` DEBUG satırları (``--log-level=test`` altında her SQL'i parametreleriyle
        yazar) test altyapısına aittir, bizim kodumuz değildir; bu yüzden yakalanmaz.
        Fixture kurulumunu yakalama BLOĞUNUN DIŞINDA yapın.
        """
        records = []

        class _Filter(logging.Filter):
            def filter(self, record):
                return not record.name.startswith(('odoo.sql_db', 'odoo.tests'))

        class _Handler(logging.Handler):
            def emit(self, record):
                try:
                    records.append(self.format(record))
                except Exception:  # pragma: no cover
                    records.append(str(record.msg))

        handler = _Handler(logging.DEBUG)
        handler.addFilter(_Filter())
        names = ('', 'odoo', 'odoo.addons.sanal_pos')
        old_levels = {}
        for name in names:
            lg = logging.getLogger(name)
            old_levels[name] = lg.level
            lg.setLevel(logging.DEBUG)
        logging.getLogger('').addHandler(handler)
        try:
            yield records
        finally:
            logging.getLogger('').removeHandler(handler)
            for name, level in old_levels.items():
                logging.getLogger(name).setLevel(level)


class SanalPosCase(SanalPosMixin, TransactionCase):
    pass


class SanalPosHttpCase(SanalPosMixin, HttpCase):
    pass


__all__ = [
    'INV_NO', 'CUSTOMER_NAME', 'EMAIL', 'PASSWORD', 'SECRET_KEY', 'MSSQL_PASSWORD',
    'MSSQL_USER', 'BASE_SETTINGS', 'CRON_SYNC', 'CRON_DAILY', 'OPEN_STATES',
    'PAID_STATES', 'REUSABLE_STATES', 'invoice_rows', 'field_for_param',
    'SanalPosCase', 'SanalPosHttpCase',
    'LIVE_URL_PREFIX', 'TEST_URL_PREFIX', 'RawResponse', 'connection_exc', 'err_body',
    'ok_body', 'qt_body', 'timeout_exc', 'tran', 'ParatikaMock', 'installment_body',
    'CARD_PARAM_NAMES', 'MAIL_ORDER_PAY_PATH', 'MAIL_ORDER_RETURN_PATH',
    'MAIL_ORDER_RESULT_PATH', 'LEAK_PAN', 'LEAK_CVV', 'LEAK_OWNER', 'CRON_SYNC_FLAGGED',
]
