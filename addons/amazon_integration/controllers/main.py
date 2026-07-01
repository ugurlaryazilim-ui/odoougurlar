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
