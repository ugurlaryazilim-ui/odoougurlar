# -*- coding: utf-8 -*-
"""Mail Order Aşama 4 kabul testleri: dekont (PDF + e-posta) (KK-4.1 ... KK-4.7, NFR-4.1 ... NFR-4.3, K-18).

Kaynak: .ekip/20261023-mo-kart-pro/01-gereksinimler.md (Aşama 4), 02-tasarim.md §6. Testler koddan ÖNCE
yazıldı: tasarımdaki adlar kullanılır (``sanal_pos.action_report_mail_order_receipt``,
``report.sanal_pos.report_mail_order_receipt``, ``receipt_state``, ``_queue_receipt``,
``cron_sanal_pos_receipt``, ``mail_template_mail_order_receipt``, ``sanal.pos.receipt.send.wizard``).

* Hiçbir şey sınıf düzeyinde ``env.ref`` ile çözülmez; eksik model/rapor/cron ilgili testi düşürür, paketi değil.
* Paratika taklit edilir (ağ yok). SMTP taklit edilir: ``ir.mail_server.send_email`` yamalanır, giden mesaj
  ayrıştırılıp saklanır (``self.sent``); ``force_send`` + ``auto_delete`` mail.mail kaydını sildiğinden
  "kaç e-posta gitti" sorusu mail.mail sayımıyla değil bu yakalayıcıyla yanıtlanır.
* Test kipinde ``_render_qweb_pdf`` HTML döner (Odoo çekirdeği); içerik bu yüzden HTML ile doğrulanır. Gerçek PDF
  tek testte (``force_report_rendering``) üretilir; wkhtmltopdf yoksa atlanır.
* Yetki testlerinde (DERSLER: sms C5) test kullanıcısına kaydı okutan geçici ACL verilir; yoksa kayıt ACL'inin
  AccessError'ı raporun/sihirbazın kendi grup denetimini maskelerdi.
* Tarayıcı davranışı (PDF'in açılması, görünüm, e-postanın gerçek kutuya düşmesi) burada SINANAMAZ:
  04-kabul-testleri.md "Aşama 4 - elle doğrulanacak".
"""
import ast
import io
import itertools
import os
import re
import smtplib
import time
from datetime import datetime, timedelta
from email import message_from_bytes, policy
from unittest.mock import patch

from lxml import html as lxml_html

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from .common import (
    CUSTOMER_NAME, EMAIL, INV_NO, LEAK_BIN, LEAK_OWNER, LEAK_PAN, MAIL_ORDER_RETURN_PATH,
    SanalPosCase, tran,
)
from .test_mail_order_http import BODY_CARD, MoHttpCase
from .test_mail_order_result import ResultCase, norm

PAYMENT = 'sanal.pos.payment'
ATTEMPT = 'sanal.pos.payment.attempt'
WIZARD = 'sanal.pos.receipt.send.wizard'
RECEIPT_REPORT = 'sanal_pos.action_report_mail_order_receipt'
RECEIPT_REPORT_NAME = 'sanal_pos.report_mail_order_receipt'
RECEIPT_URL = '/report/pdf/sanal_pos.report_mail_order_receipt/%d'
TEMPLATE = 'sanal_pos.mail_template_mail_order_receipt'
CRON_RECEIPT = 'sanal_pos.cron_sanal_pos_receipt'
BUSY_MSG = 'Bu kayıt üzerinde başka bir işlem sürüyor; birazdan tekrar deneyin.'

COMPANY_NAME = 'Uğurlar Test A.Ş.'
COMPANY_EMAIL = 'info@ugurlar.test'
SUBJECT = '%s ödeme dekontu – Fatura %%s' % COMPANY_NAME
TINY_PNG = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')
# 12:30 UTC = 15:30 Europe/Istanbul (UTC+3, DST yok)
PAID_AT = datetime(2026, 10, 20, 12, 30, 0)
PAID_AT_LOCAL = '20.10.2026 15:30'
# Fatura 8.750,00; tahsil 9.120,40 (vade farkı 370,40): hiçbir tutar metni diğerinin alt dizisi değildir
AMOUNT, PAID_AMOUNT, SURCHARGE = 8750.0, 9120.4, '370,40'

NOT_PAID_STATES = ('sending', 'sent', 'unknown', 'error', 'expired', 'link_cancelled', 'review',
                   'refund_pending', 'partial_refund', 'refunded', 'voided')
RECEIPT_STATES = ('pending', 'sending', 'sent', 'no_email', 'failed')
BAD_EMAILS = (False, '', 'gecersiz-adres', '@example.com', 'musteri@')
SECRET_EXC = 'SECRET-EXC-MSG-91ab'
FORBIDDEN_LABELS = re.compile(r'(?i)\bcvv\b|\bcvc\b|güvenlik\s+kodu|son\s+kullanma|\bskt\b|kart\s+sahib')


def fold(text):
    """Türkçe büyük/küçük harf farkını (İ/ı) yok sayan karşılaştırma anahtarı."""
    return norm((text or '').replace('İ', 'i').replace('ı', 'i').replace('I', 'i')).lower()


class SentMail:
    """``send_email``'e giden mesajın ayrıştırılmış hali (ek içerikleri çözülmüş)."""

    def __init__(self, message, probe):
        raw = message.as_bytes()
        msg = message_from_bytes(raw, policy=policy.default)
        self.probe = probe                      # gönderim anında DB'deki {payment_id: receipt_state}
        self.subject = str(msg['Subject'] or '')
        self.to = str(msg['To'] or '')
        self.sender = str(msg['From'] or '')
        self.body = ''
        self.attachments = []                   # [(ad, metin)]
        for part in msg.walk():
            if part.is_multipart():
                continue
            payload = part.get_payload(decode=True) or b''
            charset = part.get_content_charset() or 'utf-8'
            text = payload.decode(charset, 'replace')
            if part.get_filename():
                self.attachments.append((part.get_filename(), text))
            elif part.get_content_maintype() == 'text':
                self.body += text
        headers = '\n'.join('%s: %s' % (k, v) for k, v in msg.items())
        self.everything = '\n'.join([headers, self.body] + [n + '\n' + t for n, t in self.attachments])


TS_DEFAULTS = {'invoice_no': None}


