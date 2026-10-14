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
