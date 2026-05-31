import logging
import requests as http_requests

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# PDF proxy için HTTP session (cookie'leri korur)
_pdf_session = http_requests.Session()


class EArchiveController(http.Controller):
    """E-Arşiv fatura PDF proxy controller.

    Portal sayfasından PDF'i server-side çeker ve doğrudan döndürür.
    Bu sayede cross-origin/cookie sorunları yaşanmaz.
    """

    @http.route('/odoougurlar/earchive_pdf', type='http', auth='user')
    def earchive_pdf(self, url='', **kw):
        """E-arşiv portal URL'sinden PDF'i çekip döndürür.

        Akış:
            1. Portal sayfasını GET → session cookie alınır
            2. /earchive/pdf/goruntule → PDF içeriği çekilir
            3. PDF binary olarak döndürülür
        """
        if not url:
            return Response('URL parametresi gerekli', status=400)

        try:
            # 1. Portal sayfasını ziyaret et (session cookie'si al)
            sess = http_requests.Session()
            sess.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })

            portal_resp = sess.get(url, timeout=15, allow_redirects=True)
            portal_resp.raise_for_status()

            # 2. Portal URL'sinden base URL çıkar
            #    https://portal.doganedonusum.com/earchive/view-earchive/...
            #    → https://portal.doganedonusum.com
            from urllib.parse import urlparse
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"

            # 3. PDF'i çek — portal session cookie'si ile
            pdf_url = f"{base_url}/earchive/pdf/goruntule"
            pdf_resp = sess.get(pdf_url, timeout=30, allow_redirects=True)
            pdf_resp.raise_for_status()

            content_type = pdf_resp.headers.get('Content-Type', '')

            # PDF geldi mi kontrol et
            if 'pdf' in content_type.lower() or pdf_resp.content[:5] == b'%PDF-':
                return Response(
                    pdf_resp.content,
                    status=200,
                    headers={
                        'Content-Type': 'application/pdf',
                        'Content-Disposition': 'inline',
                        'Cache-Control': 'no-cache',
                    },
                )

            # PDF değilse HTML olarak dön (belki login sayfası)
            _logger.warning(
                "E-Arşiv PDF bekleniyordu, %s geldi. URL: %s",
                content_type, pdf_url
            )

            # Belki doğrudan URL'den PDF indirme linki deneyelim
            # webValidationKey ile doğrudan PDF
            alt_pdf_url = url.replace('view-pdf-earchive.xhtml', 'download-pdf-earchive.xhtml')
            alt_resp = sess.get(alt_pdf_url, timeout=30, allow_redirects=True)
            if alt_resp.content[:5] == b'%PDF-':
                return Response(
                    alt_resp.content,
                    status=200,
                    headers={
                        'Content-Type': 'application/pdf',
                        'Content-Disposition': 'inline',
                        'Cache-Control': 'no-cache',
                    },
                )

            # Son çare: HTML içeriği döndür (portal sayfası)
            return Response(
                pdf_resp.content,
                status=200,
                headers={'Content-Type': content_type or 'text/html'},
            )

        except http_requests.exceptions.Timeout:
            _logger.error("E-Arşiv PDF timeout: %s", url)
            return Response('Fatura sunucusuna bağlanılamadı (timeout)', status=504)
        except Exception as e:
            _logger.error("E-Arşiv PDF hatası: %s - %s", url, e)
            return Response(f'PDF çekilemedi: {str(e)}', status=500)
