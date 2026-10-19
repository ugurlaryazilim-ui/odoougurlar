"""Düzeltme turu #1 (07-guvenlik-AB, 06-inceleme-AB, 05-test-raporu-AB) regresyon testleri.

G-1 (kaynak kayda erişim sağlayıcıdan önce; sağlayıcıdan sonra istisna yok), Ö-1 (eski belirsiz hata kayıtları
migration'la belirsiz), G-3/D-6 (action_retry yalnız yönetici), G-5 (SmartADM hata metni maskeli), D-4 (eski XML
tanımsız yanıt belirsiz), D-7/B-1 (negatif elle sınır reddedilir), D-8 (numaraya özgü İYS hatası kampanyayı
bekletmez).
"""
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests.common import tagged


from .common import SmsTestCase

MAX_RETRY = 3


# ==== S1 G-1 ====
@tagged('post_install', '-at_install')
class TestG1RecordAccess(SmsTestCase):
    """Okuma yetkisi olup yazma yetkisi olmayan kayda SMS: sağlayıcıya hiç gidilmez (eskiden SMS gidiyor,
    message_post AccessError'ı kaydı geri alıyordu: günlük sınır ve iz atlatılıyordu)."""

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({'name': 'G1 Kişi'})
        as_plain = self.partner.with_user(self.plain_user)
        as_plain.check_access('read')   # ön koşul: okuyabilir
        with self.assertRaises(AccessError, msg='ön koşul: düz kullanıcı res.partner yazamamalı'):
            as_plain.check_access('write')

    def _wizard(self, res_model, res_id, number='05321234567'):
        return self.env['sms.system.send.wizard'].with_user(self.plain_user).create(
            {'number': number, 'body': 'Oltalama http://x', 'res_model': res_model, 'res_id': res_id})

    def test_g1_send_sms_yazilamayan_kayit_saglayiciya_gitmez(self):
        with self.assertRaises(AccessError):
            self.Message.with_user(self.plain_user).send_sms(
                '05321234567', 'Merhaba', record=self.partner.with_user(self.plain_user))
        self.assertEqual(self.net.turatel_calls, [], 'yetkisiz kayıt için sağlayıcı çağrıldı')

    def test_g1_sihirbaz_yolu_tekrarlarda_0_saglayici_cagrisi(self):
        self.set_param('user_daily_limit', '2')
        for i in range(5):
            wiz = self._wizard('res.partner', self.partner.id, '0532123456%d' % i)
            with self.assertRaises(AccessError):
                wiz.action_send()
        self.assertEqual(self.net.turatel_calls, [], 'sihirbaz yetkisiz kayıtla SMS gönderdi')

    def test_g1_okunamayan_kayit_da_reddedilir(self):
        lst = self.env['sms.system.list'].create({'name': 'L'})
        camp = self.env['sms.system.campaign'].create(
            {'name': 'K', 'message_type': 'info', 'list_ids': [(6, 0, lst.ids)], 'body': 'x'})
        with self.assertRaises(AccessError):
            self._wizard('sms.system.campaign', camp.id).action_send()
        self.assertEqual(self.net.turatel_calls, [])

    def test_g1_yetkili_kayitta_not_duser(self):
        msg = self.Message.with_user(self.admin_user).send_sms(
            '05321234567', 'Merhaba', record=self.partner.with_user(self.admin_user))
        self.assertEqual(msg.state, 'sent')
        bodies = ' '.join(self.partner.message_ids.mapped('body'))
        self.assertIn('SMS', bodies)

    def test_g1_not_yazimi_patlarsa_sms_kaydi_ve_sayac_kalir(self):
        def boom(record, **kwargs):
            raise AccessError('not yazılamadı')

        partner = self.partner.with_user(self.admin_user)
        with patch.object(self.env.registry['res.partner'], 'message_post', boom), \
                self.assertLogs('odoo.addons.sms_system', level='WARNING'):
            msg = self.Message.with_user(self.admin_user).with_context(sms_manual=True).send_sms(
                '05321234567', 'Merhaba', record=partner)
        self.assertEqual(len(self.net.turatel_calls), 1)
        self.assertEqual(msg.state, 'sent')
        self.env.flush_all()
        self.env.cr.execute('SELECT state, manual FROM sms_system_message WHERE id = %s', (msg.id,))
        self.assertEqual(self.env.cr.fetchone(), ('sent', True), 'SMS kaydı (günlük sınır sayacı) kalmalı')
