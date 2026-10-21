# -*- coding: utf-8 -*-
"""Nebim connector: yeniden deneme politikası ve log maskeleme (Nebim'e istek atmaz)."""
from unittest.mock import MagicMock, patch

import requests

from odoo.tests import tagged
from odoo.tests.common import BaseCase, TransactionCase

from ..services import nebim_connector as nc


@tagged('post_install', '-at_install')
class TestNebimConnectorPolicy(BaseCase):

    def test_session_id_is_masked(self):
        url = 'http://192.168.0.225:9091/(S(e2g2aw5ijbyryo35midpl0uk))/IntegratorService/RunProc'
        self.assertEqual(nc._mask(url), 'http://192.168.0.225:9091/(S(***))/IntegratorService/RunProc')

    def test_only_undelivered_requests_are_retried(self):
        self.assertTrue(nc._request_not_delivered(requests.exceptions.ConnectTimeout()))
        self.assertTrue(nc._request_not_delivered(
            requests.exceptions.ConnectionError('NewConnectionError: Failed to establish a new connection')))
        # Okuma zaman aşımı / yanıt ortasında kopma: Nebim belgeyi kaydetmiş olabilir
        self.assertFalse(nc._request_not_delivered(requests.exceptions.ReadTimeout()))
        self.assertFalse(nc._request_not_delivered(
            requests.exceptions.ConnectionError('Connection aborted. RemoteDisconnected')))

    def test_session_rejection_detected(self):
        resp = MagicMock(status_code=500, text='The session has expired or is invalid')
        self.assertTrue(nc._session_rejected(requests.exceptions.HTTPError(response=resp)))
        resp = MagicMock(status_code=500, text='Stok yetersiz')
        self.assertFalse(nc._session_rejected(requests.exceptions.HTTPError(response=resp)))