class ReceiptMixin:
    """Dekont testleri için ortak kurulum: şirket, SMTP yakalayıcı, izleme noktaları."""

    _inv_seq = itertools.count(1)

    def setUp(self):
        super().setUp()
        company = self.env.company.sudo()
        company.write({'name': COMPANY_NAME, 'email': COMPANY_EMAIL, 'logo': TINY_PNG})
        self.before = {}
        for table in ('ir_attachment', 'mail_mail', 'mail_message'):
            self.env.cr.execute('SELECT COALESCE(MAX(id), 0) FROM %s' % table)
            self.before[table] = self.env.cr.fetchone()[0]
        self.sent = []
        self.smtp_all = []
        self.smtp_error = None
        test = self

        def fake_send_email(this, message, *args, **kwargs):
            if test.smtp_error is not None:
                raise test.smtp_error
            mail = SentMail(message, test.receipt_probe())
            test.smtp_all.append(mail)
            # FİKSTÜR DÜZELTMESİ (A4-G2): gönderim açılınca chatter bildirimleri de (ör. KK-30 oluşturana
            # bildirim) SMTP'ye gider; "kaç dekont gitti" sayımına yalnız bildirim olmayan e-postalar girer.
            # PCI taraması (leak_texts) giden her e-postayı (smtp_all) tarar.
            if not test.is_notification_mail(message['Message-Id']):
                test.sent.append(mail)
            return message['Message-Id'] or '<receipt-test@example.com>'

        patcher = patch.object(type(self.env['ir.mail_server']), 'send_email', fake_send_email)
        patcher.start()
        self.addCleanup(patcher.stop)
        # FİKSTÜR DÜZELTMESİ (A4-G2): test kipinde ``ir.mail_server._disable_send()`` True döner ve
        # ``mail.mail._send`` hiçbir şey göndermeden çıkar (çekirdek: "skip sending e-mails unless
        # monkeypatched"); yakalayıcının çalışması için gönderim açılır (çekirdek MockEmail kalıbı).
        # Gönderim açılınca ``_connect__`` gerçek SMTP'ye bağlanmaya çalışır; bağlantı da taklit edilir.
        server_cls = type(self.env['ir.mail_server'])
        for name, fake in (('_disable_send', classmethod(lambda cls: False)),
                           ('_connect__', lambda this, *args, **kwargs: None)):
            enabler = patch.object(server_cls, name, fake)
            enabler.start()
            self.addCleanup(enabler.stop)

    # ------------------------------------------------------------------ izleme
    def receipt_probe(self):
        """Gönderim anındaki DB durumu (flush'sız): commit sırası (claim) denetimi için."""
        try:
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute('SELECT id, receipt_state FROM sanal_pos_payment')
                return dict(self.env.cr.fetchall())
        except Exception:      # alan henüz yok: kırmızı sebep zaten başka testlerde görünür
            return None

    def is_notification_mail(self, message_id):
        with self.env.cr.savepoint(flush=False):
            self.env.cr.execute(
                # FİKSTÜR DÜZELTMESİ (A4-G3): oturum açan HTTP testlerinde çekirdeğin "Password Changed"
                # güvenlik e-postası da SMTP'ye gider (model res.users); dekont sayımına yalnız ödeme kaydına
                # bağlı, bildirim olmayan e-postalar girer.
                'SELECT bool_or(mm.is_notification OR m.model IS DISTINCT FROM %s) FROM mail_mail mm'
                ' JOIN mail_message m ON m.id = mm.mail_message_id WHERE m.message_id = %s',
                [PAYMENT, message_id])
            return bool(self.env.cr.fetchone()[0])

    def count_notes(self, payment, needle):
        return self.chatter(payment).count(needle)

    def queued_mails(self, payment):
        # FİKSTÜR DÜZELTMESİ (A4-G2): oluşturana giden KK-30 bildirimi (message_post, is_notification)
        # dekont e-postası değildir; yalnız şablon/sihirbaz e-postaları sayılır.
        return self.env['mail.mail'].sudo().search([('model', '=', PAYMENT), ('res_id', '=', payment.id),
                                                    ('is_notification', '=', False)])

    # ------------------------------------------------------------------ fikstür
    def next_inv(self):
        return 'RCP%05d' % next(self._inv_seq)

    def paid_order(self, installments=3, paid_amount=PAID_AMOUNT, approval=None, **vals):
        """Doğrudan ``paid`` mail order (receipt_state boş): rapor/sihirbaz testleri için."""
        vals.setdefault('invoice_no', self.next_inv())
        vals.setdefault('amount', AMOUNT)
        payment = self.make_mail_order(**vals)
        self.make_paid(payment, paid_at=PAID_AT, tran_ref='PG-TRAN-777', paid_amount=paid_amount,
                       installment_count=installments, card_last4='4358')
        if approval:
            self.env[ATTEMPT].sudo().create({
                'payment_id': payment.id, 'tran_ref': 'PG-TRAN-777', 'tran_time': PAID_AT,
                'status': 'approved', 'approval_code': approval, 'installment_count': installments,
                'card_last4': '4358', 'user_id': self.user_sp.id})
        return payment

    def sync_to(self, payment, *transactions):
        self.set_query_transactions(*transactions)
        payment.sudo()._sync_status()
        payment.invalidate_recordset()
        return payment

    def paid_via_sync(self, tran_ref='PG-AP1', **vals):
        """Gerçek akış: ``sent`` kayıt, QUERYTRANSACTION onaylı satış -> senkron ``paid`` yapar."""
        payment = self.make_mail_order(**vals)
        self.sync_to(payment, tran('AP', 'SALE', '%.2f' % payment.amount, tran_ref, last4='4358'))
        self.assertEqual(payment.state, 'paid')
        return payment

    def late_review_order(self):
        """Süresi dolmuş kayda geç gelen onaylı satış -> ``review`` (REVIEW_LATE; test_mail_order kalıbı)."""
        payment = self.make_mail_order(state='expired', expires_at=datetime.utcnow() - timedelta(minutes=30))
        return self.sync_to(payment, tran('AP', 'SALE', '9000.00', 'PG-LATE', last4='4358'))

    def run_receipt_cron(self):
        self.run_cron(CRON_RECEIPT)

    def grant_internal_access(self, *model_names):
        """Gruplanmamış iç kullanıcıya geçici (test içinde geri alınan) okuma/yazma ACL'i."""
        for name in model_names:
            self.assertIn(name, self.env.registry, 'model yok: %s (Aşama 4)' % name)
            model = self.env['ir.model']._get(name)
            self.env['ir.model.access'].sudo().create({
                'name': 'test-gecici %s' % name, 'model_id': model.id,
                'group_id': self.env.ref('base.group_user').id,
                'perm_read': True, 'perm_write': True, 'perm_create': True, 'perm_unlink': False})
        self.env.registry.clear_cache()

    # ------------------------------------------------------------------ rapor
    def render_html(self, payment, user=None):
        Report = self.env['ir.actions.report']
        if user:
            Report = Report.with_user(user)
        content, kind = Report._render_qweb_html(RECEIPT_REPORT, payment.ids)
        self.assertEqual(kind, 'html')
        return content.decode('utf-8') if isinstance(content, bytes) else content

    @staticmethod
    def plain(content):
        return norm(lxml_html.fromstring(content).text_content())

    def leak_texts(self):
        """Bu testte üretilen her kalıcı/giden metin: SMTP, mail_mail, mail_message, ir_attachment, sanal_pos_*."""
        cr = self.env.cr
        found = [('smtp', mail.everything) for mail in self.smtp_all]
        cr.execute('SELECT t::text FROM mail_mail t WHERE id > %s', [self.before['mail_mail']])
        found += [('mail_mail', row) for (row,) in cr.fetchall()]
        cr.execute('SELECT t::text FROM mail_message t WHERE id > %s', [self.before['mail_message']])
        found += [('mail_message', row) for (row,) in cr.fetchall()]
        attachments = self.env['ir.attachment'].sudo().search([('id', '>', self.before['ir_attachment'])])
        for att in attachments:
            found.append(('ir_attachment', '%s\n%s' % (att.name, (att.raw or b'').decode('utf-8', 'replace'))))
        cr.execute("""SELECT table_name FROM information_schema.tables
                       WHERE table_schema = 'public' AND table_name LIKE 'sanal_pos_%'""")
        for (table,) in cr.fetchall():
            cr.execute('SELECT t::text FROM "%s" t' % table)
            found += [(table, row) for (row,) in cr.fetchall()]
        return found

    def assertNoCardLeak(self):
        for where, text in self.leak_texts():
            for needle in (LEAK_PAN, LEAK_BIN, LEAK_OWNER):
                self.assertNotIn(needle, text, '%s içinde kart verisi: %s' % (where, needle))


