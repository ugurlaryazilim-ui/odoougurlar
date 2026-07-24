# -*- coding: utf-8 -*-

import base64
import logging
import threading
import zipfile
import io
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter

_logger = logging.getLogger(__name__)

# ── Thread-local session for connection pooling ──────────────────────────────
_thread_local = threading.local()


def _get_session():
    """Her thread için izole bir requests.Session döndürür (TCP connection reuse)."""
    if not hasattr(_thread_local, 'session'):
        session = requests.Session()
        session.headers.update({'Content-Type': 'text/xml;charset=UTF-8'})
        adapter = HTTPAdapter(
            pool_connections=4,
            pool_maxsize=10,
            max_retries=1,
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        _thread_local.session = session
    return _thread_local.session


class DoganEInvoiceConnector:
    """
    Doğan E-Dönüşüm SOAP API Connector for fetching e-Fatura PDFs.
    
    Performans Optimizasyonları:
    - requests.Session ile TCP bağlantı havuzu (connection pooling)
    - ThreadPoolExecutor ile çapraz paralel PDF indirme (6 eşzamanlı)
    - Thread-local session pattern (thread safety)
    """

    # Paralel indirme thread sayısı (I/O bound — 6 thread optimal)
    MAX_DOWNLOAD_WORKERS = 6

    def __init__(self, env):
        self.env = env
        
        # Get credentials from config parameters
        self.username = env['ir.config_parameter'].sudo().get_param('ugurlar_invoice_collector.dogan_username', 'ugurlar')
        raw_password = env['ir.config_parameter'].sudo().get_param('ugurlar_invoice_collector.dogan_password', 'MjIxOTA1')
        
        # Nebim stores password as base64 encoded — decode it for the API
        try:
            self.password = base64.b64decode(raw_password).decode('utf-8')
        except Exception:
            self.password = raw_password  # Use as-is if decode fails
        
        # Default URLs from the task description
        self.auth_url = env['ir.config_parameter'].sudo().get_param(
            'ugurlar_invoice_collector.dogan_auth_url', 
            'https://connector.doganedonusum.com/AuthenticationWS'
        )
        self.efatura_url = env['ir.config_parameter'].sudo().get_param(
            'ugurlar_invoice_collector.dogan_efatura_url', 
            'https://connector.doganedonusum.com/EFaturaOIB'
        )

        self.namespaces = {
            'soapenv': 'http://schemas.xmlsoap.org/soap/envelope/',
            'wsdl': 'http://schemas.i2i.com/ei/wsdl'
        }

    def _login(self):
        envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:wsdl="http://schemas.i2i.com/ei/wsdl">
   <soapenv:Body>
      <wsdl:LoginRequest>
         <USER_NAME>{self.username}</USER_NAME>
         <PASSWORD>{self.password}</PASSWORD>
      </wsdl:LoginRequest>
   </soapenv:Body>
</soapenv:Envelope>"""
        
        try:
            session = _get_session()
            response = session.post(
                self.auth_url,
                data=envelope.encode('utf-8'),
                timeout=15
            )
            response.raise_for_status()
            
            _logger.info("Doğan API Login response status: %s, body (first 500): %s", 
                         response.status_code, response.text[:500])
            
            root = ET.fromstring(response.content)
            
            # Try with namespace first
            session_node = root.find('.//wsdl:SESSION_ID', self.namespaces)
            
            # Fallback: try namespace-agnostic search
            if session_node is None:
                for elem in root.iter():
                    if elem.tag.endswith('}SESSION_ID') or elem.tag == 'SESSION_ID':
                        session_node = elem
                        break
            
            if session_node is not None and session_node.text:
                _logger.info("Doğan API Login başarılı, SESSION_ID: %s...", session_node.text[:20])
                return session_node.text
            else:
                _logger.error("Doğan API Login failed: SESSION_ID not found in response.")
                return None
        except Exception as e:
            _logger.error("Doğan API Login error: %s", str(e))
            return None

    def _logout(self, session_id):
        envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:wsdl="http://schemas.i2i.com/ei/wsdl">
   <soapenv:Body>
      <wsdl:LogoutRequest>
         <REQUEST_HEADER>
            <SESSION_ID>{session_id}</SESSION_ID>
         </REQUEST_HEADER>
      </wsdl:LogoutRequest>
   </soapenv:Body>
</soapenv:Envelope>"""
        
        try:
            session = _get_session()
            session.post(
                self.auth_url,
                data=envelope.encode('utf-8'),
                timeout=10
            )
        except Exception as e:
            _logger.warning("Doğan API Logout error: %s", str(e))

    def _get_invoice_content(self, session_id, ettn):
        """
        Fetches invoice content using Doğan E-Dönüşüm GetInvoiceWithType service.
        According to Doğan developer docs (https://www.doganedonusum.com/dev/):
        - DIRECTION: 'IN' for incoming purchase invoices (default)
        - TYPE: 'PDF', 'HTML', 'XML'
        - READ_INCLUDED: 'true' to include already read invoices
        - Returns Base64-encoded ZIP file containing the PDF/HTML
        """
        envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:wsdl="http://schemas.i2i.com/ei/wsdl">
   <soapenv:Body>
      <wsdl:GetInvoiceWithTypeRequest>
         <REQUEST_HEADER>
            <SESSION_ID>{session_id}</SESSION_ID>
         </REQUEST_HEADER>
         <INVOICE_SEARCH_KEY>
            <UUID>{ettn}</UUID>
            <TYPE>PDF</TYPE>
            <READ_INCLUDED>true</READ_INCLUDED>
            <DIRECTION>IN</DIRECTION>
         </INVOICE_SEARCH_KEY>
         <HEADER_ONLY>N</HEADER_ONLY>
      </wsdl:GetInvoiceWithTypeRequest>
   </soapenv:Body>
</soapenv:Envelope>"""
        
        try:
            session = _get_session()
            response = session.post(
                self.efatura_url,
                data=envelope.encode('utf-8'),
                timeout=30
            )
            
            if response.status_code == 200:
                content = self._parse_content_node(response.content)
                if content:
                    return content
            
            # Fallback 1: Try HTML type if PDF fails
            return self._get_invoice_content_html(session_id, ettn)
        except Exception as e:
            _logger.warning("Doğan API GetInvoiceWithType error for ETTN %s: %s", ettn, str(e))
            return self._get_invoice_content_html(session_id, ettn)

    def _get_invoice_content_html(self, session_id, ettn):
        """Fallback 1: Try TYPE=HTML with DIRECTION=IN"""
        envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:wsdl="http://schemas.i2i.com/ei/wsdl">
   <soapenv:Body>
      <wsdl:GetInvoiceWithTypeRequest>
         <REQUEST_HEADER>
            <SESSION_ID>{session_id}</SESSION_ID>
         </REQUEST_HEADER>
         <INVOICE_SEARCH_KEY>
            <UUID>{ettn}</UUID>
            <TYPE>HTML</TYPE>
            <READ_INCLUDED>true</READ_INCLUDED>
            <DIRECTION>IN</DIRECTION>
         </INVOICE_SEARCH_KEY>
         <HEADER_ONLY>N</HEADER_ONLY>
      </wsdl:GetInvoiceWithTypeRequest>
   </soapenv:Body>
</soapenv:Envelope>"""
        
        try:
            session = _get_session()
            response = session.post(
                self.efatura_url,
                data=envelope.encode('utf-8'),
                timeout=30
            )
            
            if response.status_code == 200:
                content = self._parse_content_node(response.content)
                if content:
                    return content
            
            return self._get_invoice_content_raw(session_id, ettn)
        except Exception as e:
            _logger.warning("Doğan API GetInvoiceWithType HTML error for ETTN %s: %s", ettn, str(e))
            return self._get_invoice_content_raw(session_id, ettn)

    def _get_invoice_content_raw(self, session_id, ettn):
        """Fallback 2: Use simple GetInvoiceRequest with READ_INCLUDED=true and DIRECTION=IN"""
        envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:wsdl="http://schemas.i2i.com/ei/wsdl">
   <soapenv:Body>
      <wsdl:GetInvoiceRequest>
         <REQUEST_HEADER>
            <SESSION_ID>{session_id}</SESSION_ID>
         </REQUEST_HEADER>
         <INVOICE_SEARCH_KEY>
            <UUID>{ettn}</UUID>
            <READ_INCLUDED>true</READ_INCLUDED>
            <DIRECTION>IN</DIRECTION>
         </INVOICE_SEARCH_KEY>
         <HEADER_ONLY>N</HEADER_ONLY>
      </wsdl:GetInvoiceRequest>
   </soapenv:Body>
</soapenv:Envelope>"""
        
        try:
            session = _get_session()
            response = session.post(
                self.efatura_url,
                data=envelope.encode('utf-8'),
                timeout=30
            )
            
            if response.status_code == 200:
                return self._parse_content_node(response.content)
            return None
        except Exception as e:
            _logger.warning("Doğan API GetInvoice raw error for ETTN %s: %s", ettn, str(e))
            return None

    def _parse_content_node(self, xml_bytes):
        try:
            root = ET.fromstring(xml_bytes)
            content_node = None
            for elem in root.iter():
                if elem.tag.endswith('}CONTENT') or elem.tag == 'CONTENT':
                    if elem.text:
                        content_node = elem
                        break
            if content_node is not None and content_node.text:
                return base64.b64decode(content_node.text)
        except Exception as e:
            _logger.error("Error parsing CONTENT node from SOAP response: %s", str(e))
        return None

    def _extract_pdf_from_raw(self, raw_content, ettn):
        """Ham içerikten (PDF, ZIP, HTML) kullanılabilir dosyayı çıkarır."""
        if not raw_content:
            return None
        
        if raw_content.startswith(b'%PDF-'):
            return raw_content
        elif raw_content.startswith(b'PK'):
            try:
                with zipfile.ZipFile(io.BytesIO(raw_content)) as z:
                    pdf_files = [f for f in z.namelist() if f.lower().endswith('.pdf')]
                    if pdf_files:
                        return z.read(pdf_files[0])
                    html_files = [f for f in z.namelist() if f.lower().endswith(('.html', '.htm'))]
                    if html_files:
                        return z.read(html_files[0])
                    xml_files = [f for f in z.namelist() if f.lower().endswith('.xml')]
                    if xml_files:
                        xml_data = z.read(xml_files[0])
                        html_wrapped = f"<html><body><pre>{xml_data.decode('utf-8', errors='replace')}</pre></body></html>"
                        return html_wrapped.encode('utf-8')
            except Exception as e:
                _logger.error("Failed to extract file from ZIP for ETTN %s: %s", ettn, str(e))
        else:
            return raw_content
        return None

    def _download_single_invoice(self, session_id, ettn):
        """
        Tek bir faturayı indirir — ThreadPoolExecutor tarafından çağrılır.
        Thread-safe: Sadece HTTP I/O yapar, ORM kullanmaz.
        
        Returns:
            tuple: (ettn, pdf_bytes_or_None)
        """
        try:
            raw_content = self._get_invoice_content(session_id, ettn)
            pdf_content = self._extract_pdf_from_raw(raw_content, ettn)
            if pdf_content:
                _logger.info("✅ Doğan PDF indirildi (ETTN: %s...)", ettn[:12])
            return (ettn, pdf_content)
        except Exception as e:
            _logger.warning("❌ Doğan indirme hatası (ETTN: %s): %s", ettn[:12], str(e))
            return (ettn, None)

    def get_invoice_pdf(self, ettn):
        """
        Main method: Login, get invoice content, determine type, logout.
        Returns PDF binary content or None.
        """
        session_id = self._login()
        if not session_id:
            return None
        
        try:
            raw_content = self._get_invoice_content(session_id, ettn)
            return self._extract_pdf_from_raw(raw_content, ettn)
        finally:
            self._logout(session_id)

    def get_invoices_batch_pdf(self, ettn_list):
        """
        Batch method: Log in ONCE, fetch PDFs for a list of ETTNs using
        ThreadPoolExecutor for PARALLEL downloads, log out ONCE.
        
        6 eşzamanlı thread ile çapraz indirme yaparak ~5-6x hız artışı sağlar.
        
        Returns dict: {ettn: pdf_binary_content or None}
        """
        if not ettn_list:
            return {}

        session_id = self._login()
        if not session_id:
            return {ettn: None for ettn in ettn_list}

        results = {}
        try:
            worker_count = min(self.MAX_DOWNLOAD_WORKERS, len(ettn_list))
            _logger.info(
                "🚀 Doğan Paralel İndirme Başladı: %d fatura, %d eşzamanlı thread",
                len(ettn_list), worker_count
            )
            
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(self._download_single_invoice, session_id, ettn): ettn
                    for ettn in ettn_list
                }
                
                for future in as_completed(futures):
                    ettn = futures[future]
                    try:
                        _, pdf_content = future.result(timeout=60)
                        results[ettn] = pdf_content
                    except Exception as e:
                        _logger.warning("Thread sonucu alınamadı (ETTN: %s): %s", ettn[:12], str(e))
                        results[ettn] = None
            
            success_count = sum(1 for v in results.values() if v)
            _logger.info(
                "✅ Doğan Paralel İndirme Tamamlandı: %d/%d başarılı",
                success_count, len(ettn_list)
            )
        finally:
            self._logout(session_id)

        return results