@tagged('post_install', '-at_install')
class TestNebimConnectorPost(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('odoougurlar.nebim_url', 'http://nebim.test/IntegratorService')
        self.connector = self.env['odoougurlar.nebim.connector']

    def test_post_is_not_resent_after_read_timeout(self):
        """Okuma zaman aşımında aynı belge ikinci kez gönderilmez (mükerrer e-fatura)."""
        with patch.object(type(self.connector), '_connect', return_value='TOKEN'), \
                patch.object(nc._http_session, 'post', side_effect=requests.exceptions.ReadTimeout()) as post, \
                patch.object(nc.time, 'sleep'):
            with self.assertRaises(Exception) as ctx:
                self.connector.post_data('Post', {'ModelType': 8})
        self.assertEqual(post.call_count, 1)
        self.assertNotIn('TOKEN', str(ctx.exception))

    def test_post_is_retried_when_not_delivered(self):
        ok = MagicMock(status_code=200)
        ok.json.return_value = {'HeaderID': 'X'}
        with patch.object(type(self.connector), '_connect', return_value='TOKEN'), \
                patch.object(nc._http_session, 'post',
                             side_effect=[requests.exceptions.ConnectTimeout(), ok]) as post, \
                patch.object(nc.time, 'sleep'):
            self.assertEqual(self.connector.post_data('Post', {'ModelType': 8}), {'HeaderID': 'X'})
        self.assertEqual(post.call_count, 2)

    def test_non_idempotent_sp_is_not_resent(self):
        with patch.object(type(self.connector), '_connect', return_value='TOKEN'), \
                patch.object(nc._http_session, 'post', side_effect=requests.exceptions.ReadTimeout()) as post, \
                patch.object(nc.time, 'sleep'):
            with self.assertRaises(Exception):
                self.connector.run_proc('sp_GetNextExportFileNumber_Hamurlabs')
        self.assertEqual(post.call_count, 1)


@tagged('post_install', '-at_install')
class TestNebimCallPolicy(TransactionCase):
    """Çağrı başına timeout / retries (H3): varsayılan davranış korunur."""

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('odoougurlar.nebim_url', 'http://nebim.test/IntegratorService')
        self.connector = self.env['odoougurlar.nebim.connector']

    def _ok(self):
        ok = MagicMock(status_code=200)
        ok.json.return_value = []
        return ok

    def _timeouts(self, post):
        return [c.kwargs['timeout'] for c in post.call_args_list]

    def test_defaults_keep_300s_and_two_attempts(self):
        with patch.object(type(self.connector), '_connect', return_value='T'), \
                patch.object(nc._http_session, 'post', side_effect=[requests.exceptions.ConnectTimeout(), self._ok()]) as post, \
                patch.object(nc.time, 'sleep'):
            self.connector.run_proc('sp_GetX')
        self.assertEqual(self._timeouts(post), [(nc.CONNECT_TIMEOUT, 300)] * 2)

    def test_explicit_timeout_and_no_retry(self):
        with patch.object(type(self.connector), '_connect', return_value='T') as connect, \
                patch.object(nc._http_session, 'post', side_effect=requests.exceptions.ReadTimeout()) as post, \
                patch.object(nc.time, 'sleep'):
            with self.assertRaises(Exception):
                self.connector.run_proc('sp_GetX', timeout=15, retries=0)
        self.assertEqual(self._timeouts(post), [(nc.CONNECT_TIMEOUT, 15)])
        connect.assert_called_once_with(retries=0)  # bağlantı da yeniden denenmez

    def test_idempotent_read_is_retried_by_default(self):
        with patch.object(type(self.connector), '_connect', return_value='T'), \
                patch.object(nc._http_session, 'post', side_effect=[requests.exceptions.ReadTimeout(), self._ok()]) as post, \
                patch.object(nc.time, 'sleep'):
            self.connector.run_proc('sp_GetX')
        self.assertEqual(post.call_count, 2)

    def test_context_timeout_applies_and_explicit_wins(self):
        conn = self.connector.with_context(nebim_timeout=60)
        with patch.object(type(self.connector), '_connect', return_value='T'), \
                patch.object(nc._http_session, 'post', return_value=self._ok()) as post:
            conn.post_data('Post', {})
            conn.run_proc('sp_GetX', timeout=15)
        self.assertEqual(self._timeouts(post), [(nc.CONNECT_TIMEOUT, 60), (nc.CONNECT_TIMEOUT, 15)])

    def test_post_with_explicit_timeout_never_resends_after_read_timeout(self):
        with patch.object(type(self.connector), '_connect', return_value='T'), \
                patch.object(nc._http_session, 'post', side_effect=requests.exceptions.ReadTimeout()) as post, \
                patch.object(nc.time, 'sleep'):
            with self.assertRaises(Exception):
                self.connector.post_data('Post', {}, timeout=60)
        self.assertEqual(self._timeouts(post), [(nc.CONNECT_TIMEOUT, 60)])

    def test_context_retries_zero_disables_retries_including_connect(self):
        """nebim_retries=0 (paketleme zinciri): idempotent okuma da, bağlantı da tek deneme."""
        conn = self.connector.with_context(nebim_retries=0)
        self.addCleanup(nc._session_cache.update, dict(nc._session_cache))
        nc._session_cache.update(token=None, expires=0)
        with patch.object(nc._http_session, 'post', side_effect=requests.exceptions.ConnectTimeout()) as post, \
                patch.object(nc.time, 'sleep') as sleep:
            with self.assertRaises(Exception):
                conn.run_proc('sp_GetX')
        self.assertEqual(post.call_count, 1, 'Connect tek deneme')
        sleep.assert_not_called()
        with patch.object(type(self.connector), '_connect', return_value='T'), \
                patch.object(nc._http_session, 'post', side_effect=requests.exceptions.ReadTimeout()) as post:
            with self.assertRaises(Exception):
                conn.run_proc('sp_GetX')
        self.assertEqual(post.call_count, 1, 'idempotent SP de yeniden denenmez')

    def test_explicit_retries_override_context(self):
        conn = self.connector.with_context(nebim_retries=0)
        with patch.object(type(self.connector), '_connect', return_value='T'), \
                patch.object(nc._http_session, 'post', side_effect=[requests.exceptions.ReadTimeout(), self._ok()]) as post, \
                patch.object(nc.time, 'sleep'):
            conn.run_proc('sp_GetX', retries=1)
        self.assertEqual(post.call_count, 2)

    def test_connect_retries_zero_makes_single_attempt(self):
        # NEDEN: modül düzeyinde süreç-geneli önbellek; testten sonra eski haline döner
        self.addCleanup(nc._session_cache.update, dict(nc._session_cache))
        nc._session_cache.update(token=None, expires=0)
        with patch.object(nc._http_session, 'post', side_effect=requests.exceptions.ConnectTimeout()) as post, \
                patch.object(nc.time, 'sleep') as sleep:
            with self.assertRaises(Exception):
                self.connector._connect(retries=0)
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()


@tagged('post_install', '-at_install')
class TestNebimCopyFlags(TransactionCase):

    def test_copied_order_is_not_marked_sent(self):
        partner = self.env['res.partner'].create({'name': 'Kopya Test'})
        order = self.env['sale.order'].create({'partner_id': partner.id})
        order.write({'nebim_order_sent': True, 'nebim_customer_sent': True, 'nebim_customer_code': '1-4-1',
                     'nebim_header_id': 'H1'})
        copy = order.copy()
        self.assertFalse(copy.nebim_order_sent)
        self.assertFalse(copy.nebim_customer_code)
        self.assertFalse(copy.nebim_header_id)
