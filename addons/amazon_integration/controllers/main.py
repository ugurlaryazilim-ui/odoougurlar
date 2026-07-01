import logging
import requests
from werkzeug.exceptions import BadRequest

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class AmazonAuthController(http.Controller):

    @http.route('/amazon/auth/callback', type='http', auth='user', website=True)
    def amazon_auth_callback(self, **kw):
        """
        Amazon OAuth2 callback endpoint.
        Amazon redirects here with:
        - spapi_oauth_code
        - state (which we set to our amazon.store ID)
        - selling_partner_id
        """
        spapi_oauth_code = kw.get('spapi_oauth_code')
        state = kw.get('state')
        selling_partner_id = kw.get('selling_partner_id')
        error = kw.get('error')
        error_description = kw.get('error_description')

        if error:
            _logger.error("Amazon Auth Error: %s - %s", error, error_description)
            return request.render('http_routing.http_error', {
                'status_code': 400,
                'status_message': 'Amazon Yetkilendirme Hatası',
                'error_message': f"Amazon yetkilendirmesi başarısız oldu: {error_description}"
            })

        if not spapi_oauth_code or not state:
            return request.render('http_routing.http_error', {
                'status_code': 400,
                'status_message': 'Geçersiz İstek',
                'error_message': "Amazon'dan gerekli parametreler alınamadı (spapi_oauth_code veya state eksik)."
            })

        try:
            store_id = int(state)
        except ValueError:
            return request.render('http_routing.http_error', {
                'status_code': 400,
                'status_message': 'Geçersiz State',
                'error_message': "State parametresi geçerli bir mağaza ID'si değil."
            })

        store = request.env['amazon.store'].sudo().browse(store_id)
        if not store.exists():
            return request.render('http_routing.http_error', {
                'status_code': 404,
                'status_message': 'Mağaza Bulunamadı',
                'error_message': f"ID'si {store_id} olan mağaza veritabanında bulunamadı."
            })

        # LWA'dan Refresh Token al
        token_url = "https://api.amazon.com/auth/o2/token"
        payload = {
            "grant_type": "authorization_code",
            "code": spapi_oauth_code,
            "client_id": store.lwa_client_id,
            "client_secret": store.lwa_client_secret
        }

        try:
            res = requests.post(token_url, data=payload, timeout=20)
            res.raise_for_status()
            token_data = res.json()
            
            refresh_token = token_data.get('refresh_token')
            if not refresh_token:
                raise ValueError("Amazon yanıtında refresh_token bulunamadı!")
            
            # Token'ı kaydet
            store.write({
                'refresh_token': refresh_token,
            })
            
            # Başarılı mesajı ile mağazanın form görünümüne geri yönlendir
            action = request.env.ref('amazon_integration.action_amazon_store')
            url = f"/web#id={store.id}&model=amazon.store&view_type=form&action={action.id}"
            
            # Başarı sayfasını gösterelim ve 3 saniye sonra geri yönlendirelim
            html_content = f"""
            <html>
                <head>
                    <title>Başarılı</title>
                    <meta http-equiv="refresh" content="3;url={url}" />
                    <style>
                        body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; background-color: #f8f9fa; }}
                        .container {{ max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                        h2 {{ color: #28a745; }}
                        p {{ color: #6c757d; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h2>✅ Yetkilendirme Başarılı!</h2>
                        <p>Amazon Refresh Token başarıyla alındı ve mağazaya kaydedildi.</p>
                        <p>Odoo'ya geri yönlendiriliyorsunuz...</p>
                        <p><a href="{url}">Otomatik yönlendirilmezseniz buraya tıklayın.</a></p>
                    </div>
                </body>
            </html>
            """
            return http.Response(html_content, status=200, mimetype='text/html')

        except Exception as e:
            _logger.exception("Refresh token alınırken hata oluştu.")
            return request.render('http_routing.http_error', {
                'status_code': 500,
                'status_message': 'Sunucu Hatası',
                'error_message': f"Refresh Token alınırken bir hata oluştu: {str(e)}"
            })

    @http.route('/amazon-privacy-policy', type='http', auth='public', website=True)
    def amazon_privacy_policy(self, **kw):
        """
        Amazon Data Protection Policy (DPP) compliant Privacy Policy page.
        This page is publicly accessible and can be provided to Amazon Developer Registration.
        """
        html_content = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Amazon Integration Privacy Policy - Ugurlar Grup</title>
            <style>
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 40px 20px; background-color: #f9f9f9; }
                .container { background-color: #fff; padding: 40px; border-radius: 8px; box-shadow: 0 2px 15px rgba(0,0,0,0.05); }
                h1 { color: #232f3e; border-bottom: 2px solid #ff9900; padding-bottom: 10px; margin-bottom: 30px; }
                h2 { color: #232f3e; margin-top: 30px; font-size: 1.3em; }
                p { margin-bottom: 15px; }
                ul { margin-bottom: 20px; padding-left: 20px; }
                li { margin-bottom: 8px; }
                .footer { margin-top: 50px; font-size: 0.9em; color: #777; border-top: 1px solid #eee; padding-top: 20px; text-align: center; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Privacy and Data Handling Policy</h1>
                <p><strong>Last Updated:</strong> July 2026</p>
                <p><strong>Company:</strong> Ugurlar Grup</p>
                
                <p>This Privacy and Data Handling Policy explains how Ugurlar Grup ("we", "us", "our") collects, processes, stores, shares, and disposes of Amazon Information, including Personally Identifiable Information (PII) obtained through the Amazon Selling Partner API (SP-API).</p>

                <h2>1. Data Collection and Usage</h2>
                <p>We collect Amazon Information strictly for internal operational purposes to fulfill our Merchant Fulfilled Network (MFN) orders. The data collected includes order details, shipping addresses, phone numbers, and customer names (PII). We use this information <strong>exclusively</strong> for:</p>
                <ul>
                    <li>Generating shipping labels and fulfilling orders directly to the consumer.</li>
                    <li>Generating and uploading legally required tax invoices.</li>
                    <li>Managing inventory and order tracking within our self-hosted ERP system.</li>
                </ul>

                <h2>2. Data Sharing</h2>
                <p>We do not share, sell, or rent Amazon Information or PII to any external third parties, marketing agencies, or unauthorized affiliates. All Amazon data remains strictly within our private, closed-loop Odoo ERP system and is only accessible by authorized internal personnel on a need-to-know basis.</p>

                <h2>3. Data Storage and Security (Encryption at Rest)</h2>
                <p>All Amazon Information, including PII, is encrypted at rest using industry-standard AES-256 encryption. Our databases are hosted in a secure, private subnet with restricted access. Encryption keys are managed securely and independently from the database server.</p>

                <h2>4. Data Retention and Disposal</h2>
                <p>In strict compliance with the Amazon Data Protection Policy, we retain Personally Identifiable Information (PII) for no longer than <strong>30 days</strong> after order delivery, unless required by law for tax purposes (in which case it is cryptographically anonymized or masked). After the fulfillment lifecycle is complete, all PII is permanently deleted from our primary databases and encrypted backups.</p>

                <h2>5. Incident Response</h2>
                <p>We maintain a comprehensive Incident Response Plan. In the event of a suspected or actual security breach involving Amazon Information, we will isolate the affected systems and notify Amazon at security@amazon.com within 24 hours of detection.</p>

                <h2>6. Contact Information</h2>
                <p>If you have any questions or concerns regarding this Privacy Policy or our data handling practices, please contact our Incident Management Point of Contact (IMPOC):</p>
                <p><strong>Email:</strong> eticarettr@ugurlargrup.com</p>
                
                <div class="footer">
                    &copy; 2026 Ugurlar Grup. All rights reserved. This policy is designed to comply with Amazon Services API Data Protection Policy.
                </div>
            </div>
        </body>
        </html>
        """
        return http.Response(html_content, status=200, mimetype='text/html')
