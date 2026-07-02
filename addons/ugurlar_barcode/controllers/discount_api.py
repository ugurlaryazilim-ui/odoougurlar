import logging
import json

from odoo import http
from odoo.http import request

from .base_api import BarcodeApiBase

_logger = logging.getLogger(__name__)


class DiscountApiController(BarcodeApiBase):
    """Satış İndirimleri API'si."""

    @http.route('/ugurlar_barcode/api/calculate_discounts', type='json', auth='user')
    def calculate_discounts(self, basket=None, customer_code=''):
        """
        Sepet bilgisini alır, Nebim V3'e gönderir ve hesaplanmış sonuçları döner.
        :param basket: list of dict, [{"barcode": "...", "quantity": 1}]
        :param customer_code: str, opsiyonel müşteri kartı veya kodu
        """
        if not basket:
            return {'error': 'Sepet boş.'}

        # 1. Nebim'e gönderilecek JSON payload'ını hazırla
        nebim_payload = {
            'Basket': [
                {
                    'LineId': i,
                    'Barcode': item.get('barcode'),
                    'Quantity': item.get('quantity', 1)
                }
                for i, item in enumerate(basket, start=1)
            ],
            'CustomerCode': customer_code or '',
            'LangCode': 1
        }

        # 2. Nebim Connector üzerinden SP'yi çağır
        NebimConnector = request.env['odoougurlar.nebim.connector'].sudo()
        try:
            # Parametreler Nebim IntegratorService beklediği formatta (Name, Value)
            proc_params = [
                {'Name': 'JsonData', 'Value': json.dumps(nebim_payload)}
            ]
            
            # SP çağrısı
            # Not: SP ismi sabit veya ayarlardan çekilebilir. Burada sabit bırakıldı.
            results = NebimConnector.run_proc('sp_Odoougurlar_GetBasketDiscounts', params=proc_params)
            
            # Nebim'den dönen results genelde dict listesidir. Eğer boşsa, sepet hesaplanamadı demektir.
            if not results:
                return {'error': 'Nebim V3 indirim hesaplama sonucu boş döndü.'}
            
            if isinstance(results, dict) and results.get('ExceptionMessage'):
                return {'error': f"Nebim Hatası: {results.get('ExceptionMessage')}"}

        except Exception as e:
            _logger.error('Nebim V3 İndirim Hesaplama Hatası: %s', str(e))
            return {'error': f'İndirim hesaplanırken hata oluştu: {str(e)}'}

        # 3. Odoo'dan Ürün Resimlerini (image_url) ve Ek Bilgileri Ekle
        # Nebim'den dönen Barcode'ları toplayıp Odoo'da arıyoruz.
        barcodes = [row.get('Barcode') for row in results if isinstance(row, dict) and row.get('Barcode')]
        
        Product = request.env['product.product'].sudo()
        products = Product.search([('barcode', 'in', barcodes)])
        
        # Barkod -> Odoo Ürün Map'i
        product_map = {p.barcode: p for p in products if p.barcode}

        # 4. Yanıtı formatla
        formatted_lines = []
        total_retail = 0.0
        total_discount = 0.0
        total_final = 0.0

        for row in results:
            if not isinstance(row, dict):
                continue
                
            barcode = row.get('Barcode', '')
            qty = row.get('Quantity', 1)
            retail_price = float(row.get('RetailPrice', 0.0))
            discount_amount = float(row.get('DiscountAmount', 0.0))
            final_total = float(row.get('FinalLineTotal', 0.0))
            campaign_name = row.get('CampaignName', '')
            upsell_message = row.get('UpsellMessage', '')

            # Odoo ürünü varsa bilgilerini zenginleştir
            odoo_prod = product_map.get(barcode)
            image_url = f'/web/image/product.product/{odoo_prod.id}/image_128' if odoo_prod else ''
            product_name = odoo_prod.display_name if odoo_prod else barcode

            formatted_lines.append({
                'barcode': barcode,
                'name': product_name,
                'quantity': qty,
                'retail_price': retail_price,
                'discount_amount': discount_amount,
                'final_price': final_total,
                'campaign_name': campaign_name,
                'upsell_message': upsell_message,
                'image_url': image_url
            })

            total_retail += (retail_price * qty)
            total_discount += discount_amount
            total_final += final_total

        return {
            'success': True,
            'lines': formatted_lines,
            'summary': {
                'total_retail': total_retail,
                'total_discount': total_discount,
                'total_final': total_final
            }
        }

    @http.route('/ugurlar_barcode/api/search_customer', type='json', auth='user')
    def search_customer(self, query):
        """Müşteri arama endpoint'i. İsim veya cep telefonu ile arar."""
        if not query or len(query) < 3:
            return {'customers': []}
            
        Partner = request.env['res.partner'].sudo()
        domain = ['|', ('name', 'ilike', query), ('mobile', 'ilike', query)]
        # Müşterileri bul, ref veya barcode (Nebim CustomerCode için) dön
        partners = Partner.search(domain, limit=10)
        
        customers = []
        for p in partners:
            customer_code = p.ref or p.barcode or ''
            customers.append({
                'id': p.id,
                'name': p.name,
                'phone': p.mobile or p.phone or '',
                'customer_code': customer_code
            })
            
        return {'customers': customers}