# ======================================================================================
# KK-4.1, KK-4.5, KK-4.4: rapor tanımı, içerik, durum/yetki denetimi
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestReceiptReport(ReceiptMixin, SanalPosCase):

    def test_kk_4_1_rapor_tanimi_group_ids_binding_yok_dosya_adi(self):
        report = self.env.ref(RECEIPT_REPORT)
        self.assertEqual(report._name, 'ir.actions.report')
        self.assertEqual(report.model, PAYMENT)
        self.assertEqual(report.report_type, 'qweb-pdf')
        self.assertEqual(report.report_name, RECEIPT_REPORT_NAME)
        self.assertEqual(report.group_ids, self.env.ref('sanal_pos.group_sanal_pos_user'),
                         'rapor yalnız group_sanal_pos_user (KK-4.5)')
        self.assertFalse(report.binding_model_id, 'Yazdır menüsünde görünmez; yalnız düğmeler (tasarım §6.1)')
        bound = self.env['ir.actions.report'].search([('binding_model_id.model', '=', PAYMENT)])
        self.assertNotIn(report, bound)
        payment = self.paid_order()
        self.assertEqual(safe_eval(report.print_report_name, {'object': payment}), 'Dekont - %s' % payment.invoice_no)

    def test_kk_4_1_icerik_alanlari(self):
        payment = self.paid_order(approval='ONAY123')
        content = self.render_html(payment, self.user_sp)
        text = self.plain(content)
        self.assertIn(COMPANY_NAME, text, 'şirket adı')
        self.assertIn('data:image', content, 'şirket logosu (external_layout)')
        self.assertIn('Ödeme Dekontu', text)
        self.assertNotIn(payment.name, ('/', False, ''))
        self.assertIn(payment.name, text, 'talep no')
        self.assertIn(payment.invoice_no, text, 'fatura no')
        self.assertIn(CUSTOMER_NAME, text, 'müşteri adı')
        self.assertIn('8.750,00', text, 'fatura tutarı')
        self.assertIn('9.120,40', text, 'ödenen tutar')
        self.assertIn(SURCHARGE, text, 'vade farkı (paid_amount - amount > 0)')
        self.assertRegex(text, r'(?i)vade\s+fark')
        self.assertRegex(text, r'(?i)(3\s*taksit|taksit[^0-9]{0,15}\b3\b)')
        self.assertIn(PAID_AT_LOCAL, text, 'ödeme zamanı Europe/Istanbul')
        self.assertNotIn('20.10.2026 12:30', text, 'UTC değil yerel saat')
        self.assertIn('PG-TRAN-777', text, 'işlem no (pgTranId)')
        self.assertIn('ONAY123', text, 'onay kodu (onaylı denemeden)')
        self.assertRegex(text, r'Mail Order\s*[·•\-–]\s*3D Secure')
        self.assertIn('**** **** **** 4358', text)
        self.assertIn('Bu belge fatura yerine geçmez', text)

    def test_kk_4_1_vade_farki_ve_onay_kodu_yoksa_gosterilmez(self):
        payment = self.paid_order(paid_amount=AMOUNT, installments=1)
        text = self.plain(self.render_html(payment, self.user_sp))
        self.assertNotRegex(text, r'(?i)vade\s+fark')
        self.assertNotRegex(text, r'(?i)onay\s+kod', 'onaylı attempt yoksa onay kodu satırı yok')
        self.assertIn('8.750,00', text)
        self.assertIn('**** **** **** 4358', text)

    def test_kk_4_1_pan_bin_skt_cvv_kart_sahibi_yok(self):
        payment = self.paid_order(approval='ONAY123')
        content = self.render_html(payment, self.user_sp)
        text = self.plain(content)
        for needle in (LEAK_PAN, LEAK_BIN, LEAK_OWNER, '4355 0843', '43550843'):
            self.assertNotIn(needle, content)
        self.assertNotRegex(text, FORBIDDEN_LABELS)
        for digits in re.findall(r'(?<![\d.,])\d{13,19}(?![\d.,])', text):
            self.fail('PAN benzeri rakam dizisi dekontta: %s' % digits[:4])

    def test_kk_4_1_paid_disi_her_durumda_usererror(self):
        for state in NOT_PAID_STATES:
            with self.subTest(state=state):
                payment = self.make_mail_order(state=state, invoice_no=self.next_inv())
                with self.assertRaises(UserError):
                    self.render_html(payment, self.user_sp)

    def test_kk_4_1_link_odemesi_icin_dekont_yok(self):
        link = self.make_payment(invoice_no=self.next_inv())
        self.make_paid(link, paid_at=PAID_AT, tran_ref='PG-LINK', card_last4='4358')
        self.assertEqual((link.payment_method, link.state), ('link', 'paid'))
        with self.assertRaises(UserError):
            self.render_html(link, self.user_sp)

    def test_kk_4_1_inceleme_kabulunden_sonra_paid_olunca_dekont_uretilir(self):
        payment = self.late_review_order()
        self.assertEqual(payment.state, 'review')
        with self.assertRaises(UserError):
            self.render_html(payment, self.user_sp)
        payment.with_user(self.user_mgr).action_review_accept()
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'paid')
        self.assertIn('**** **** **** 4358', self.plain(self.render_html(payment, self.user_sp)))

    def test_kk_4_5_grupsuz_ic_kullanici_accesserror_acl_maskelemez(self):
        payment = self.paid_order()
        self.grant_internal_access(PAYMENT)
        self.assertTrue(payment.with_user(self.user_plain).read(['invoice_no']),
                        'fikstür: kullanıcı kaydı okuyabiliyor; AccessError grup denetiminden gelmeli')
        with self.assertRaises(AccessError):
            self.render_html(payment, self.user_plain)
        for user in (self.user_sp, self.user_mgr):
            with self.subTest(user=user.login):
                self.assertIn(payment.invoice_no, self.plain(self.render_html(payment, user)))

    def test_kk_4_2_sistem_ortami_cron_ve_sablon_yolu_render_edebilir(self):
        """Cron (süper kullanıcı) ``group_sanal_pos_user`` üyesi değildir; yine de render edebilmeli."""
        payment = self.paid_order()
        self.assertTrue(self.env.su)
        self.assertIn(payment.invoice_no, self.plain(self.render_html(payment)))

    def test_nfr_4_1_gercek_pdf_tek_sayfa_5_sn(self):
        Report = self.env['ir.actions.report']
        if Report.get_wkhtmltopdf_state() != 'ok':
            self.skipTest('wkhtmltopdf yok/çalışmıyor: gerçek PDF testi atlandı (rapora yazılır)')
        # NEDEN: wkhtmltopdf varlıkları web.base.url'den ister; ulaşılamaz bir adres hemen reddedilir
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'http://127.0.0.1:1')
        payment = self.paid_order(approval='ONAY123')
        started = time.monotonic()
        pdf, kind = Report.with_user(self.user_sp).with_context(force_report_rendering=True)._render_qweb_pdf(
            RECEIPT_REPORT, payment.ids)
        elapsed = time.monotonic() - started
        self.assertEqual(kind, 'pdf')
        self.assertTrue(pdf.startswith(b'%PDF'), pdf[:20])
        self.assertLessEqual(elapsed, 5.0, 'NFR-4.1: PDF üretimi <=5 sn (%.1f sn)' % elapsed)
        from odoo.tools.pdf import PdfFileReader
        reader = PdfFileReader(io.BytesIO(pdf))
        self.assertEqual(len(reader.pages), 1, 'KK-4.1: tek sayfalık PDF')
        page = reader.pages[0]
        extract = getattr(page, 'extract_text', None) or getattr(page, 'extractText', None)
        if extract:
            text = norm(extract())
            self.assertIn('4358', text)
            self.assertIn(payment.invoice_no, text)
            for needle in (LEAK_PAN, LEAK_BIN, LEAK_OWNER):
                self.assertNotIn(needle, text)


