import logging
import re
import requests as http_requests

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class EArchiveController(http.Controller):
    """E-Arşiv fatura PDF proxy controller.

    Doğan e-Dönüşüm portalından fatura PDF/HTML'ini server-side çeker.
    Portal JSF tabanlı olduğu için form submit simüle edilir.
    """

    @http.route('/odoougurlar/earchive_pdf', type='http', auth='user')
    def earchive_pdf(self, url='', **kw):
        """E-arşiv portal URL'sinden faturayı çekip döndürür.

        Akış:
            1. Portal sayfasını GET → JSF session + ViewState alınır
            2. JSF formunu POST → PDF/HTML içeriği çekilir
            3. İçerik olarak döndürülür
        """
        if not url:
            return Response('URL parametresi gerekli', status=400)

        try:
            sess = http_requests.Session()
            sess.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                              'AppleWebKit/537.36 (KHTML, like Gecko) '
                              'Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;'
                          'q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8',
            })

            # ──── 1. Portal sayfasını GET ────
            _logger.info("E-Arşiv portal sayfası çekiliyor: %s", url)
            portal_resp = sess.get(url, timeout=15, allow_redirects=True)
            portal_resp.raise_for_status()
            portal_html = portal_resp.text

            from urllib.parse import urlparse, urljoin
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"

            # ──── 2. JSF ViewState ve form bilgilerini parse et ────
            view_state = self._extract_view_state(portal_html)
            form_info = self._extract_form_info(portal_html)

            if not form_info:
                _logger.warning("E-Arşiv: JSF form bulunamadı, doğrudan URL deneniyor")
                return self._try_direct_urls(sess, url, base_url)

            form_id = form_info['form_id']
            form_action = form_info['form_action']
            pdf_btn_id = form_info.get('pdf_btn_id', '')
            html_btn_id = form_info.get('html_btn_id', '')

            # Form action URL'sini resolve et
            if form_action.startswith('/'):
                action_url = base_url + form_action
            elif form_action.startswith('http'):
                action_url = form_action
            else:
                action_url = urljoin(url, form_action)

            # ──── 3. PDF formunu POST et ────
            if pdf_btn_id:
                result = self._submit_jsf_form(
                    sess, action_url, form_id, pdf_btn_id, view_state
                )
                if result:
                    content_type = result.headers.get('Content-Type', '')
                    _logger.info("E-Arşiv PDF yanıtı: %s (%d bytes)",
                                 content_type, len(result.content))

                    # PDF geldi mi?
                    if b'%PDF' in result.content[:10]:
                        return Response(
                            result.content,
                            status=200,
                            headers={
                                'Content-Type': 'application/pdf',
                                'Content-Disposition': 'inline',
                                'Cache-Control': 'no-cache',
                            },
                        )

                    # HTML fatura gelmiş olabilir (e-arşiv HTML görünümü)
                    if 'html' in content_type.lower() or b'<html' in result.content[:100].lower():
                        return self._serve_invoice_html(result.content, base_url)

            # ──── 4. PDF bulunamadıysa HTML dene ────
            if html_btn_id:
                result = self._submit_jsf_form(
                    sess, action_url, form_id, html_btn_id, view_state
                )
                if result:
                    content_type = result.headers.get('Content-Type', '')
                    if 'html' in content_type.lower() or b'<html' in result.content[:100].lower():
                        return self._serve_invoice_html(result.content, base_url)

            # ──── 5. Fallback: Doğrudan URL'ler dene ────
            return self._try_direct_urls(sess, url, base_url)

        except http_requests.exceptions.Timeout:
            _logger.error("E-Arşiv timeout: %s", url)
            return self._error_response('Fatura sunucusuna bağlanılamadı (timeout)')
        except Exception as e:
            _logger.error("E-Arşiv hatası: %s - %s", url, e)
            return self._error_response(f'Fatura yüklenirken hata: {str(e)}')

    def _extract_view_state(self, html):
        """JSF ViewState değerini HTML'den çıkarır."""
        patterns = [
            r'name="javax\.faces\.ViewState"\s+value="([^"]*)"',
            r'value="([^"]*)"\s+name="javax\.faces\.ViewState"',
            r'id="j_id1:javax\.faces\.ViewState:0"\s+value="([^"]*)"',
            r'javax\.faces\.ViewState[^>]+value="([^"]*)"',
        ]
        for p in patterns:
            m = re.search(p, html)
            if m:
                return m.group(1)
        return ''

    def _extract_form_info(self, html):
        """JSF form bilgilerini (form_id, action, buton ID'leri) çıkarır."""
        # Form bul
        form_match = re.search(
            r'<form\s+[^>]*id="([^"]*)"[^>]*action="([^"]*)"[^>]*>',
            html, re.IGNORECASE
        )
        if not form_match:
            # action önce gelebilir
            form_match = re.search(
                r'<form\s+[^>]*action="([^"]*)"[^>]*id="([^"]*)"[^>]*>',
                html, re.IGNORECASE
            )
            if form_match:
                form_id = form_match.group(2)
                form_action = form_match.group(1)
            else:
                return None
        else:
            form_id = form_match.group(1)
            form_action = form_match.group(2)

        # PDF butonu bul — çeşitli kalıplar
        pdf_btn_id = ''
        html_btn_id = ''

        # Kalıp 1: <a> veya <input> ile PDF/HTML metni
        # commandLink/commandButton kalıbı: id="formId:j_idt7" ...>PDF Görüntüle</a>
        links = re.findall(
            r'id="([^"]*)"[^>]*>([^<]*(?:PDF|pdf)[^<]*)<',
            html, re.IGNORECASE
        )
        for lid, ltext in links:
            if 'pdf' in ltext.lower() and 'görüntüle' in ltext.lower():
                pdf_btn_id = lid
                break
            if 'pdf' in ltext.lower() and not pdf_btn_id:
                pdf_btn_id = lid

        links_html = re.findall(
            r'id="([^"]*)"[^>]*>([^<]*(?:HTML|html)[^<]*)<',
            html, re.IGNORECASE
        )
        for lid, ltext in links_html:
            if 'html' in ltext.lower() and 'görüntüle' in ltext.lower():
                html_btn_id = lid
                break
            if 'html' in ltext.lower() and not html_btn_id:
                html_btn_id = lid

        # Kalıp 2: onclick="mojarra.jsfcljs(...)" içinden ID çıkar
        if not pdf_btn_id:
            onclick_matches = re.findall(
                r"mojarra\.jsfcljs\([^,]+,\{'([^']+)':'[^']+'\}",
                html
            )
            # Her onclick match için bağlamına bak
            for om in onclick_matches:
                # Bu ID'nin çevresinde "PDF" metni var mı?
                idx = html.find(om)
                context = html[max(0, idx - 100):idx + 200]
                if re.search(r'PDF\s*G', context, re.IGNORECASE):
                    pdf_btn_id = om
                elif re.search(r'HTML\s*G', context, re.IGNORECASE):
                    html_btn_id = om

        # Kalıp 3: input type="submit" value="PDF Görüntüle"
        if not pdf_btn_id:
            submit_match = re.search(
                r'<input[^>]*value="[^"]*PDF[^"]*"[^>]*name="([^"]*)"',
                html, re.IGNORECASE
            )
            if submit_match:
                pdf_btn_id = submit_match.group(1)

        _logger.info(
            "E-Arşiv JSF form: id=%s, action=%s, pdf=%s, html=%s",
            form_id, form_action, pdf_btn_id, html_btn_id
        )

        return {
            'form_id': form_id,
            'form_action': form_action,
            'pdf_btn_id': pdf_btn_id,
            'html_btn_id': html_btn_id,
        }

    def _submit_jsf_form(self, sess, action_url, form_id, btn_id, view_state):
        """JSF formunu submit eder (commandLink/commandButton simülasyonu)."""
        form_data = {
            form_id: form_id,
            btn_id: btn_id,
            'javax.faces.ViewState': view_state,
        }

        _logger.info("E-Arşiv JSF form submit: %s → btn=%s", action_url, btn_id)

        try:
            resp = sess.post(
                action_url,
                data=form_data,
                timeout=30,
                allow_redirects=True,
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Faces-Request': 'partial/ajax',
                },
            )
            resp.raise_for_status()

            # Ajax redirect olabilir
            if b'redirect url=' in resp.content or b'<redirect' in resp.content:
                redirect_match = re.search(
                    r'(?:redirect\s+url="|<redirect[^>]+url=")([^"]*)',
                    resp.text
                )
                if redirect_match:
                    redirect_url = redirect_match.group(1)
                    if not redirect_url.startswith('http'):
                        from urllib.parse import urljoin
                        redirect_url = urljoin(action_url, redirect_url)
                    _logger.info("E-Arşiv redirect: %s", redirect_url)
                    resp = sess.get(redirect_url, timeout=30, allow_redirects=True)

            # Faces-Request header olmadan tekrar dene (non-ajax)
            if len(resp.content) < 200 and b'%PDF' not in resp.content:
                _logger.info("E-Arşiv: Ajax yanıt küçük, non-ajax deneniyor")
                resp = sess.post(
                    action_url,
                    data=form_data,
                    timeout=30,
                    allow_redirects=True,
                    headers={
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                )

            return resp
        except Exception as e:
            _logger.warning("E-Arşiv JSF submit hatası: %s", e)
            return None

    def _try_direct_urls(self, sess, original_url, base_url):
        """Alternatif URL kalıplarını dener."""
        from urllib.parse import urlparse, parse_qs

        # webValidationKey'i çıkar
        parsed = urlparse(original_url)
        qs = parse_qs(parsed.query)
        wvk = qs.get('webValidationKey', [''])[0]

        # Denenecek URL kalıpları
        patterns = [
            f"{base_url}/earchive/pdf/goruntule",
            f"{base_url}/earchive/pdf/goruntule?webValidationKey={wvk}",
            f"{base_url}/earchive/download-pdf-earchive?webValidationKey={wvk}",
            f"{base_url}/earchive/download-earchive?webValidationKey={wvk}&docType=PDF",
            f"{base_url}/earchive/view-earchive/download-pdf-earchive.xhtml?webValidationKey={wvk}",
            f"{base_url}/earchive/html/goruntule",
            f"{base_url}/earchive/html/goruntule?webValidationKey={wvk}",
        ]

        for pattern_url in patterns:
            try:
                _logger.info("E-Arşiv alternatif URL deneniyor: %s", pattern_url)
                resp = sess.get(pattern_url, timeout=15, allow_redirects=True)
                if resp.status_code == 200 and len(resp.content) > 500:
                    ct = resp.headers.get('Content-Type', '')

                    # PDF bulunduysa
                    if b'%PDF' in resp.content[:10]:
                        _logger.info("E-Arşiv PDF bulundu: %s", pattern_url)
                        return Response(
                            resp.content,
                            status=200,
                            headers={
                                'Content-Type': 'application/pdf',
                                'Content-Disposition': 'inline',
                                'Cache-Control': 'no-cache',
                            },
                        )

                    # HTML fatura bulunduysa
                    if ('html' in ct.lower() and
                            b'<html' in resp.content[:200].lower() and
                            b'e-Ar' in resp.content[:2000]):
                        _logger.info("E-Arşiv HTML bulundu: %s", pattern_url)
                        return self._serve_invoice_html(resp.content, base_url)

            except Exception as e:
                _logger.debug("E-Arşiv URL deneme hatası %s: %s", pattern_url, e)
                continue

        # SON ÇARE: Portal sayfasını doğrudan göster
        _logger.warning("E-Arşiv: Hiçbir yöntem çalışmadı, portal sayfası gösteriliyor")
        return Response(
            self._wrap_portal_redirect(original_url),
            status=200,
            headers={'Content-Type': 'text/html; charset=utf-8'},
        )

    def _serve_invoice_html(self, content, base_url):
        """Fatura HTML'ini serve eder. Relative URL'leri düzeltir."""
        html = content
        if isinstance(html, bytes):
            # Encoding tespit et
            encoding = 'utf-8'
            enc_match = re.search(rb'charset[=\s]*"?([^"\s;>]+)', html[:500])
            if enc_match:
                encoding = enc_match.group(1).decode('ascii', errors='ignore')
            try:
                html = html.decode(encoding, errors='replace')
            except Exception:
                html = html.decode('utf-8', errors='replace')

        # Relative src/href URL'lerini absolute yap
        html = re.sub(
            r'(src|href)="(?!http|data:)(/[^"]*)"',
            rf'\1="{base_url}\2"',
            html
        )

        # Print butonu ekle
        print_bar = '''
        <div id="ea-print-bar" style="
            position:fixed; top:0; left:0; right:0; z-index:99999;
            background:linear-gradient(135deg,#714B67,#875A7B);
            padding:8px 16px; display:flex; align-items:center;
            justify-content:space-between; gap:8px;
            font-family:Arial,sans-serif; box-shadow:0 2px 8px rgba(0,0,0,0.3);">
            <span style="color:#fff;font-size:14px;font-weight:600;">
                📄 E-Arşiv Fatura
            </span>
            <div>
                <button onclick="
                    document.getElementById('ea-print-bar').style.display='none';
                    window.print();
                    setTimeout(function(){
                        document.getElementById('ea-print-bar').style.display='flex';
                    },1000);
                " style="
                    background:#28a745;color:#fff;border:none;border-radius:6px;
                    padding:6px 16px;font-size:13px;font-weight:600;cursor:pointer;
                    margin-right:8px;">
                    🖨️ Yazdır
                </button>
            </div>
        </div>
        <div style="height:44px;"></div>
        '''

        # Body açılışından sonra print bar ekle
        html = re.sub(
            r'(<body[^>]*>)',
            rf'\1{print_bar}',
            html,
            count=1,
            flags=re.IGNORECASE
        )

        return Response(
            html.encode('utf-8'),
            status=200,
            headers={
                'Content-Type': 'text/html; charset=utf-8',
                'Cache-Control': 'no-cache',
            },
        )

    def _wrap_portal_redirect(self, url):
        """Son çare: kullanıcıyı portal sayfasına yönlendir."""
        return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>E-Arşiv Fatura</title></head>
<body style="margin:0;font-family:Arial,sans-serif;display:flex;
    flex-direction:column;align-items:center;justify-content:center;
    min-height:100vh;background:#f5f5f5;color:#333;">
    <div style="text-align:center;padding:2rem;">
        <p style="font-size:1.2rem;margin-bottom:1rem;">
            ⚠️ PDF doğrudan yüklenemedi.
        </p>
        <a href="{url}" target="_blank" style="
            display:inline-block;background:#714B67;color:#fff;
            text-decoration:none;padding:12px 24px;border-radius:8px;
            font-size:1rem;font-weight:600;">
            📄 Fatura Portalını Aç
        </a>
    </div>
</body>
</html>'''

    def _error_response(self, message):
        """Hata sayfası döndürür."""
        return Response(
            f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Hata</title></head>
<body style="margin:0;font-family:Arial,sans-serif;display:flex;
    align-items:center;justify-content:center;min-height:100vh;
    background:#fff5f5;color:#c33;">
    <div style="text-align:center;padding:2rem;">
        <p style="font-size:3rem;margin:0;">⚠️</p>
        <p style="font-size:1.1rem;">{message}</p>
    </div>
</body>
</html>''',
            status=200,
            headers={'Content-Type': 'text/html; charset=utf-8'},
        )
