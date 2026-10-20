"""KK-C4..C7, C12, C24, C25, C30 (istemci düzeyi): services/turatel_json.py, Odoo kaydı kullanılmadan.

HTTP taklidi ``common.FakeTuratelJson``: zarf, GetToken, hesap yetkisi, -1/-22/-1000/-6 GERÇEK yanıt biçimleridir
(turatel-ornek-yanitlar.md). SendSms ve GetStatus satır alan adları belgesizdir; testler tasarım §5.2'nin
toleranslı ayrıştırıcı varsayımına göre yazıldı ve "VARSAYIM" ile işaretlidir (geçiş adımı 3'te doğrulanır).
İstek sözleşmesi (Content-Type, Bearer, gövdede kimlik yok, şema dışı alan yok, sendDate/ipAddress boş,
ConfirmSms/AbortSms yok) her testte FakeTuratelJson tarafından otomatik denetlenir (SmsFakes teardown).
"""
from datetime import datetime, timezone

import requests
from odoo.tests.common import tagged

from odoo.addons.sms_system.services.turatel import TuratelError

from .common import SmsTestCase, json_err, json_ok, tail10
from .test_turatel_client import _dns_error, _reset_error

NUMBERS = ['5321234567', '5329876543', '5331112233']
CIDS = ['abcd1234-m11', 'abcd1234-m12', 'abcd1234-m13']