# ======================================================================================
# KK-4.5: rapor HTTP adresi
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestReceiptHttp(ReceiptMixin, MoHttpCase):

    def get(self, payment, user=None):
        if user:
            self.login_as(user)
        return self.url_open(RECEIPT_URL % payment.id, allow_redirects=False)

    def test_kk_4_5_yetkili_kullanici_paid_dekontu_alir(self):
        payment = self.paid_order()
        response = self.get(payment, self.user_sp)
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/pdf', response.headers.get('Content-Type', ''))
        self.assertIn(payment.invoice_no.encode(), response.content)   # test kipinde HTML gövde

    def test_kk_4_5_grupsuz_ic_kullanici_403(self):
        payment = self.paid_order()
        self.grant_internal_access(PAYMENT)        # ACL maskelemesin: 403 raporun grup denetiminden gelmeli
        response = self.get(payment, self.user_plain)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(payment.invoice_no.encode(), response.content)

    def test_kk_4_5_oturumsuz_erisim_yok_herkese_acik_baglanti_yok(self):
        payment = self.paid_order()
        response = self.url_open(RECEIPT_URL % payment.id, allow_redirects=False)
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn(payment.invoice_no.encode(), response.content)
        self.assertNotIn('application/pdf', response.headers.get('Content-Type', ''))
        # olumlu çapa: aynı kayıt yetkili oturumla gerçekten alınabiliyor (aksi halde 404/500 de "geçer")
        self.assertEqual(self.get(payment, self.user_sp).status_code, 200)

    def test_kk_4_4_paid_disi_kayitta_http_dekont_uretmez(self):
        payment = self.make_mail_order(state='sent', invoice_no=self.next_inv())
        response = self.get(payment, self.user_sp)
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn(payment.invoice_no.encode(), response.content)
        self.assertLess(response.status_code, 500, 'beklenen hata (UserError) 5xx değil, istemci hatası olmalı')
        paid = self.paid_order()
        self.assertEqual(self.get(paid, self.user_sp).status_code, 200, 'olumlu çapa: paid kayıt alınır')


