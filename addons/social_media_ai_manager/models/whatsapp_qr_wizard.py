# -*- coding: utf-8 -*-
from odoo import models, fields, api, exceptions
import requests
import logging

_logger = logging.getLogger(__name__)

class WhatsAppQRWizard(models.TransientModel):
    _name = 'social.media.whatsapp.qr.wizard'
    _description = 'WhatsApp QR Code Wizard'

    account_id = fields.Many2one('social.media.account', required=True)
    qr_image = fields.Binary(string='QR Kodu', readonly=True)
    status_message = fields.Text(string='Durum Mesajı', readonly=True)
    state = fields.Selection([
        ('init', 'Başlangıç'),
        ('qr_ready', 'QR Bekleniyor'),
        ('connected', 'Bağlandı'),
        ('error', 'Hata')
    ], default='init')

    def action_fetch_qr(self):
        self.ensure_one()
        account = self.account_id
        if not account.whatsapp_api_url or not account.api_token or not account.whatsapp_instance_name:
            self.write({'status_message': 'API URL, API Şifresi veya Instance Name eksik!', 'state': 'error'})
            return self._reopen()

        base_url = account.whatsapp_api_url.rstrip('/')
        headers = {
            'apikey': account.api_token,
            'Content-Type': 'application/json'
        }

        # 1. Instance Create (Zaten varsa Evolution API hata döndürebilir ama sorun değil)
        create_url = f"{base_url}/instance/create"
        payload = {
            "instanceName": account.whatsapp_instance_name,
            "integration": "WHATSAPP-BAILEYS"
        }
        try:
            res_create = requests.post(create_url, json=payload, headers=headers, timeout=10)
            _logger.info(f"Evolution API Create Instance Response: {res_create.status_code} - {res_create.text}")
        except Exception as e:
            self.write({'status_message': f'Evolution API bağlantı hatası: {str(e)}', 'state': 'error'})
            return self._reopen()

        # 2. Get QR Code
        connect_url = f"{base_url}/instance/connect/{account.whatsapp_instance_name}"
        try:
            res_connect = requests.get(connect_url, headers=headers, timeout=10)
            if res_connect.status_code == 200:
                data = res_connect.json()
                if 'base64' in data:
                    base64_str = data['base64']
                    if ',' in base64_str:
                        base64_str = base64_str.split(',')[1]
                    
                    self.write({
                        'qr_image': base64_str,
                        'status_message': 'Lütfen telefonunuzun WhatsApp Ayarlar > Bağlı Cihazlar bölümünden QR kodu okutun.',
                        'state': 'qr_ready'
                    })
                elif 'state' in data and data.get('state') == 'open':
                    self.write({
                        'status_message': 'Harika! Telefonunuz zaten başarılı şekilde bağlı.',
                        'state': 'connected',
                        'qr_image': False
                    })
                    account.state = 'connected'
                else:
                    self.write({'status_message': f'QR kodu alınamadı. Yanıt: {res_connect.text}', 'state': 'error'})
            else:
                self.write({'status_message': f'QR Kod Çekme Hatası: {res_connect.text}', 'state': 'error'})
        except Exception as e:
            self.write({'status_message': f'Evolution API QR bağlantı hatası: {str(e)}', 'state': 'error'})
            
        return self._reopen()

    def action_check_status(self):
        self.ensure_one()
        account = self.account_id
        base_url = account.whatsapp_api_url.rstrip('/')
        headers = {'apikey': account.api_token}
        
        status_url = f"{base_url}/instance/connectionState/{account.whatsapp_instance_name}"
        try:
            res = requests.get(status_url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                instance = data.get('instance', {})
                state = instance.get('state')
                if state == 'open':
                    self.write({
                        'status_message': 'Harika! Başarıyla bağlandınız.',
                        'state': 'connected',
                        'qr_image': False
                    })
                    account.state = 'connected'
                else:
                    self.write({
                        'status_message': f'Henüz bağlanmadı. Güncel durum: {state}',
                    })
            else:
                self.write({'status_message': f'Durum sorgulama hatası: {res.text}'})
        except Exception as e:
            self.write({'status_message': f'Durum sorgulama hatası: {str(e)}'})
            
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