@tagged('post_install', '-at_install')
class TestTuratelJsonClient(SmsTestCase):

    def send(self, client, receivers=None, cids=None, **kw):
        receivers = receivers or NUMBERS[:1]
        cids = cids or CIDS[:len(receivers)]
        kw.setdefault('reference_id', cids[0])
        return client.send_sms(9254, 'TESTBASLIK', 'Merhaba', receivers, client_ids=cids, **kw)

    def assertPermanent(self, error):
        self.assertIsInstance(error, TuratelError)
        self.assertFalse(error.retryable)
        self.assertFalse(error.uncertain)

    # ── KK-C4 ──
    def test_kk_c4_get_token_adresi_ve_govdesi(self):
        client = self.json_client('info')
        client.get_token()
        call = self.net.json_calls[0]
        self.assertEqual(call['endpoint'], 'Auth/GetToken')
        self.assertEqual(call['url'], self.JSON_SINGLE_URL + '/Auth/GetToken')
        self.assertEqual(call['headers']['content-type'], 'application/json')
        self.assertEqual({k: str(v) for k, v in call['payload'].items()},
                         {'userId': '20219', 'username': 'info_user', 'password': 'info_pw'})

    def test_kk_c4_bearer_ve_govdede_kimlik_yok(self):
        client = self.json_client('info')
        self.assertEqual(client.get_credit(9254), 90680)
        self.assertEqual(self.net.json_endpoints, ['Auth/GetToken', 'Sms/GetCredit'])
        token = self.net.tj.tokens_issued[0][1]
        credit = self.net.json_calls[1]
        self.assertEqual(credit['headers']['authorization'], 'Bearer ' + token)
        self.assertEqual(credit['payload'], {'accountId': 9254})
        self.assertIs(type(credit['payload']['accountId']), int)

    def test_kk_c4_tum_uclar_sozlesmeye_uyar(self):
        """GetUserAccounts/GetOriginator/GetCredit/SendSms/GetStatus/GetStatusByTwoDates: sözleşme ihlali yok."""
        client = self.json_client('info')
        client.get_user_accounts()
        client.get_originators(9254)
        client.get_credit(9254)
        result = self.send(client)
        client.get_status(9254, packet_id=result.packet_id)
        client.get_status_between(9254, datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc),
                                  datetime(2026, 10, 19, 20, 59, 59, tzinfo=timezone.utc))
        self.assertEqual(set(self.net.json_endpoints) - {'Auth/GetToken'},
                         {'Sms/GetUserAccounts', 'Sms/GetOriginator', 'Sms/GetCredit', 'Sms/SendSms',
                          'Sms/GetStatus', 'Sms/GetStatusByTwoDates'})
        self.assertEqual(self.net.tj.violations, [])

    def test_kk_c4_bulk_istemcisi_bulksms_adresine_gider(self):
        client = self.json_client('info', service='bulk')
        client.get_credit(9254)
        self.assertTrue(all(c['service'] == 'bulksms' for c in self.net.json_calls))
        self.assertEqual(self.net.json_calls[-1]['url'], self.JSON_BULK_URL + '/Sms/GetCredit')

    def test_kk_c4_zaman_asimi_varsayilan_5_15(self):
        self.json_client('info').get_credit(9254)
        self.assertTrue(all(tuple(c['timeout']) == (5, 15) for c in self.net.json_calls), self.net.json_calls)

    def test_kk_c4_send_sms_govdesi(self):
        client = self.json_client('info')
        self.send(client, NUMBERS[:2], CIDS[:2], reference_id='REF-1', validity_minutes=1260)
        payload = self.net.json_sends[0]['payload']
        self.assertEqual(payload['accountId'], 9254)
        self.assertEqual(payload['originator'], 'TESTBASLIK')
        self.assertEqual(payload['messageText'], 'Merhaba')
        self.assertEqual([tail10(n) for n in payload['receiverList']], [tail10(n) for n in NUMBERS[:2]])
        self.assertEqual(payload['referenceId'], 'REF-1')
        self.assertIs(payload['isCheckBlackList'], False)
        self.assertEqual([p['clientId'] for p in payload['personalMessages']], CIDS[:2])
        for item in payload['personalMessages']:
            self.assertFalse(item.get('parameter'), 'Kişiselleştirme yokken parameter gönderilmez (R2)')

    def test_kk_c4_parametre_alici_sirasiyla_gider(self):
        client = self.json_client('info', service='bulk')
        self.send(client, NUMBERS[:2], CIDS[:2], parameters=[['Ayşe'], ['Mehmet']])
        payload = self.net.json_sends[0]['payload']
        self.assertEqual([p['parameter'] for p in payload['personalMessages']], [['Ayşe'], ['Mehmet']])
        self.assertEqual([p['clientId'] for p in payload['personalMessages']], CIDS[:2])

    def test_kk_c4_kara_liste_bayragi_iletilir(self):
        client = self.json_client('com', service='bulk')
        client.send_sms(65672, 'TESTBASLIK', 'Kampanya', NUMBERS[:2], client_ids=CIDS[:2], reference_id='R',
                        check_blacklist=True)   # bulksms en az 2 alıcı ister
        self.assertIs(self.net.json_sends[0]['payload']['isCheckBlackList'], True)

    # ── KK-C25 ──
    def test_kk_c25_gecerlilik_dakikasi_ayardan_gelir(self):
        client = self.json_client('info')
        self.send(client, validity_minutes=300)
        self.send(client, NUMBERS[1:2], CIDS[1:2], reference_id='R2')
        first, second = [c['payload'] for c in self.net.json_sends]
        self.assertEqual(first['validityPeriod'], 300)
        self.assertEqual(second['validityPeriod'], 1260, 'Varsayılan 1260 dakika (eski +21 saat)')
        self.assertIsNone(first.get('sendDate'))

    # ── KK-C5 ──
    def test_kk_c5_jeton_surec_bellegince_paylasilir(self):
        client = self.json_client('info')
        client.get_credit(9254)
        self.assertEqual(len(self.net.tj.tokens_issued), 1)
        client.get_credit(9254)
        client.get_originators(9254)
        self.assertEqual(len(self.net.tj.tokens_issued), 1, 'Geçerli jeton varken yeni GetToken istenmemeli')

    def test_kk_c5_ayni_kimlikli_ikinci_ornek_jetonu_paylasir(self):
        api = self.json_api()
        api.clear_token_cache()
        self.addCleanup(api.clear_token_cache)
        for _i in range(2):
            api.TuratelJsonClient(self.JSON_SINGLE_URL, '20219', 'info_user', 'info_pw').get_credit(9254)
        self.assertEqual(len(self.net.json_endpoint_calls('Auth/GetToken')), 1)

    def test_kk_c5_kimlik_hatasinda_bir_kez_yenilenir_ve_tekrar_denenir(self):
        client = self.json_client('info')
        client.get_credit(9254)
        self.net.tj.expire_tokens('info_user')        # sunucu jetonu artık tanımıyor: errorCode "-1"
        self.assertEqual(client.get_credit(9254), 90680)
        self.assertEqual(len(self.net.json_endpoint_calls('Auth/GetToken')), 2)
        self.assertEqual(len(self.net.json_endpoint_calls('Sms/GetCredit')), 3)   # 1 + (-1) + tekrar

    def test_kk_c5_ikinci_basarisizlikta_kalici_kimlik_hatasi_dongu_yok(self):
        client = self.json_client('info')
        self.net.tj.add_script('Sms/GetCredit', json_err(-1, 'Unauthorized'), json_err(-1, 'Unauthorized'),
                               json_err(-1, 'Unauthorized'))
        with self.assertRaises(TuratelError) as ctx:
            client.get_credit(9254)
        self.assertPermanent(ctx.exception)
        self.assertIn('kimlik', str(ctx.exception).lower())
        self.assertEqual(len(self.net.json_endpoint_calls('Sms/GetCredit')), 2, 'En çok 2 deneme')
        self.assertLessEqual(len(self.net.json_endpoint_calls('Auth/GetToken')), 2)
        self.assertNotIn('info_pw', str(ctx.exception))

    def test_kk_c5_send_sms_kimlik_hatasinda_en_cok_iki_istek(self):
        client = self.json_client('info')
        self.net.tj.add_script('Sms/SendSms', json_err(-1, 'Unauthorized'), json_err(-1, 'Unauthorized'),
                               json_err(-1, 'Unauthorized'))
        with self.assertRaises(TuratelError) as ctx:
            self.send(client)
        self.assertPermanent(ctx.exception)
        self.assertEqual(len(self.net.json_sends), 2)

    def test_kk_c5_http_401_de_kimlik_hatasi_sayilir(self):
        """Tasarım §5.2: errorCode -1 ya da HTTP 401 → bir yenileme + bir tekrar."""
        client = self.json_client('info')
        self.net.tj.add_script('Sms/GetCredit', 401)
        self.assertEqual(client.get_credit(9254), 90680)
        self.assertEqual(len(self.net.json_endpoint_calls('Auth/GetToken')), 2)

    def test_kk_c5_yanlis_sifre_get_token_kalici_hata(self):
        api = self.json_api()
        api.clear_token_cache()
        self.addCleanup(api.clear_token_cache)
        client = api.TuratelJsonClient(self.JSON_SINGLE_URL, '20219', 'info_user', 'YANLIS-SIFRE')
        with self.assertRaises(TuratelError) as ctx:
            client.get_credit(9254)
        self.assertPermanent(ctx.exception)
        self.assertNotIn('YANLIS-SIFRE', str(ctx.exception))
        self.assertEqual(self.net.json_endpoint_calls('Sms/GetCredit'), [])
        self.assertLessEqual(len(self.net.json_endpoint_calls('Auth/GetToken')), 2)

    def test_kk_c5_onbellek_anahtari_sifreyi_icerir(self):
        client = self.json_client('info')
        client.get_credit(9254)
        wrong = self.json_api().TuratelJsonClient(self.JSON_SINGLE_URL, '20219', 'info_user', 'baska-sifre')
        with self.assertRaises(TuratelError):
            wrong.get_credit(9254)   # başka şifreyle önbellekteki jeton kullanılmamalı
        self.assertEqual(len(self.net.json_endpoint_calls('Sms/GetCredit')), 1)

    def test_kk_c5_jeton_ve_sifre_loga_ve_veritabanina_yazilmaz(self):
        with self.capture_logs() as lines:
            client = self.json_client('info')
            client.get_credit(9254)
            self.net.tj.expire_tokens('info_user')
            client.get_credit(9254)
            self.net.tj.add_script('Sms/GetOriginator', json_err(-22, 'Unauthorized IP Address'))
            with self.assertRaises(TuratelError):
                client.get_originators(9254)
        text = '\n'.join(lines)
        for secret in ('info_pw', 'Bearer', 'TOK-info_user'):
            self.assertNotIn(secret, text)
        tokens = [t for _u, t in self.net.tj.tokens_issued]
        self.assertTrue(tokens)
        params = self.env['ir.config_parameter'].sudo().search([]).mapped('value')
        for token in tokens:
            self.assertFalse([v for v in params if v and token in v], 'Jeton ir.config_parameter içine yazıldı')

    # ── KK-C6 ──
    def test_kk_c6_basari_paket_ve_mesaj_kimlikleri_eslenir(self):
        """VARSAYIM: data={'packetId', 'messageIdList'} sayı listesi, receiverList sırasıyla (tasarım §5.2)."""
        client = self.json_client('info', service='bulk')
        result = self.send(client, NUMBERS, CIDS)
        self.assertEqual(len(self.net.json_sends), 1)
        self.assertTrue(result.packet_id)
        self.assertEqual(set(result.message_ids), set(CIDS))
        for cid in CIDS:
            truth = self.net.tj.message_by_client(cid)
            self.assertEqual(str(result.message_ids[cid]), str(truth['message_id']), 'Kimlikler karışmamalı (KK-C12)')
            self.assertEqual(str(result.packet_id), str(truth['packet_id']))
        self.assertTrue(result.raw)

    def test_kk_c6_nesne_listesi_clientid_ile_eslenir_sira_ne_olursa_olsun(self):
        """VARSAYIM: data.messages=[{messageId, clientId}] (nesne listesi → clientId ile eşle)."""
        client = self.json_client('info', service='bulk')
        response = json_ok({'packetId': 9001, 'messages': [
            {'messageId': 503, 'clientId': CIDS[2]}, {'messageId': 501, 'clientId': CIDS[0]},
            {'messageId': 502, 'clientId': CIDS[1]}]})
        self.net.tj.add_script('Sms/SendSms', response)
        result = self.send(client, NUMBERS, CIDS)
        self.assertEqual({k: str(v) for k, v in result.message_ids.items()},
                         {CIDS[0]: '501', CIDS[1]: '502', CIDS[2]: '503'})
        self.assertEqual(str(result.packet_id), '9001')

    def test_kk_c6_sayi_uyusmazsa_eslestirme_kurulmaz_ham_yanit_saklanir(self):
        client = self.json_client('info', service='bulk')
        self.net.tj.add_script('Sms/SendSms', json_ok({'packetId': 9002, 'messageIdList': [601, 602]}))
        result = self.send(client, NUMBERS, CIDS)
        self.assertEqual(dict(result.message_ids), {}, 'Tahmin yürütülmez: eşleme durum cron\'una kalır')
        self.assertEqual(str(result.packet_id), '9002')
        self.assertIn('9002', str(result.raw))

    def test_kk_c6_ip_hatasi_kalici_ve_tekrar_yok(self):
        client = self.json_client('info')
        self.net.tj.add_script('Sms/SendSms', json_err(-22, 'Unauthorized IP Address'))
        with self.assertRaises(TuratelError) as ctx:
            self.send(client)
        self.assertPermanent(ctx.exception)
        self.assertIn("Sunucu IP'si Turatel'de yetkili değil", str(ctx.exception))
        self.assertEqual(len(self.net.json_sends), 1)

    def test_kk_c6_1000_yanlis_kimlik_seti_kalici_ve_tekrar_yok(self):
        """Bilgi seti reklam hesabıyla (65672) gönderirse sunucu -1000 verir (gerçek C0 yanıtı)."""
        client = self.json_client('info', service='bulk')
        with self.assertRaises(TuratelError) as ctx:
            client.send_sms(65672, 'TESTBASLIK', 'Kampanya', NUMBERS[:1], client_ids=CIDS[:1], reference_id='R',
                            check_blacklist=True)
        self.assertPermanent(ctx.exception)
        self.assertIn('Hesap bu Turatel kullanıcısında tanımlı değil', str(ctx.exception))
        self.assertIn('-1000', str(ctx.exception))
        self.assertEqual(len(self.net.json_sends), 1)
        self.assertEqual(len(self.net.json_endpoint_calls('Auth/GetToken')), 1, '-1000 jeton yenilemesi değildir')

    def test_kk_c6_diger_hatalar_kalici_turatel_hatasi_kod_mesaj(self):
        client = self.json_client('info')
        self.net.tj.add_script('Sms/SendSms', json_err('-10', 'Insufficient credit'))
        with self.assertRaises(TuratelError) as ctx:
            self.send(client)
        self.assertPermanent(ctx.exception)
        self.assertEqual(str(ctx.exception), 'Turatel hatası -10: Insufficient credit')
        self.assertEqual(len(self.net.json_sends), 1)

    def test_kk_c6_mesajsiz_hata_cokmez(self):
        client = self.json_client('info')
        self.net.tj.add_script('Sms/SendSms', json_err(-5, None))
        with self.assertRaises(TuratelError) as ctx:
            self.send(client)
        self.assertPermanent(ctx.exception)
        self.assertIn('-5', str(ctx.exception))
        self.assertNotIn('None', str(ctx.exception))

    def test_kk_c6_error_code_sayi_olarak_gelirse_de_eslenir(self):
        client = self.json_client('info', service='bulk')
        self.net.tj.add_script('Sms/SendSms',
                               {'isSuccess': False, 'errorCode': -1000, 'message': 'x', 'data': None},
                               {'isSuccess': False, 'errorCode': -22, 'message': 'x', 'data': None})
        with self.assertRaises(TuratelError) as ctx:
            self.send(client)
        self.assertIn('-1000', str(ctx.exception))
        with self.assertRaises(TuratelError) as ctx:
            self.send(client)
        self.assertIn("Sunucu IP'si", str(ctx.exception))

    def test_kk_c6_anahtarlar_buyuk_kucuk_harf_duyarsiz(self):
        client = self.json_client('info')
        self.net.tj.add_script('Sms/GetCredit', {'IsSuccess': True, 'ErrorCode': None, 'Message': None,
                                                 'Data': {'Amount': 77}})
        self.assertEqual(client.get_credit(9254), 77)

    def test_kk_c6_gecici_baglanti_hatalari_retryable(self):
        client = self.json_client('info')
        for label, error in (('ConnectTimeout', requests.exceptions.ConnectTimeout()), ('DNS', _dns_error())):
            with self.subTest(hata=label):
                self.net.tj.add_script('Sms/SendSms', error)
                with self.assertRaises(TuratelError) as ctx:
                    self.send(client)
                self.assertTrue(ctx.exception.retryable)
                self.assertFalse(ctx.exception.uncertain)
        self.assertEqual(len(self.net.json_sends), 2, 'İstemci kendi kendine yeniden göndermez')

    def test_kk_c6_belirsiz_sonuclar_uncertain(self):
        client = self.json_client('info')
        cases = (('ReadTimeout', requests.exceptions.ReadTimeout()), ('HTTP500', 500), ('HTTP502', 502),
                 ('HTML', '<html>Bakımda</html>'), ('bos', ''), ('baglanti-koptu', _reset_error()))
        for label, outcome in cases:
            with self.subTest(durum=label):
                self.net.tj.add_script('Sms/SendSms', outcome)
                with self.assertRaises(TuratelError) as ctx:
                    self.send(client)
                self.assertTrue(ctx.exception.uncertain, '%s belirsiz sayılmalı' % label)
                self.assertFalse(ctx.exception.retryable)
        self.assertEqual(len(self.net.json_sends), len(cases), 'Belirsiz sonuçta istemci tekrar göndermez')

    def test_kk_c6_get_token_baglanti_hatasi_retryable(self):
        client = self.json_client('info')
        self.net.tj.add_script('Auth/GetToken', requests.exceptions.ConnectTimeout())
        with self.assertRaises(TuratelError) as ctx:
            self.send(client)
        self.assertTrue(ctx.exception.retryable)
        self.assertEqual(self.net.json_sends, [], 'Jeton alınamadıysa SendSms hiç gitmez')

    def test_kk_c6_okuma_uclari_hatada_hata_verir(self):
        client = self.json_client('info')
        cases = (('credit', 'Sms/GetCredit', lambda: client.get_credit(9254)),
                 ('originator', 'Sms/GetOriginator', lambda: client.get_originators(9254)),
                 ('accounts', 'Sms/GetUserAccounts', lambda: client.get_user_accounts()))
        for label, endpoint, call in cases:
            for outcome in (requests.exceptions.ReadTimeout(), 500, '<html/>', json_err(-22, 'Unauthorized IP Address')):
                with self.subTest(uc=label, sonuc=repr(outcome)[:30]):
                    self.net.tj.add_script(endpoint, outcome)
                    with self.assertRaises(TuratelError):
                        call()

    def test_kk_c6_minus_6_yalniz_durum_uclarinda_bos_liste(self):
        client = self.json_client('info')
        self.net.tj.status_empty = True    # gerçek C0: errorCode "-6", message null
        self.assertEqual(client.get_status_between(9254, datetime(2026, 10, 18, 21, 0, tzinfo=timezone.utc),
                                                   datetime(2026, 10, 19, 20, 59, 59, tzinfo=timezone.utc)), [])
        self.assertEqual(client.get_status(9254, packet_id=4001), [])
        self.net.tj.add_script('Sms/GetCredit', json_err(-6, None))
        with self.assertRaises(TuratelError):
            client.get_credit(9254)
        self.net.tj.add_script('Sms/SendSms', json_err(-6, None))
        with self.assertRaises(TuratelError):
            self.send(client)

    def test_kk_c6_minus_6_hata_logu_yazmaz(self):
        client = self.json_client('info')
        self.net.tj.status_empty = True
        with self.capture_logs() as lines:
            client.get_status_between(9254, datetime(2026, 10, 18, 21, 0, tzinfo=timezone.utc),
                                      datetime(2026, 10, 19, 20, 59, 59, tzinfo=timezone.utc))
        self.assertEqual([ln for ln in lines if ln.startswith(('ERROR', 'WARNING'))], [])

    # ── KK-C7 ──
    def test_kk_c7_durum_satirlari_kimlik_ve_kodla_doner(self):
        """Canlı satır: {messageId, packetId, receiver, status, deliveryDate, reason}; clientId varsa eşleşir;
        data={'statusList': [...]} ya da çıplak liste. Satır kodu: reason doluysa o, değilse status:N."""
        client = self.json_client('info', service='bulk')
        result = self.send(client, NUMBERS, CIDS)
        truth = {cid: self.net.tj.message_by_client(cid) for cid in CIDS}
        self.net.tj.set_code(truth[CIDS[1]]['message_id'], 114)
        for shape in ('dict', 'list'):
            with self.subTest(sekil=shape):
                self.net.tj.status_shape = shape
                rows = client.get_status(9254, packet_id=result.packet_id)
                by_client = {r.client_id: r for r in rows}
                self.assertEqual(set(by_client), set(CIDS))
                self.assertEqual(str(by_client[CIDS[1]].code), '114')
                self.assertEqual(str(by_client[CIDS[1]].reason), '114')
                self.assertEqual(str(by_client[CIDS[0]].code), 'status:1')
                self.assertEqual(str(by_client[CIDS[0]].status), '1')
                self.assertEqual(len(by_client[CIDS[0]].delivery_date), 12)
                self.assertFalse(by_client[CIDS[0]].reason)
                self.assertEqual(str(by_client[CIDS[1]].message_id), str(truth[CIDS[1]]['message_id']))
                self.assertTrue(by_client[CIDS[1]].raw)

    def test_kk_c7_iki_tarih_arasi_sorgu_tarih_bicimi(self):
        client = self.json_client('info')
        self.send(client)
        start = datetime(2026, 10, 18, 21, 0, 0, tzinfo=timezone.utc)   # 19.10 00:00:00 İstanbul
        end = datetime(2026, 10, 19, 20, 59, 59, tzinfo=timezone.utc)   # 19.10 23:59:59 İstanbul
        rows = client.get_status_between(9254, start, end)
        self.assertEqual(len(rows), 1)
        payload = self.net.json_endpoint_calls('Sms/GetStatusByTwoDates')[0]['payload']
        self.assertEqual((payload['startDate'], payload['endDate']), ('191026000000', '191026235959'))

    def test_kk_c7_format_date_istanbul_ddMMyyHHmmss(self):
        api = self.json_api()
        self.assertEqual(api.format_date(datetime(2026, 10, 19, 15, 30, 45, tzinfo=timezone.utc)), '191026183045')
        self.assertEqual(api.format_date(datetime(2026, 12, 31, 21, 0, 0, tzinfo=timezone.utc)), '010127000000')

    def test_kk_c7_iletim_kodlari_eslemesi(self):
        """Ret/operatör kodları GetStatus `reason` alanında gelir (Turatel cevabı 2) → iletilemedi."""
        api = self.json_api()
        keywords = {103: ('yetki',), 114: ('kapal', 'kapsam'), -104001: ('kara liste',), -8000: ('iys', 'İYS'),
                    -467: ('uzun', 'concat', 'karakter'), -441: ('başlık', 'originator')}
        labels = set()
        for code, words in keywords.items():
            for value in (code, str(code)):
                with self.subTest(kod=value):
                    state, label = api.delivery_state(value)
                    self.assertEqual(state, 'undelivered')
                    self.assertTrue(label and label.strip())
                    self.assertTrue(any(w.lower() in label.lower() for w in words),
                                    'Kodun Türkçe açıklaması gösterilmeli: %r' % label)
            labels.add(api.delivery_state(code)[1])
        self.assertEqual(len(labels), 6, 'Her kodun kendi açıklaması olmalı')

    def test_kk_c7_bilinmeyen_reason_iletilemedi_ham_kodla(self):
        api = self.json_api()
        for code in (999, '999', -31337):
            state, label = api.delivery_state(code)
            self.assertEqual(state, 'undelivered')
            self.assertEqual(label, 'iletilemedi (kod %s)' % code)

    def test_canli_veri_status_reason_delivery_date_eslemesi(self):
        """Canlı veri: status 1 + deliveryDate dolu = ulaştı; status 0/2 = bekliyor; reason = ret kodu."""
        api = self.json_api()
        date = '201026123000'
        cases = [
            # (status, reason, deliveryDate, kod, durum)
            (1, '', date, 'status:1', 'delivered'),
            ('1', None, date, 'status:1', 'delivered'),
            (1, '0', date, 'status:1', 'delivered'),
            (0, '', '', 'status:0', 'pending'),
            (0, '0', '', 'status:0', 'pending'),
            (2, '', '', 'status:2', 'pending'),
            (1, '', '', 'status:1:tarih-yok', 'pending'),
            (None, '', '', '', 'pending'),
            (1, '114', '', '114', 'undelivered'),
            (2, '114', '', '114', 'undelivered'),
            (1, '-8000', date, '-8000', 'undelivered'),
            (1, '555', '', '555', 'undelivered'),
            (5, '', '', 'status:5', 'unknown'),
            (-3, '', date, 'status:-3', 'unknown'),
        ]
        for status, reason, delivery_date, code, state in cases:
            with self.subTest(status=status, reason=reason, tarih=delivery_date):
                self.assertEqual(api.status_code(status, reason, delivery_date), code)
                self.assertEqual(api.delivery_state(code)[0], state)

    def test_canli_veri_etiketler(self):
        api = self.json_api()
        self.assertEqual(api.delivery_state('status:1'), ('delivered', 'iletildi'))
        self.assertIn('onay', api.delivery_state('status:0')[1])
        self.assertEqual(api.delivery_state('status:0')[0], 'pending')
        self.assertIn('rapor bekleniyor', api.delivery_state('status:2')[1])
        self.assertNotEqual(api.delivery_state('status:0')[1], api.delivery_state('status:2')[1])
        self.assertEqual(api.delivery_state('status:7'), ('unknown', 'bilinmeyen (durum 7)'))
        self.assertEqual(api.delivery_state(''), ('pending', 'yanıt bekleniyor'))
        self.assertEqual(api.delivery_state(None), ('pending', 'yanıt bekleniyor'))
        # Eski sürümün yanlış 'iletildi' işaretlediği ham kod 0: artık doğrulanmamış sayılır
        self.assertEqual(api.delivery_state('0')[0], 'unknown')
        self.assertNotEqual(api.delivery_state('0')[1], 'iletildi')

    def test_canli_veri_ham_satir_ayristirma(self):
        api = self.json_api()
        row = {'messageId': 9100000001, 'packetId': 4100000001, 'receiver': '+905321234567', 'messageSize': 1,
               'personalParameter': '[]', 'status': 1, 'deliveryDate': '201026123000', 'reason': ''}
        for payload, code, state in (
                (dict(row), 'status:1', 'delivered'),
                (dict(row, status=0, deliveryDate=''), 'status:0', 'pending'),
                (dict(row, status=2, deliveryDate=''), 'status:2', 'pending'),
                (dict(row, status=2, deliveryDate='', reason='114'), '114', 'undelivered'),
                (dict(row, deliveryDate=''), 'status:1:tarih-yok', 'pending'),
                (dict(row, status=9), 'status:9', 'unknown'),
                ({k: v for k, v in row.items() if k not in ('status', 'reason', 'deliveryDate')}, '', 'pending')):
            with self.subTest(code=code):
                rows = api.TuratelJsonClient._status_rows({'statusList': [payload]})
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0].code, api.delivery_state(rows[0].code)[0]), (code, state))
                self.assertEqual(rows[0].message_id, '9100000001')
                self.assertNotIn('5321234567', rows[0].raw, 'Telefon ham raporda maskeli olmalı')

    def test_status_row_eski_dort_alanli_cagri_calisir(self):
        api = self.json_api()
        row = api.StatusRow('1', None, 'status:2', '{}')
        self.assertEqual((row.status, row.reason, row.delivery_date), (None, None, None))

    # ── KK-C12 / KK-C13 istemci ──
    def test_kk_c12_uc_alicili_paket_kimlikleri_karismaz(self):
        client = self.json_client('info', service='bulk')
        result = self.send(client, NUMBERS, CIDS, reference_id='PAKET-1')
        mids = [str(result.message_ids[c]) for c in CIDS]
        self.assertEqual(len(set(mids)), 3)
        for cid, number in zip(CIDS, NUMBERS):
            truth = self.net.tj.message_by_client(cid)
            self.assertEqual(tail10(truth['number']), tail10(number))
            self.assertEqual(str(result.message_ids[cid]), str(truth['message_id']))
        self.assertEqual(self.net.json_sends[0]['payload']['referenceId'], 'PAKET-1')

    # ── KK-C24 ──
    def test_kk_c24_json_parca_sayisi_gsm7(self):
        count = self.json_api().json_segment_count
        for length, expected in ((1, 1), (160, 1), (161, 2), (306, 2), (307, 3), (459, 3), (460, 4)):
            with self.subTest(uzunluk=length):
                self.assertEqual(count('a' * length), expected)

    def test_kk_c24_turkce_harfler_gsm7_sayilir(self):
        count = self.json_api().json_segment_count
        self.assertEqual(count('ışğİŞĞçöü' * 17 + 'a'), 1)   # 154 karakter: Türkçe harf 70/67'ye düşürmez
        self.assertEqual(count('ş' * 160), 1)
        self.assertEqual(count('ş' * 161), 2)

    def test_kk_c24_gsm7_disi_karakter_70_67(self):
        count = self.json_api().json_segment_count
        for text, expected in (('a' * 69 + '中', 1), ('a' * 70 + '中', 2), ('中' * 134, 2), ('中' * 135, 3),
                               ('Merhaba 😀', 1)):
            with self.subTest(metin=text[:12], uzunluk=len(text)):
                self.assertEqual(count(text), expected)

    def test_kk_c24_bos_metin(self):
        self.assertIn(self.json_api().json_segment_count(''), (0, 1))

    # ── KK-C3 okuma uçları (istemci) ──
    def test_kk_c3_hesaplar_baslıklar_kredi_gercek_yanit_bicimleriyle(self):
        client = self.json_client('info')
        accounts = client.get_user_accounts()
        self.assertEqual([(int(a['accountId']), a['accountName']) for a in accounts], [(9254, 'hesap_9254')])
        self.assertEqual(client.get_originators(9254), ['UGURLARGRUP', 'TESTBASLIK'])
        self.assertEqual(client.get_credit(9254), 90680)

    # ── KK-C30 ──
    def test_kk_c30_her_set_kendi_jetonunu_alir_ve_karismaz(self):
        info = self.json_client('info', service='bulk')
        com = self.json_api().TuratelJsonClient(self.JSON_BULK_URL, '20219', 'com_user', 'com_pw')
        info.get_credit(9254)
        com.get_credit(65672)
        info.get_credit(9254)
        com.get_credit(65672)
        self.assertEqual([u for u, _t in self.net.tj.tokens_issued], ['info_user', 'com_user'])
        credits = self.net.json_endpoint_calls('Sms/GetCredit')
        self.assertEqual([c['user'] for c in credits], ['info_user', 'com_user', 'info_user', 'com_user'])
        self.assertTrue(all(c['payload']['accountId'] == (9254 if c['user'] == 'info_user' else 65672)
                            for c in credits))

    def test_kk_c30_bilgi_jetonu_reklam_hesabina_kullanilmaz(self):
        info = self.json_client('info', service='bulk')
        info.get_credit(9254)
        info_token = self.net.tj.tokens_issued[0][1]
        com = self.json_api().TuratelJsonClient(self.JSON_BULK_URL, '20219', 'com_user', 'com_pw')
        com.get_credit(65672)
        self.assertNotEqual(self.net.json_endpoint_calls('Sms/GetCredit')[-1]['bearer'], info_token)

    def test_kk_c30_bir_setin_minus_1_i_digerinin_jetonunu_etkilemez(self):
        info = self.json_client('info', service='bulk')
        com = self.json_api().TuratelJsonClient(self.JSON_BULK_URL, '20219', 'com_user', 'com_pw')
        info.get_credit(9254)
        com.get_credit(65672)
        com_token = [t for u, t in self.net.tj.tokens_issued if u == 'com_user'][0]
        self.net.tj.expire_tokens('info_user')
        info.get_credit(9254)                                  # -1 → yalnız bilgi jetonu yenilenir
        com.get_credit(65672)
        self.assertEqual([u for u, _t in self.net.tj.tokens_issued], ['info_user', 'com_user', 'info_user'])
        self.assertEqual(self.net.json_endpoint_calls('Sms/GetCredit')[-1]['bearer'], com_token)

    def test_kk_c30_onbellek_servis_adresi_basina(self):
        single = self.json_client('info', service='single')
        bulk = self.json_api().TuratelJsonClient(self.JSON_BULK_URL, '20219', 'info_user', 'info_pw')
        single.get_credit(9254)
        bulk.get_credit(9254)
        self.assertEqual(len(self.net.json_endpoint_calls('Auth/GetToken')), 2)

    # ── C2 sözleşmesi ek testleri (sozlesme-C2.md) ──
    def test_c2_yenileme_baska_is_parcaciginin_jetonunu_silmez(self):
        """-1 sonrası önbellek yalnız hâlâ eski jetonu tutuyorsa silinir (karşılaştır-sil)."""
        api = self.json_api()
        client = self.json_client('info')
        client.get_credit(9254)
        self.net.tj.expire_tokens('info_user')
        state = {'done': False}

        def other_thread_refreshes(call):
            # eski jetonla gelen GetCredit -1 alacak; o sırada "başka iş parçacığı" yeni jeton alıp önbelleğe koyar
            if call['endpoint'] == 'Sms/GetCredit' and not state['done']:
                state['done'] = True
                api.TuratelJsonClient(self.JSON_SINGLE_URL, '20219', 'info_user', 'info_pw').get_token(force=True)
        self.net.tj.hook = other_thread_refreshes
        self.assertEqual(client.get_credit(9254), 90680)
        self.assertEqual(len(self.net.json_endpoint_calls('Auth/GetToken')), 2,
                         'Başka iş parçacığının aldığı yeni jeton silinmemeli, yeniden GetToken gerekmez')
        self.assertEqual(self.net.json_endpoint_calls('Sms/GetCredit')[-1]['bearer'], self.net.tj.tokens_issued[-1][1])

    def test_c2_send_oncesi_jeton_alinamazsa_retryable(self):
        """SendSms'ten önceki GetToken hatası: SMS kesinlikle gitmedi → belirsiz değil, yeniden denenebilir."""
        client = self.json_client('info')
        for outcome in (requests.exceptions.ReadTimeout(), 500, '<html>Bakımda</html>'):
            with self.subTest(sonuc=repr(outcome)[:30]):
                self.net.tj.add_script('Auth/GetToken', outcome)
                with self.assertRaises(TuratelError) as ctx:
                    self.send(client)
                self.assertTrue(ctx.exception.retryable)
                self.assertFalse(ctx.exception.uncertain)
        self.assertEqual(self.net.json_sends, [])

    def test_c2_ham_yanit_sinirli_ve_numara_maskeli(self):
        client = self.json_client('info', service='bulk')
        self.net.tj.add_script('Sms/SendSms', json_ok({'packetId': 9003, 'messageIdList': [801, 802, 803],
                                                       'echo': 'x' * 5000, 'receiver': '905321234567'}))
        result = self.send(client, NUMBERS, CIDS)
        self.assertLessEqual(len(result.raw), 2000)
        self.assertNotIn('5321234567', result.raw)
        self.assertEqual(str(result.message_ids[CIDS[2]]), '803')
        self.net.tj.add_script('Sms/SendSms', json_err('-10', 'Numara 905321234567 hatali'))
        with self.assertRaises(TuratelError) as ctx:
            self.send(client)
        self.assertNotIn('5321234567', str(ctx.exception))

    def test_c2_hatali_istek_aga_cikmadan_kalici_hata(self):
        client = self.json_client('info')
        cases = (
            ('alici-kimlik', lambda: client.send_sms(9254, 'TESTBASLIK', 'x', NUMBERS[:2], client_ids=CIDS[:1],
                                                     reference_id='R')),
            ('parametre', lambda: client.send_sms(9254, 'TESTBASLIK', 'x', NUMBERS[:2], client_ids=CIDS[:2],
                                                  reference_id='R', parameters=[['A']])),
            ('bos-alici', lambda: client.send_sms(9254, 'TESTBASLIK', 'x', [], client_ids=[], reference_id='R')),
            ('referans', lambda: client.send_sms(9254, 'TESTBASLIK', 'x', NUMBERS[:1], client_ids=CIDS[:1],
                                                 reference_id='')),
            ('hesap', lambda: client.get_credit('abc')),
        )
        for label, call in cases:
            with self.subTest(durum=label):
                with self.assertRaises(TuratelError) as ctx:
                    call()
                self.assertPermanent(ctx.exception)
        self.assertEqual(self.net.json_calls, [], 'Hatalı istek ağa çıkmamalı')

    def test_c2_loglarda_numara_ve_govde_yok(self):
        with self.capture_logs() as lines:
            client = self.json_client('info', service='bulk')
            self.send(client, NUMBERS, CIDS)
            client.get_status_between(9254, datetime(2026, 10, 18, 21, 0, tzinfo=timezone.utc),
                                      datetime(2026, 10, 19, 20, 59, 59, tzinfo=timezone.utc))
        text = '\n'.join(lines)
        self.assertTrue(text, 'İstemci en az bir DEBUG satırı yazmalı')
        for secret in ('Merhaba', 'info_pw', 'Bearer', 'TOK-') + tuple(NUMBERS):
            self.assertNotIn(secret, text)

    def test_teslim_tarihi_yer_tutucusu_kanit_sayilmaz(self):
        api = self.json_api()
        for value in (None, '', ' ', '000000000000', '0', '0001-01-01T00:00:00', '0001010000000'):
            with self.subTest(deger=value):
                self.assertFalse(api.has_delivery_date(value))
                self.assertEqual(api.status_code(1, '', value), 'status:1:tarih-yok')
        self.assertTrue(api.has_delivery_date('201026123000'))
        self.assertEqual(api.status_code(1, '', '201026123000'), 'status:1')

    def test_eski_yalniz_rakam_status_kodlari_iletilemedi_sayilmaz(self):
        """Eski sürüm `status` değerini kod diye saklardı ('1', '2'...): ulaşmış SMS 'iletilemedi' görünmesin."""
        api = self.json_api()
        for code in ('0', '1', '2', '3', 1, 2):
            with self.subTest(kod=code):
                state, label = api.delivery_state(code)
                self.assertEqual(state, 'unknown')
                self.assertIn('eski kayıt', label)
        # Gerçek reason kodları etkilenmez; tek haneli reason 'kod:' önekiyle saklanır ve iletilemedi sayılır
        self.assertEqual(api.delivery_state('114')[0], 'undelivered')
        self.assertEqual(api.delivery_state('-8000')[0], 'undelivered')
        self.assertEqual(api.status_code(2, '5', ''), 'kod:5')
        self.assertEqual(api.delivery_state('kod:5'), ('undelivered', 'iletilemedi (kod 5)'))
