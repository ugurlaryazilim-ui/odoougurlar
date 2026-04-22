# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class IdefixStore(models.Model):
    _name = 'idefix.store'
    _description = 'Idefix Mağaza Ayarları'
    _order = 'sequence, name'

    name = fields.Char(string='Mağaza Adı', required=True)
    sequence = fields.Integer(string='Sıra', default=10)
    active = fields.Boolean(default=True)

    # API Credentials
    client_id = fields.Char(string='API Key', required=True, help="Idefix panelinden alınır")
    client_secret = fields.Char(string='API Secret', required=True)
    vendor_id = fields.Char(string='Satıcı ID (Vendor ID)', required=True)

    # ─── Senkronizasyon Ayarları ─────────────────────────
    auto_sync = fields.Boolean(string='Otomatik Sipariş Senkronizasyonu', default=True)
    sync_interval = fields.Integer(string='Senkron Aralığı (dk)', default=1, help='Bu değer cron ile senkronize çalışarak hangi sıklıkta Idefix API\'ye çıkılacağını gösterir.')
    order_day_range = fields.Integer(string='Senkronizasyon Gün Aralığı', default=1, help="Geçmişe dönük kaç günlük sipariş çekilecek?")
    last_sync = fields.Datetime(string='Son Senkronizasyon', readonly=True)
    
    # ─── Sipariş Ayarları ────────────────────────────────
    auto_confirm = fields.Boolean(string='Siparişi Otomatik Onayla', default=True, help="Odoo'ya düşen siparişler otomatik onaylanır ve Nebim sürecini tetikler.")
    auto_cancel = fields.Boolean(string='İptalleri Otomatik İptal Et', default=True)

    # ─── Müşteri Ayarları ────────────────────────────────
    customer_prefix = fields.Char(string='Müşteri Kodu Ön Ek', default='IDE-', help='Idefix müşterilerinin kodlarına eklenen ek')
    skip_customer_email = fields.Boolean(string='Mail Adresi İşlenmesin', default=False, help='Müşteri oluşturulurken e-posta adresi kaydedilmez (KVKK)')

    # ─── İade Ayarları ───────────────────────────────────
    process_returns = fields.Boolean(string='İadeleri İşle', default=False, help='İade edilen siparişleri çekip listele')
    return_day_range = fields.Integer(string='İade Gün Aralığı', default=3)
    
    # ─── Kargo Ayarları ──────────────────────────────────
    auto_send_cargo = fields.Boolean(string='Otomatik Kargo Kodu Gönder', default=True, help='Depo Picking (Toplama) tamamlandığında kargo bilgisini idefix paneline otomatik yollar')
    cargo_include_order_number = fields.Boolean(string='Kargo Koduna Sipariş No Ekle', default=False)
    default_package_count = fields.Integer(string='Varsayılan Koli Sayısı', default=1)
    default_desi = fields.Float(string='Varsayılan Desi', default=1.0)
    
    # ─── Finansal İşlem Ayarları ─────────────────────────
    sync_financials = fields.Boolean(string='Finansal İşlemleri Senkronize Et', default=True)
    financial_day_range = fields.Integer(string='Finansal Gün Aralığı', default=15)
    platform_fee_rate = fields.Float(string='Platform Hizmet Bedeli Oranı (%)', default=1.47, digits=(5, 2))
    cargo_unit_price = fields.Float(string='Kargo Birim Fiyatı (desi)', default=110.39, digits=(10, 2))
    last_financial_sync = fields.Datetime(string='Son Finansal Senkron', readonly=True)

    # ─── Counts ──────────────────────────────────────────
    order_count = fields.Integer(string='Sipariş Sayısı', compute='_compute_order_count')
    settlement_count = fields.Integer(string='Finansal Kayıt', compute='_compute_counts')

    def _compute_order_count(self):
        for store in self:
            store.order_count = self.env['idefix.order'].search_count([('store_id', '=', store.id)])

    def _compute_counts(self):
        for store in self:
            store.settlement_count = self.env['idefix.settlement'].search_count([('store_id', '=', store.id)])

    def get_api(self):
        """IdefixApi client objesini oluştur ve döndür."""
        self.ensure_one()
        if not self.client_id or not self.client_secret:
            raise UserError(_("Client ID ve Client Secret boş olamaz."))
            
        api = self.env['idefix.api'].sudo().create_api(self)
        return api

    def action_test_connection(self):
        """Bağlantıyı ve yetkilendirmeyi sına."""
        self.ensure_one()
        try:
            api = self.get_api()
            result = api.get_orders(start_date=fields.Datetime.now(), end_date=fields.Datetime.now())
            if result.get('success'):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Başarılı'),
                        'message': _('Bağlantı Başarılı. Sipariş listesi API yanıt verdi.'),
                        'sticky': False,
                        'type': 'success',
                    }
                }
            else:
                raise UserError(_("Bağlantı Hatası: %s" % result.get('error')))
        except Exception as e:
            raise UserError(_("Bağlantı Hatası: %s" % str(e)))

    def action_sync_now(self):
        self.ensure_one()
        sync_model = self.env['idefix.order'].sudo()
        res = sync_model.sync_orders_for_store(self)
        msg = f"Sipariş Senkronizasyon Tamamlandı.\nYeni: {res.get('created', 0)}\nGüncellenen: {res.get('updated', 0)}\nHata: {res.get('errors', 0)}"
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Senkronizasyon Sonucu'),
                'message': msg,
                'sticky': False,
                'type': 'success' if res.get('errors') == 0 else 'warning',
            }
        }

    def action_sync_financials(self):
        self.ensure_one()
        from datetime import datetime, timedelta
        import json
        
        api = self.get_api()
        start_date = datetime.now() - timedelta(days=self.financial_day_range or 15)
        end_date = datetime.now()

        res = api.get_payment_agreements(start_date=start_date, end_date=end_date)
        if not res.get('success'):
            raise UserError(_("Finansal veriler çekilemedi: %s") % res.get('error'))

        data_list = res.get('data', [])
        
        # Idefix data is sometimes inside {'data': [...]} or just a list
        if isinstance(data_list, dict) and 'data' in data_list:
            data_list = data_list['data']
        elif isinstance(data_list, dict) and 'paymentAgreements' in data_list:
            data_list = data_list['paymentAgreements']

        if not data_list or not isinstance(data_list, list):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Finansal Senkronizasyon'),
                    'message': 'Belirtilen tarih aralığında yeni finansal işlem (Payment Agreement) bulunamadı.',
                    'sticky': False,
                    'type': 'info',
                }
            }

        created = 0
        updated = 0
        settlement_model = self.env['idefix.settlement']

        for item in data_list:
            trx_id = str(item.get('id') or item.get('paymentAgreementId') or '')
            order_id = item.get('orderId') or ''
            
            # Bazı kayıtlarda id olmayabiliyor, trx_id ve order_id birlikte kontrol edelim
            domain = [('store_id', '=', self.id)]
            if trx_id:
                domain.append(('trx_id', '=', trx_id))
            elif order_id:
                domain.append(('order_id', '=', order_id))
            else:
                continue # no identifier

            existing = settlement_model.search(domain, limit=1)
            
            # Tarih dönüşümleri
            trx_date_str = item.get('transactionDate') or item.get('agreementDate')
            trx_date = False
            if trx_date_str:
                try:
                    trx_date = datetime.strptime(trx_date_str[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                except:
                    pass

            transferred_date_str = item.get('allowanceDate') or item.get('paymentDate')
            transferred_date = False
            if transferred_date_str:
                try:
                    transferred_date = datetime.strptime(transferred_date_str[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                except:
                    pass

            vals = {
                'store_id': self.id,
                'order_id': order_id,
                'trx_id': trx_id,
                'amount': item.get('totalAmount') or item.get('amount') or 0.0,
                'installment_number': item.get('installmentNumber', 1),
                'commission_amount': item.get('commissionAmount', 0.0),
                'coupon_discount': item.get('couponDiscount', 0.0),
                'status': item.get('status') or item.get('paymentStatus') or 'Unknown',
                'transaction_date': trx_date,
                'transferred_date': transferred_date,
                'raw_data': json.dumps(item, ensure_ascii=False)
            }

            if existing:
                existing.write(vals)
                updated += 1
            else:
                settlement_model.create(vals)
                created += 1

        self.sudo().write({'last_financial_sync': fields.Datetime.now()})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Finansal Senkronizasyon Başarılı'),
                'message': f"Yeni İşlem: {created}\nGüncellenen: {updated}",
                'sticky': False,
                'type': 'success',
            }
        }