# ======================================================================================
# KK-4.2, KK-4.3, KK-4.7, NFR-4.2, NFR-4.3: otomatik dekont e-postası
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestReceiptMail(ReceiptMixin, SanalPosCase):

    # -- yapı ------------------------------------------------------------------------
    def test_nfr_4_2_receipt_state_alani_ve_manifest_surumu(self):
        field = self.env[PAYMENT]._fields.get('receipt_state')
        self.assertIsNotNone(field, 'receipt_state alanı yok (K-18)')
        self.assertEqual(field.type, 'selection')
        self.assertEqual({key for key, _label in field.selection}, set(RECEIPT_STATES))
        self.assertFalse(field.copy, 'copy=False')
        self.assertTrue(field.readonly, 'salt okunur')
        self.assertTrue(field.store)
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '__manifest__.py')
        with open(path, encoding='utf-8') as fh:
            version = ast.literal_eval(fh.read())['version']
        self.assertGreaterEqual(tuple(int(p) for p in version.split('.')[2:]), (1, 5, 0), version)

    def test_kk_4_2_sablon_ve_cron_tanimi(self):
        template = self.env.ref(TEMPLATE)
        self.assertEqual(template.model, PAYMENT)
        self.assertEqual(template.report_template_ids, self.env.ref(RECEIPT_REPORT))
        imd = self.env['ir.model.data'].search([('module', '=', 'sanal_pos'),
                                                ('name', '=', 'mail_template_mail_order_receipt')])
        self.assertTrue(imd.noupdate, 'şablon noupdate=1 (yönetici metni değiştirebilir)')
        payment = self.paid_order()
        subject = template._render_field('subject', payment.ids)[payment.id]
        self.assertEqual(subject, SUBJECT % payment.invoice_no)
        body = template._render_field('body_html', payment.ids)[payment.id]
        self.assertIn(payment.invoice_no, body)
        self.assertNotIn('4358', body, 'gövdede kart bilgisi yok (tasarım §6.2)')
        cron = self.env.ref(CRON_RECEIPT).sudo()
        self.assertEqual(cron.model_id.model, PAYMENT)
        self.assertTrue(cron.active)
        self.assertEqual((cron.interval_number, cron.interval_type), (10, 'minutes'))
        self.assertIn('_cron_send_receipts', cron.code)

    # -- KK-4.2 ----------------------------------------------------------------------
    def test_kk_4_2_paid_gecisinde_kuyruga_alinir_pdf_uretilmez(self):
        payment = self.make_mail_order()
        self.assertFalse(payment.receipt_state)
        self.sync_to(payment, tran('AP', 'SALE', '9000.00', 'PG-AP1', last4='4358'))
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.receipt_state, 'pending')
        self.assertGreaterEqual(self.cron_trigger_count(CRON_RECEIPT), 1, 'cron tetiklenir')
        self.assertEqual(self.sent, [], 'paid anında e-posta gitmez; cron gönderir (NFR-4.1: PDF burada üretilmez)')
        self.assertFalse(self.queued_mails(payment))

    def test_kk_4_2_cron_dekontu_gonderir_konu_ek_gonderen_chatter(self):
        payment = self.paid_via_sync()
        self.run_receipt_cron()
        payment.invalidate_recordset()
        self.assertEqual(len(self.sent), 1, 'tam bir e-posta')
        mail = self.sent[0]
        self.assertEqual(mail.subject, SUBJECT % INV_NO)
        self.assertIn(EMAIL, mail.to)
        self.assertIn(COMPANY_EMAIL, mail.sender, 'NFR-4.3: şirket e-postasıyla gider')
        self.assertEqual(len(mail.attachments), 1, 'dekont PDF eki')
        name, content = mail.attachments[0]
        self.assertIn('Dekont - %s' % INV_NO, name)
        self.assertIn(INV_NO, content, 'ek dekont içeriğini taşır (test kipinde HTML)')
        self.assertIn('4358', content)
        self.assertIn(INV_NO, mail.body)
        self.assertEqual(payment.receipt_state, 'sent')
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(self.count_notes(payment, 'Dekont %s adresine gönderildi' % EMAIL), 1)

    def test_kk_4_2_cron_gondermeden_once_sending_yazar_ve_commit_eder(self):
        payment = self.paid_via_sync()
        self.run_receipt_cron()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual((self.sent[0].probe or {}).get(payment.id), 'sending',
                         'gönderim anında DB\'de receipt_state=sending (claim + commit gönderimden önce, K-6/K-9 kalıbı)')

    def test_kk_4_2_bir_kez_cron_senkron_ve_paid_yeniden_yazim(self):
        payment = self.paid_via_sync()
        self.run_receipt_cron()
        self.assertEqual(len(self.sent), 1)
        self.sync_to(payment, tran('AP', 'SALE', '9000.00', 'PG-AP1', last4='4358'))   # ikinci senkron
        self.sync_to(payment, tran('AP', 'SALE', '9000.00', 'PG-AP1', last4='4358'))   # üçüncü senkron
        payment.sudo().write({'state': 'paid'})                                          # paid'e yeniden yazım
        payment.sudo()._queue_receipt()
        self.run_receipt_cron()
        self.run_receipt_cron()
        self.assertEqual(len(self.sent), 1, 'ikinci e-posta gitmez (KK-4.2)')
        self.assertEqual(payment.receipt_state, 'sent')
        self.assertEqual(self.count_notes(payment, 'adresine gönderildi'), 1)

    def test_kk_4_2_queue_receipt_yalniz_bos_durumda_kuyruga_alir(self):
        for state in ('sending', 'sent', 'no_email', 'failed'):
            with self.subTest(receipt_state=state):
                payment = self.paid_order(invoice_no=self.next_inv())
                payment.sudo().write({'receipt_state': state})
                payment.sudo()._queue_receipt()
                self.assertEqual(payment.receipt_state, state, 'yalnız boş -> pending geçişi kuyruğa alır')
        fresh = self.paid_order(invoice_no=self.next_inv())
        fresh.sudo()._queue_receipt()
        self.assertEqual(fresh.receipt_state, 'pending')

    def test_kk_4_2_inceleme_kabulu_de_bir_kez_kuyruga_alir(self):
        payment = self.late_review_order()
        self.assertEqual(payment.state, 'review')
        self.assertFalse(payment.receipt_state, 'inceleme durumunda dekont yok')
        payment.with_user(self.user_mgr).action_review_accept()
        payment.invalidate_recordset()
        self.assertEqual((payment.state, payment.receipt_state), ('paid', 'pending'))
        self.run_receipt_cron()
        self.run_receipt_cron()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(payment.receipt_state, 'sent')

    def test_kk_4_2_takili_sending_otomatik_yeniden_gonderilmez(self):
        payment = self.paid_order()
        payment.sudo().write({'receipt_state': 'sending'})
        self.run_receipt_cron()
        payment.invalidate_recordset()
        self.assertEqual(self.sent, [], 'çökmüş kayıt çift e-posta yerine sessizlik (K-9 ilkesi)')
        self.assertEqual(payment.receipt_state, 'sending')

    def test_kk_4_2_pending_ama_artik_paid_degilse_gonderilmez(self):
        payment = self.paid_order()
        payment.sudo().write({'receipt_state': 'pending', 'state': 'voided'})
        self.run_receipt_cron()
        payment.invalidate_recordset()
        self.assertEqual(self.sent, [], "claim koşulu state='paid' AND receipt_state='pending' (tasarım §6.2)")
        self.assertEqual(payment.receipt_state, 'pending')

    # -- KK-4.3 ----------------------------------------------------------------------
    def test_kk_4_3_eposta_yok_ya_da_gecersiz_gonderilmez_not_dusar_odeme_etkilenmez(self):
        for bad in BAD_EMAILS:
            with self.subTest(email=bad):
                payment = self.paid_via_sync(customer_email=bad, invoice_no=self.next_inv())
                self.run_receipt_cron()
                self.run_receipt_cron()
                payment.invalidate_recordset()
                self.assertEqual(self.sent, [], 'e-posta gönderilmez')
                self.assertFalse(self.queued_mails(payment))
                self.assertEqual(payment.receipt_state, 'no_email')
                self.assertEqual(payment.state, 'paid', 'ödeme durumu etkilenmez')
                self.assertEqual(self.count_notes(payment, 'Müşteri e-postası yok; dekont gönderilmedi'), 1)

    def test_kk_4_3_smtp_hatasi_odeme_paid_kalir_failed_gorunur_tekrar_denenmez(self):
        self.smtp_error = smtplib.SMTPException('SMTP kapalı')
        payment = self.paid_via_sync()
        self.run_receipt_cron()            # cron istisna fırlatmamalı (run_cron raise eder)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'paid', 'ödeme etkilenmez')
        self.assertEqual(payment.receipt_state, 'failed', 'kayıtta "Gönderilemedi" görünür')
        self.assertEqual(self.count_notes(payment, 'Dekont gönderilemedi'), 1)
        self.assertEqual(self.queued_mails(payment).mapped('state'), ['exception'])
        # senkron etkilenmez
        self.sync_to(payment, tran('AP', 'SALE', '9000.00', 'PG-AP1', last4='4358'))
        self.assertEqual(payment.state, 'paid')
        # otomatik yeniden deneme yok (bir kez kuralı); elle gönderme yolu açık
        self.smtp_error = None
        self.run_receipt_cron()
        self.assertEqual(self.sent, [])
        self.assertEqual(payment.receipt_state, 'failed')

    def test_kk_4_3_rapor_uretimi_coker_failed_yalniz_sinif_adi_loglanir(self):
        payment = self.paid_via_sync()
        Report = type(self.env['ir.actions.report'])
        original = Report._render_qweb_pdf

        def failing(this, report_ref, res_ids=None, data=None):
            raise RuntimeError(SECRET_EXC)

        with patch.object(Report, '_render_qweb_pdf', failing), self.capture_logs() as records:
            self.run_receipt_cron()
        self.assertIs(Report._render_qweb_pdf, original)
        payment.invalidate_recordset()
        self.assertEqual((payment.state, payment.receipt_state), ('paid', 'failed'))
        self.assertEqual(self.sent, [])
        logs = '\n'.join(records)
        self.assertNotIn(SECRET_EXC, logs, 'beklenmeyen istisnada yalnız sınıf adı loglanır (tasarım §6.2)')
        self.assertNotIn(SECRET_EXC, self.chatter(payment))

    def test_kk_4_3_bir_kaydin_hatasi_digerini_engellemez(self):
        first = self.paid_via_sync(invoice_no=self.next_inv())
        second = self.paid_via_sync(invoice_no=self.next_inv())
        Report = type(self.env['ir.actions.report'])
        original = Report._render_qweb_pdf

        def selective(this, report_ref, res_ids=None, data=None):
            if first.id in (res_ids or []):
                raise RuntimeError(SECRET_EXC)
            return original(this, report_ref, res_ids, data)

        with patch.object(Report, '_render_qweb_pdf', selective):
            self.run_receipt_cron()
        first.invalidate_recordset()
        second.invalidate_recordset()
        self.assertEqual(first.receipt_state, 'failed')
        self.assertEqual(second.receipt_state, 'sent')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual((first.state, second.state), ('paid', 'paid'))

    # -- KK-4.7 ----------------------------------------------------------------------
    def test_kk_4_7_link_odemesi_icin_eposta_kuyruga_girmez(self):
        link = self.make_payment(invoice_no=self.next_inv())
        self.sync_to(link, tran('AP', 'SALE', '9000.00', 'PG-L1', last4='4358'))
        self.assertEqual((link.payment_method, link.state), ('link', 'paid'))
        self.assertFalse(link.receipt_state)
        link.sudo()._queue_receipt()
        self.assertFalse(link.receipt_state, '_queue_receipt yalnız mail order için')
        self.run_receipt_cron()
        self.assertEqual(self.sent, [])
        self.assertFalse(self.queued_mails(link))

    def test_kk_4_7_iptal_akisi_dekonttan_etkilenmez_ikinci_eposta_yok(self):
        payment = self.paid_via_sync()
        self.run_receipt_cron()
        self.assertEqual(len(self.sent), 1)
        payment.with_user(self.user_mgr).action_void('Müşteri vazgeçti')
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'voided')
        self.assertEqual(payment.receipt_state, 'sent')
        self.run_receipt_cron()
        self.assertEqual(len(self.sent), 1)
        with self.assertRaises(UserError):
            self.render_html(payment, self.user_sp)


