# -*- coding: utf-8 -*-
"""G5 / Ekran: görünümler, menüler, uygulama ikonu. KK-17, KK-33, KK-34, KK-48 (ekran yüzü).

Görsel kısımlar (rozet renkleri, bant) elle doğrulanır; burada görünümlerin yüklenmesi,
alanların varlığı, grup bazlı menü/işlem kaydı erişimi ve ikon dosyası sınanır.
"""
import ast
import base64
import io

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import file_open

from .common import SanalPosCase

PAYMENT = 'sanal.pos.payment'
LOG = 'sanal.pos.log'


@tagged('post_install', '-at_install', 'sanal_pos')
class TestScreens(SanalPosCase):

    def views(self, model, user, types=('list', 'form', 'search')):
        result = self.env[model].with_user(user).get_views([(False, t) for t in types])
        return {t: result['views'][t]['arch'] for t in types}

    def test_g5_odeme_gorunumleri_yuklenir(self):
        views = self.views(PAYMENT, self.user_sp)
        for view_type, arch in views.items():
            self.assertTrue(arch, 'görünüm boş: %s' % view_type)

    def test_g5_islem_kaydi_gorunumleri_yonetici_icin_yuklenir(self):
        views = self.views(LOG, self.user_mgr)
        self.assertIn('response_body', views['form'])
        self.assertIn('success', views['list'])

    def test_g5_islem_kaydi_gorunumu_kullaniciya_kapali(self):
        with self.assertRaises(AccessError):
            self.views(LOG, self.user_sp)

    def test_kk33_liste_sutunlari_ve_ortam(self):
        arch = self.views(PAYMENT, self.user_sp)['list']
        for fname in ('invoice_no', 'customer_name', 'customer_phone', 'amount', 'refunded_amount',
                      'channels_display', 'state', 'user_id', 'create_date', 'expires_at',
                      'paid_at', 'environment'):
            self.assertIn('name="%s"' % fname, arch, 'liste sütunu eksik: %s' % fname)
        self.assertIn('badge', arch)

    def test_kk33_hazir_filtreler(self):
        arch = self.views(PAYMENT, self.user_sp)['search']
        for name in ('open', 'paid', 'partial_refund', 'refunded', 'voided', 'expired',
                     'link_cancelled', 'error', 'review', 'mine'):
            self.assertIn('name="%s"' % name, arch, 'hazır filtre eksik: %s' % name)

    def test_kk33_varsayilan_filtre_acik_ve_acik_filtresi_sent_unknown(self):
        action = self.env.ref('sanal_pos.action_sanal_pos_payment')
        self.assertEqual(ast.literal_eval(action.context).get('search_default_open'), 1)
        sent = self.make_payment()
        unknown = self.make_payment(invoice_no='UNK1', state='unknown')
        paid = self.make_paid(self.make_payment(invoice_no='PAID1'))
        found = self.env[PAYMENT].with_user(self.user_sp).search(
            [('state', 'in', ('sent', 'unknown'))])
        self.assertIn(sent, found)
        self.assertIn(unknown, found)
        self.assertNotIn(paid, found)

    def test_kk34_form_test_bandi_ve_hata_bandi(self):
        arch = self.views(PAYMENT, self.user_sp)['form']
        self.assertIn('TEST ORTAMI', arch)
        self.assertIn('gerçek tahsilat yapılmaz', arch)
        self.assertIn('last_error_message', arch)

    def test_kk48_form_iade_gecmisi_salt_okunur(self):
        arch = self.views(PAYMENT, self.user_sp)['form']
        self.assertIn('refund_ids', arch)
        self.assertIn('İade Geçmişi', arch)

    def test_kk17_link_adresi_ve_token_yalniz_ayar_aciksa_gorunur(self):
        arch = self.views(PAYMENT, self.user_sp)['form']
        self.assertIn('name="link_url"', arch)
        for fname in ('link_url', 'provider_token'):
            index = arch.index('name="%s"' % fname)
            self.assertIn('not link_url', arch[index:index + 400],
                          '%s link_url boşken gizlenmeli' % fname)
        self.set_setting('paratika_show_link_url', False)
        self.assertFalse(self.make_payment().with_user(self.user_sp).link_url)

    def test_g5_menuler(self):
        Menu = self.env['ir.ui.menu']
        root = self.env.ref('sanal_pos.menu_sanal_pos_root')
        visible_sp = Menu.with_user(self.user_sp)._visible_menu_ids()
        visible_mgr = Menu.with_user(self.user_mgr)._visible_menu_ids()
        payments = self.env.ref('sanal_pos.menu_sanal_pos_payments')
        logs = self.env.ref('sanal_pos.menu_sanal_pos_logs')
        self.assertEqual(payments.parent_id, root)
        self.assertIn(payments.id, visible_sp)
        self.assertNotIn(logs.id, visible_sp)
        self.assertIn(logs.id, visible_mgr)

    def test_g5_uygulama_ikonu(self):
        root = self.env.ref('sanal_pos.menu_sanal_pos_root')
        self.assertEqual(root.web_icon, 'sanal_pos,static/description/icon.png')
        self.assertTrue(root.web_icon_data, 'menü ikon verisi (web_icon_data) boş')
        with file_open('sanal_pos/static/description/icon.png', 'rb') as handle:
            data = handle.read()
        self.assertEqual(base64.b64decode(root.web_icon_data), data)
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        from PIL import Image
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.size, (256, 256))
        with file_open('sanal_pos/static/description/icon.svg', 'rb') as handle:
            self.assertIn(b'<svg', handle.read())
