# -*- coding: utf-8 -*-
import hashlib
import hmac
import json

from odoo.tests import HttpCase, TransactionCase, tagged


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestWhatsAppWebhook(HttpCase):
    URL = '/social_media_ai/webhook/whatsapp'

    def setUp(self):
        super().setUp()
        self.account = self.env['social.media.account'].create({
            'name': 'WA Test', 'platform': 'whatsapp', 'whatsapp_instance_name': 'test_inst',
        })
        self.payload = {
            'event': 'messages.upsert', 'instance': 'test_inst',
            'payload': {'from': '905551234567@c.us', 'body': 'Merhaba'},
        }

    def _post(self, secret=None):
        headers = {'Content-Type': 'application/json'}
        if secret is not None:
            headers['X-Webhook-Secret'] = secret
        return self.url_open(self.URL, data=json.dumps(self.payload), headers=headers)

    def _messages(self):
        return self.env['social.media.message'].search([('conversation_id.account_id', '=', self.account.id)])

    def test_secret_not_configured_rejects(self):
        # NEDEN: secret tanımsızken boş başlık da eşleşmemeli (fail-closed)
        self.env['ir.config_parameter'].set_param('social_media_ai.whatsapp_webhook_secret', '')
        self.assertEqual(self._post('').status_code, 403)
        self.assertEqual(self._post().status_code, 403)
        self.assertFalse(self._messages())

    def test_wrong_secret_rejects(self):
        self.env['ir.config_parameter'].set_param('social_media_ai.whatsapp_webhook_secret', 's3cret')
        self.assertEqual(self._post('yanlis').status_code, 403)
        self.assertFalse(self._messages())

    def test_correct_secret_processes(self):
        self.env['ir.config_parameter'].set_param('social_media_ai.whatsapp_webhook_secret', 's3cret')
        self.assertEqual(self._post('s3cret').status_code, 200)
        self.assertEqual(self._messages().content, 'Merhaba')
        partner = self.env['res.partner'].search([('ref', '=', 'wa_905551234567')])
        self.assertEqual(len(partner), 1)
        # Aynı numara ikinci kez gelince mevcut partner yeniden kullanılır
        self.assertEqual(self._post('s3cret').status_code, 200)
        self.assertEqual(self.env['res.partner'].search_count([('ref', '=', 'wa_905551234567')]), 1)
        self.assertEqual(len(self._messages()), 2)


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestMetaWebhookSignature(HttpCase):
    URL = '/social_media_ai/webhook/meta'

    def setUp(self):
        super().setUp()
        self.account = self.env['social.media.account'].create({'name': 'FB Test', 'platform': 'facebook'})
        self.env['ir.config_parameter'].set_param('social_media_ai.enable_dms', 'True')
        self.body = json.dumps({'object': 'page', 'entry': [{'messaging': [{
            'sender': {'id': 'psid1'}, 'recipient': {'id': 'page1'},
            'message': {'mid': 'm1', 'text': 'Selam'},
        }]}]}).encode()

    def _post(self, signature=None):
        headers = {'Content-Type': 'application/json'}
        if signature:
            headers['X-Hub-Signature-256'] = signature
        return self.url_open(self.URL, data=self.body, headers=headers)

    def _count(self):
        return self.env['social.media.message'].search_count([('conversation_id.account_id', '=', self.account.id)])

    def test_signature_checked_when_secret_set(self):
        self.env['ir.config_parameter'].set_param('social_media_ai.meta_app_secret', 'appsecret')
        good = 'sha256=' + hmac.new(b'appsecret', self.body, hashlib.sha256).hexdigest()
        self.assertEqual(self._post('sha256=' + '0' * 64).status_code, 403)
        self.assertEqual(self._post().status_code, 403)
        self.assertEqual(self._count(), 0)
        self.assertEqual(self._post(good).status_code, 200)
        self.assertEqual(self._count(), 1)

    def test_no_secret_rejects(self):
        # NEDEN: fail-closed; App Secret tanımsızken imzasız/boş imzalı POST işlenmemeli
        self.env['ir.config_parameter'].set_param('social_media_ai.meta_app_secret', '')
        self.assertEqual(self._post().status_code, 403)
        self.assertEqual(self._post('sha256=' + '0' * 64).status_code, 403)
        self.assertEqual(self._count(), 0)

    def test_challenge_is_text_plain(self):
        self.account.webhook_secret = 'verify-tok'
        res = self.url_open(self.URL + '?hub.mode=subscribe&hub.verify_token=verify-tok&hub.challenge=%3Cb%3E123')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.headers['Content-Type'].startswith('text/plain'))
        self.assertEqual(res.text, '<b>123')


@tagged('post_install', '-at_install', 'social_media_ai_manager')
class TestSearchProductForChat(TransactionCase):

    def test_returns_results(self):
        product = self.env['product.product'].create({
            'name': 'Test Elbise G5', 'list_price': 100.0, 'barcode': 'G5TEST123',
        })
        results = self.env['social.media.message'].search_product_for_chat('G5TEST123')
        self.assertEqual([r['id'] for r in results], [product.id])
        self.assertIn('Test Elbise G5', results[0]['chat_text'])

    def test_no_match_returns_empty_list(self):
        self.assertEqual(self.env['social.media.message'].search_product_for_chat('yok-boyle-urun-xyz'), [])
