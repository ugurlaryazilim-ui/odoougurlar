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
        # Try GetInvoiceWithType first (without TYPE=PDF, get raw content)
        envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:wsdl="http://schemas.i2i.com/ei/wsdl">
   <soapenv:Body>
      <wsdl:GetInvoiceWithTypeRequest>
         <REQUEST_HEADER>
            <SESSION_ID>{session_id}</SESSION_ID>
         </REQUEST_HEADER>
         <INVOICE_SEARCH_KEY>
            <UUID>{ettn}</UUID>
            <TYPE>PDF</TYPE>
            <DIRECTION>INBOUND</DIRECTION>
            <READ_INCLUDED>true</READ_INCLUDED>
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
            
            _logger.info("Doğan API GetInvoice response status: %s, body (first 2000): %s",
                         response.status_code, response.text[:2000])
            
            if response.status_code != 200:
                # Try alternative: GetInvoice (without WithType)
                _logger.info("GetInvoiceWithType failed, trying GetInvoice...")
                return self._get_invoice_content_v2(session_id, ettn)
            
            root = ET.fromstring(response.content)
            
            # Namespace-agnostic search for CONTENT element
            content_node = None
            for elem in root.iter():
                if elem.tag.endswith('}CONTENT') or elem.tag == 'CONTENT':
                    if elem.text:
                        content_node = elem
                        break
            
            if content_node is not None and content_node.text:
                return base64.b64decode(content_node.text)
            else:
                _logger.warning("Doğan API GetInvoice: CONTENT element not found or empty for ETTN %s", ettn)
                return None
        except Exception as e:
            _logger.error("Doğan API GetInvoice error for ETTN %s: %s", ettn, str(e))
            return None

    def _get_invoice_content_v2(self, session_id, ettn):
        """Fallback: Use GetInvoice instead of GetInvoiceWithType"""
        envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:wsdl="http://schemas.i2i.com/ei/wsdl">
   <soapenv:Body>
      <wsdl:GetInvoiceRequest>
         <REQUEST_HEADER>
            <SESSION_ID>{session_id}</SESSION_ID>
         </REQUEST_HEADER>
         <INVOICE_SEARCH_KEY>
            <UUID>{ettn}</UUID>
            <DIRECTION>INBOUND</DIRECTION>
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
            
            _logger.info("Doğan API GetInvoice v2 response status: %s, body (first 2000): %s",
                         response.status_code, response.text[:2000])
            
            if response.status_code != 200:
                return None
            
            root = ET.fromstring(response.content)
            
            content_node = None
            for elem in root.iter():
                if elem.tag.endswith('}CONTENT') or elem.tag == 'CONTENT':
                    if elem.text:
                        content_node = elem
                        break
            
            if content_node is not None and content_node.text:
                return base64.b64decode(content_node.text)
            else:
                _logger.warning("Doğan API GetInvoice v2: CONTENT not found for ETTN %s", ettn)
                return None
        except Exception as e:
            _logger.error("Doğan API GetInvoice v2 error for ETTN %s: %s", ettn, str(e))
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
                    # It's a ZIP, extract the XML
                    try:
                        with zipfile.ZipFile(io.BytesIO(raw_content)) as z:
                            for filename in z.namelist():
                                if filename.lower().endswith('.xml'):
                                    xml_data = z.read(filename)
                                    # Wrap the extracted XML in basic HTML
                                    html_wrapped = f"<html><body><pre>{xml_data.decode('utf-8', errors='replace')}</pre></body></html>"
                                    pdf_content = html_wrapped.encode('utf-8')
                                    break
                    except Exception as e:
                        _logger.error("Failed to extract XML from ZIP for ETTN %s: %s", ettn, str(e))
                else:
                    # If it's directly XML or other raw text
                    html_wrapped = f"<html><body><pre>{raw_content.decode('utf-8', errors='replace')}</pre></body></html>"
                    pdf_content = html_wrapped.encode('utf-8')
        finally:
            self._logout(session_id)
            
        return pdf_content