# ======================================================================================
# KK-4.6: PCI (PDF, e-posta gövdesi, ir_attachment, mail_mail)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestReceiptPci(ReceiptMixin, ResultCase):

    def test_kk_4_6_kartli_odeme_ve_dekont_sonrasi_hicbir_yerde_pan_bin_yok_yalniz_son_4(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-AP-PCI', last4='4358'))
        dirty = self.url_open(MAIL_ORDER_RETURN_PATH, method='POST', allow_redirects=False,
                              data=dict(MERCHANTPAYMENTID=payment.merchant_payment_id, **BODY_CARD))
        self.assertEqual(dirty.status_code, 200)
        page = self.result(payment)                       # dönüş sonrası sonuç sayfası senkronu ödenmiş yapar
        self.assertEqual(self.reload(payment).state, 'paid')
        self.assertEqual(payment.receipt_state, 'pending')
        self.run_receipt_cron()                           # otomatik e-posta
        self.assertEqual(payment.receipt_state, 'sent')
        wizard = self.env[WIZARD].with_user(self.user_sp).create({'payment_id': payment.id, 'email': EMAIL})
        wizard.action_send()                              # elle gönderim: mail.mail + ek kuyrukta kalır
        self.assertTrue(self.queued_mails(payment), 'kuyruktaki mail.mail da taranır')
        report = self.url_open(RECEIPT_URL % payment.id, allow_redirects=False)
        self.assertEqual(report.status_code, 200)
        for where, text in (('sonuç sayfası', page.text), ('rapor yanıtı', report.text)):
            for needle in (LEAK_PAN, LEAK_BIN, LEAK_OWNER):
                self.assertNotIn(needle, text, '%s içinde %s' % (where, needle))
        self.assertNoCardLeak()
        self.assertEqual(len(self.sent), 1)
        self.assertIn('4358', self.sent[0].attachments[0][1], 'olumlu çapa: son 4 hane dekontta var')
        self.assertIn('**** **** **** 4358', self.plain(report.text))


# ======================================================================================
# KK-4.4: elle yeniden gönderme sihirbazı
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestReceiptWizard(ReceiptMixin, SanalPosCase):

    def wiz(self, payment, email=EMAIL, user=None):
        env = self.env(user=user or self.user_sp)
        return env[WIZARD].create({'payment_id': payment.id, 'email': email})

    def test_kk_4_4_varsayilan_adres_kayittaki_eposta(self):
        payment = self.paid_order()
        defaults = self.env[WIZARD].with_user(self.user_sp).with_context(
            default_payment_id=payment.id, active_id=payment.id, active_model=PAYMENT).default_get(
            ['payment_id', 'email'])
        self.assertEqual(defaults.get('payment_id'), payment.id)
        self.assertEqual(defaults.get('email'), EMAIL)

    def test_kk_4_4_ayni_adrese_yeniden_gonderim_kuyruga_alir_not_dusar(self):
        payment = self.paid_order()
        self.wiz(payment).action_send()
        payment.invalidate_recordset()
        mails = self.queued_mails(payment)
        self.assertEqual(len(mails), 1, 'force_send=False: kuyruğa alınır (tasarım §6.3)')
        self.assertEqual(mails.state, 'outgoing')
        self.assertIn(EMAIL, mails.email_to)
        self.assertEqual(mails.subject, SUBJECT % payment.invoice_no)
        self.assertEqual(len(mails.attachment_ids), 1)
        self.assertIn('Dekont - %s' % payment.invoice_no, mails.attachment_ids.name)
        self.assertEqual(payment.receipt_state, 'sent')
        self.assertEqual(self.sent, [], 'sihirbaz anında SMTP\'ye gitmez')
        self.assertEqual(self.count_notes(payment, 'Dekont %s adresine gönderildi' % EMAIL), 1)
        self.assertNotIn('kayıttaki adres', self.chatter(payment), 'adres aynıysa fark notu yok')

    def test_kk_4_4_adres_degisikligi_notu_ve_kayit_eposta_degismez(self):
        payment = self.paid_order()
        self.wiz(payment, email='yeni.adres@example.com').action_send()
        payment.invalidate_recordset()
        self.assertIn('Dekont yeni.adres@example.com adresine gönderildi (kayıttaki adres: %s)' % EMAIL,
                      self.chatter(payment))
        mails = self.queued_mails(payment)
        self.assertEqual(len(mails), 1)
        self.assertIn('yeni.adres@example.com', mails.email_to)
        self.assertNotIn(EMAIL, mails.email_to)
        self.assertEqual(payment.customer_email, EMAIL, 'ödeme kaydının customer_email\'i değişmez (K-7)')

    def test_kk_4_4_kayitta_eposta_yoksa_adres_yazilarak_gonderilir(self):
        payment = self.paid_order(customer_email=False)
        payment.sudo().write({'receipt_state': 'no_email'})
        self.wiz(payment, email='elle.adres@example.com').action_send()
        payment.invalidate_recordset()
        self.assertEqual(payment.receipt_state, 'sent')
        self.assertFalse(payment.customer_email)
        self.assertIn('Dekont elle.adres@example.com adresine gönderildi', self.chatter(payment))

    def test_kk_4_4_her_baslangic_durumundan_sent_olur(self):
        for state in (False, 'pending', 'sending', 'no_email', 'failed', 'sent'):
            with self.subTest(receipt_state=state):
                payment = self.paid_order(invoice_no=self.next_inv())
                payment.sudo().write({'receipt_state': state})
                self.wiz(payment).action_send()
                payment.invalidate_recordset()
                self.assertEqual(payment.receipt_state, 'sent')
                self.assertEqual(payment.state, 'paid')

    def test_kk_4_4_gecersiz_adres_usererror_eposta_kuyruga_girmez(self):
        for bad in (False, '', 'gecersiz-adres', '@example.com'):
            with self.subTest(email=bad):
                payment = self.paid_order(invoice_no=self.next_inv())
                with self.assertRaises(UserError):
                    self.wiz(payment, email=bad).action_send()
                self.assertFalse(self.queued_mails(payment))
                self.assertNotIn('adresine gönderildi', self.chatter(payment))

    def test_kk_4_4_paid_disinda_usererror(self):
        for state in NOT_PAID_STATES:
            with self.subTest(state=state):
                payment = self.make_mail_order(state=state, invoice_no=self.next_inv())
                with self.assertRaises(UserError):
                    self.wiz(payment).action_send()
                self.assertFalse(self.queued_mails(payment))

    def test_kk_4_4_link_kaydinda_usererror(self):
        link = self.make_payment(invoice_no=self.next_inv())
        self.make_paid(link, paid_at=PAID_AT, tran_ref='PG-LINK', card_last4='4358')
        with self.assertRaises(UserError):
            self.wiz(link).action_send()
        self.assertFalse(self.queued_mails(link))

    def test_kk_4_5_grupsuz_kullanici_gonderemez_acl_maskelemez(self):
        payment = self.paid_order()
        self.grant_internal_access(PAYMENT, WIZARD)
        self.assertTrue(payment.with_user(self.user_plain).read(['invoice_no']))
        with self.assertRaises(AccessError):
            self.wiz(payment, user=self.user_plain).action_send()
        self.assertFalse(self.queued_mails(payment))
        self.assertNotEqual(payment.receipt_state, 'sent')

    def test_kk_4_4_kilit_mesgulse_usererror_ve_sent_yazilmaz(self):
        payment = self.paid_order()
        payment.sudo().write({'receipt_state': 'failed'})
        wizard = self.wiz(payment)
        with patch.object(type(payment), '_lock_for_provider_call', lambda this: False):
            with self.assertRaises(UserError) as ctx:
                wizard.action_send()
        self.assertIn(BUSY_MSG, str(ctx.exception))
        payment.invalidate_recordset()
        self.assertEqual(payment.receipt_state, 'failed')
        self.assertEqual(payment.state, 'paid')

    def test_kk_4_4_sihirbaz_create_uid_kurali_baska_kullanici_okuyamaz(self):
        payment = self.paid_order()
        wizard = self.wiz(payment, user=self.user_sp)
        self.assertEqual(wizard.read(['email'])[0]['email'], EMAIL)
        with self.assertRaises(AccessError):
            wizard.with_user(self.user_sp2).read(['email'])
        with self.assertRaises(AccessError):
            wizard.with_user(self.user_mgr).read(['email'])
        rules = self.env['ir.rule'].sudo().search([('model_id.model', '=', WIZARD)])
        self.assertTrue(any('create_uid' in (rule.domain_force or '') for rule in rules),
                        'PII taşıyan sihirbaza create_uid ir.rule (DERSLER: sanal_pos G12)')


# ======================================================================================
# KK-4.4: formdaki düğmeler
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestReceiptForm(ReceiptMixin, SanalPosCase):

    def arch(self):
        view = self.env[PAYMENT].get_view(view_type='form')
        return lxml_html.fromstring('<root>%s</root>' % view['arch'])

    def button(self, label):
        for node in self.arch().xpath('//button'):
            if fold(node.get('string')) == fold(label):
                return node
        self.fail('Formda "%s" düğmesi yok' % label)

    def test_kk_4_4_dugmeler_yalniz_mail_order_ve_paid_iken_gorunur(self):
        for label in ('Dekontu İndir', 'Dekontu Gönder'):
            with self.subTest(label=label):
                invisible = self.button(label).get('invisible') or ''
                self.assertIn('mail_order', invisible)
                self.assertIn('paid', invisible)
        self.assertTrue(self.arch().xpath('//field[@name="receipt_state"]'), 'receipt_state formda gösterilir')

    def test_kk_4_4_indir_dugmesi_dekont_raporunu_acar(self):
        node = self.button('Dekontu İndir')
        payment = self.paid_order()
        report = self.env.ref(RECEIPT_REPORT)
        if node.get('type') == 'object':
            action = getattr(payment.with_user(self.user_sp), node.get('name'))()
            self.assertEqual(action.get('type'), 'ir.actions.report')
            self.assertEqual(action.get('report_name'), RECEIPT_REPORT_NAME)
            for state in ('sent', 'voided', 'refunded'):
                other = self.make_mail_order(state=state, invoice_no=self.next_inv())
                with self.assertRaises(UserError):
                    getattr(other.with_user(self.user_sp), node.get('name'))()
        else:
            self.assertEqual(node.get('type'), 'action')
            name = node.get('name') or ''
            self.assertTrue(name == str(report.id) or RECEIPT_REPORT in name, name)

    def test_kk_4_4_gonder_dugmesi_sihirbazi_acar_paid_disinda_usererror(self):
        node = self.button('Dekontu Gönder')
        self.assertEqual(node.get('type'), 'object')
        payment = self.paid_order()
        action = getattr(payment.with_user(self.user_sp), node.get('name'))()
        self.assertEqual(action.get('res_model'), WIZARD)
        self.assertEqual(action.get('target'), 'new')
        for state in ('sent', 'review', 'voided', 'refunded'):
            with self.subTest(state=state):
                other = self.make_mail_order(state=state, invoice_no=self.next_inv())
                with self.assertRaises(UserError):
                    getattr(other.with_user(self.user_sp), node.get('name'))()


# ======================================================================================
# KK-3.2 / KK-4.4: sonuç sayfasında dekont bağlantısı ve e-posta durumu
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestReceiptResultPage(ReceiptMixin, ResultCase):

    STATE_WORDS = {'pending': 'gönderilecek', 'sending': 'gönderiliyor', 'sent': 'gönderildi',
                   'no_email': 'e-posta yok', 'failed': 'gönderilemedi'}

    def paid_page(self, receipt_state=False):
        payment = self.paid_order()
        payment.sudo().write({'receipt_state': receipt_state})
        return payment, self.result(self.fresh(payment))

    def test_kk_4_4_paid_sonuc_sayfasinda_dekont_baglantisi_csp_degismez(self):
        payment, response = self.paid_page('sent')
        self.assertEqual(response.status_code, 200)
        hrefs = self.doc(response).xpath('//a[contains(@href,"/report/pdf/")]/@href')
        self.assertEqual(len(hrefs), 1, hrefs)
        self.assertTrue(hrefs[0].endswith(RECEIPT_URL % payment.id), hrefs[0])
        self.assertRegex(self.doc(response).xpath('//a[contains(@href,"/report/pdf/")]')[0].text_content().lower(),
                         r'dekont')
        policy = self.csp(response)
        self.assertEqual(policy.get('default-src'), ["'none'"])
        self.assertEqual(policy.get('img-src'), ["'self'"])
        self.assertEqual(policy.get('form-action'), ["'self'"])
        self.assertNotIn('script-src', policy, 'bağlantı GET, aynı köken: CSP değişmez')
        self.assertNotIn('<script', response.text.lower())

    def test_kk_4_4_eposta_durumu_metni_her_receipt_state_icin(self):
        for state, word in self.STATE_WORDS.items():
            with self.subTest(receipt_state=state):
                payment, response = self.paid_page(state)
                self.assertEqual(response.status_code, 200)
                text = self.text(response).lower()
                self.assertIn(word, text)
                for other_state, other_word in self.STATE_WORDS.items():
                    if other_state != state:
                        self.assertNotIn(other_word, text, '%s durumunda %r görünmemeli' % (state, other_word))

    def test_kk_4_4_paid_disinda_dekont_baglantisi_ve_eposta_durumu_yok(self):
        anchor, anchor_page = self.paid_page('sent')           # olumlu çapa: paid'de bağlantı var
        self.assertIn(RECEIPT_URL % anchor.id, anchor_page.text)
        for state in ('sent', 'review', 'expired', 'error', 'voided', 'refunded'):
            with self.subTest(state=state):
                payment = self.make_mail_order(state=state, invoice_no=self.next_inv())
                response = self.result(self.fresh(payment))
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('/report/pdf/', response.text)
                for word in self.STATE_WORDS.values():
                    self.assertNotIn(word, self.text(response).lower())

    def test_kk_4_4_sonuc_sayfasi_son_4_disinda_kart_verisi_icermez(self):
        payment, response = self.paid_page('sent')
        self.assertIn('**** **** **** 4358', self.text(response))
        for needle in (LEAK_PAN, LEAK_BIN, LEAK_OWNER):
            self.assertNotIn(needle, response.text)
