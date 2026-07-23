# -*- coding: utf-8 -*-

import base64
import logging
import zipfile
import io
import xml.etree.ElementTree as ET
import requests

from odoo import models, api

_logger = logging.getLogger(__name__)

class DoganEInvoiceConnector:
    """
    Doğan E-Dönüşüm SOAP API Connector for fetching e-Fatura PDFs.
    Uses basic requests and ElementTree to avoid zeep dependency.
    """
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
            response = requests.post(
                self.auth_url,
                data=envelope.encode('utf-8'),
                headers={'Content-Type': 'text/xml;charset=UTF-8'},
                timeout=15
            )
            response.raise_for_status()
            
            _logger.info("Doğan API Login response status: %s, body (first 2000): %s", 
                         response.status_code, response.text[:2000])
            
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
            requests.post(
                self.auth_url,
                data=envelope.encode('utf-8'),
                headers={'Content-Type': 'text/xml;charset=UTF-8'},
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
            response = requests.post(
                self.efatura_url,
                data=envelope.encode('utf-8'),
                headers={'Content-Type': 'text/xml;charset=UTF-8'},
                timeout=30
            )
            
            _logger.info("Doğan API GetInvoiceWithType (PDF, IN) status: %s, body (first 2000): %s",
                         response.status_code, response.text[:2000])
            
            if response.status_code == 200:
                content = self._parse_content_node(response.content)
                if content:
                    return content
            
            # Fallback 1: Try HTML type if PDF fails
            _logger.info("GetInvoiceWithType PDF failed/empty, trying HTML type...")
            return self._get_invoice_content_html(session_id, ettn)
        except Exception as e:
            _logger.error("Doğan API GetInvoiceWithType error for ETTN %s: %s", ettn, str(e))
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
            response = requests.post(
                self.efatura_url,
                data=envelope.encode('utf-8'),
                headers={'Content-Type': 'text/xml;charset=UTF-8'},
                timeout=30
            )
            
            _logger.info("Doğan API GetInvoiceWithType (HTML, IN) status: %s, body (first 2000): %s",
                         response.status_code, response.text[:2000])
            
            if response.status_code == 200:
                content = self._parse_content_node(response.content)
                if content:
                    return content
            
            _logger.info("GetInvoiceWithType HTML failed, trying raw GetInvoiceRequest...")
            return self._get_invoice_content_raw(session_id, ettn)
        except Exception as e:
            _logger.error("Doğan API GetInvoiceWithType HTML error for ETTN %s: %s", ettn, str(e))
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
            response = requests.post(
                self.efatura_url,
                data=envelope.encode('utf-8'),
                headers={'Content-Type': 'text/xml;charset=UTF-8'},
                timeout=30
            )
            
            _logger.info("Doğan API GetInvoice (raw, IN) status: %s, body (first 2000): %s",
                         response.status_code, response.text[:2000])
            
            if response.status_code == 200:
                return self._parse_content_node(response.content)
            return None
        except Exception as e:
            _logger.error("Doğan API GetInvoice raw error for ETTN %s: %s", ettn, str(e))
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

    def get_invoice_pdf(self, ettn):
        """
        Main method: Login, get invoice content, determine type, logout.
        Returns PDF binary content or None.
        """
        session_id = self._login()
        if not session_id:
            return None
        
        pdf_content = None
        try:
            raw_content = self._get_invoice_content(session_id, ettn)
            if raw_content:
                # Check magic bytes to see what we got
                if raw_content.startswith(b'%PDF-'):
                    pdf_content = raw_content
                elif raw_content.startswith(b'PK'):
                    # It's a ZIP file containing the invoice file (PDF, HTML, or XML)
                    try:
                        with zipfile.ZipFile(io.BytesIO(raw_content)) as z:
                            # 1. Look for PDF first
                            pdf_files = [f for f in z.namelist() if f.lower().endswith('.pdf')]
                            if pdf_files:
                                _logger.info("Extracted PDF '%s' from ZIP for ETTN %s", pdf_files[0], ettn)
                                pdf_content = z.read(pdf_files[0])
                            else:
                                # 2. Look for HTML
                                html_files = [f for f in z.namelist() if f.lower().endswith(('.html', '.htm'))]
                                if html_files:
                                    _logger.info("Extracted HTML '%s' from ZIP for ETTN %s", html_files[0], ettn)
                                    pdf_content = z.read(html_files[0])
                                else:
                                    # 3. Look for XML
                                    xml_files = [f for f in z.namelist() if f.lower().endswith('.xml')]
                                    if xml_files:
                                        _logger.info("Extracted XML '%s' from ZIP for ETTN %s", xml_files[0], ettn)
                                        xml_data = z.read(xml_files[0])
                                        html_wrapped = f"<html><body><pre>{xml_data.decode('utf-8', errors='replace')}</pre></body></html>"
                                        pdf_content = html_wrapped.encode('utf-8')
                    except Exception as e:
                        _logger.error("Failed to extract file from ZIP for ETTN %s: %s", ettn, str(e))
                else:
                    # If it's directly HTML or raw text
                    pdf_content = raw_content
        finally:
            self._logout(session_id)
            
        return pdf_content

    def get_invoices_batch_pdf(self, ettn_list):
        """
        Batch method: Log in ONCE, fetch PDFs for a list of ETTNs, log out ONCE.
        Returns dict: {ettn: pdf_binary_content or None}
        """
        if not ettn_list:
            return {}

        session_id = self._login()
        if not session_id:
            return {ettn: None for ettn in ettn_list}

        results = {}
        try:
            for ettn in ettn_list:
                pdf_content = None
                raw_content = self._get_invoice_content(session_id, ettn)
                if raw_content:
                    if raw_content.startswith(b'%PDF-'):
                        pdf_content = raw_content
                    elif raw_content.startswith(b'PK'):
                        try:
                            with zipfile.ZipFile(io.BytesIO(raw_content)) as z:
                                pdf_files = [f for f in z.namelist() if f.lower().endswith('.pdf')]
                                if pdf_files:
                                    _logger.info("Extracted PDF '%s' from ZIP for ETTN %s", pdf_files[0], ettn)
                                    pdf_content = z.read(pdf_files[0])
                                else:
                                    html_files = [f for f in z.namelist() if f.lower().endswith(('.html', '.htm'))]
                                    if html_files:
                                        _logger.info("Extracted HTML '%s' from ZIP for ETTN %s", html_files[0], ettn)
                                        pdf_content = z.read(html_files[0])
                                    else:
                                        xml_files = [f for f in z.namelist() if f.lower().endswith('.xml')]
                                        if xml_files:
                                            _logger.info("Extracted XML '%s' from ZIP for ETTN %s", xml_files[0], ettn)
                                            xml_data = z.read(xml_files[0])
                                            html_wrapped = f"<html><body><pre>{xml_data.decode('utf-8', errors='replace')}</pre></body></html>"
                                            pdf_content = html_wrapped.encode('utf-8')
                        except Exception as e:
                            _logger.error("Failed to extract file from ZIP for ETTN %s: %s", ettn, str(e))
                    else:
                        pdf_content = raw_content
                results[ettn] = pdf_content
        finally:
            self._logout(session_id)

        return results
