import logging
import httpx
import os
from typing import Optional, Dict, Any

from app.models.conversation import Conversation
from app.models.message import Message

_logger = logging.getLogger(__name__)

class OdooBridge:
    """Odoo JSON-RPC üzerinden senkronizasyon sağlayan köprü sınıfı."""
    
    def __init__(self):
        self.enabled = os.getenv("ODOO_SYNC_ENABLED", "false").lower() == "true"
        self.odoo_url = os.getenv("ODOO_URL", "http://localhost:8069")
        self.db = os.getenv("ODOO_DB", "ugurlar")
        self.username = os.getenv("ODOO_USERNAME", "admin")
        self.password = os.getenv("ODOO_PASSWORD", "admin")
        self.session_id: Optional[str] = None

    async def authenticate(self, client: httpx.AsyncClient) -> bool:
        """Odoo ile kimlik doğrulaması yapar."""
        if not self.enabled:
            return False

        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "service": "common",
                    "method": "authenticate",
                    "args": [self.db, self.username, self.password, {}]
                },
                "id": 1
            }
            
            response = await client.post(f"{self.odoo_url}/jsonrpc", json=payload)
            response.raise_for_status()
            
            data = response.json()
            if data.get("error"):
                _logger.error(f"Odoo Auth Hatası: {data['error']}")
                return False
                
            self.session_id = data.get("result") # UID döner
            _logger.info(f"Odoo bağlantısı başarılı. UID: {self.session_id}")
            return True
            
        except Exception as e:
            _logger.error(f"Odoo kimlik doğrulama başarısız: {str(e)}")
            return False

    async def sync_conversation(self, conv: Conversation) -> Optional[int]:
        """Sohbet oturumunu Odoo'ya senkronize eder ve Odoo ID'sini döner."""
        if not self.enabled:
            return None

        async with httpx.AsyncClient() as client:
            if not self.session_id:
                auth_ok = await self.authenticate(client)
                if not auth_ok:
                    return None

            try:
                # Odoo'daki chat modeli varsayımsal: 'ugurlar.chat.conversation'
                payload = {
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "service": "object",
                        "method": "execute_kw",
                        "args": [
                            self.db, self.session_id, self.password,
                            "ugurlar.chat.conversation", "create",
                            [{
                                "uid": conv.uid,
                                "store_domain": conv.store_domain,
                                "customer_name": conv.customer_name,
                                "customer_email": conv.customer_email,
                                "state": conv.state,
                            }]
                        ]
                    },
                    "id": 2
                }
                
                response = await client.post(f"{self.odoo_url}/jsonrpc", json=payload)
                data = response.json()
                
                if data.get("error"):
                    _logger.error(f"Odoo sync_conversation hatası: {data['error']}")
                    return None
                    
                odoo_id = data.get("result")
                _logger.info(f"Odoo senkronizasyonu başarılı (Conversation). Odoo ID: {odoo_id}")
                return odoo_id
                
            except Exception as e:
                _logger.error(f"Odoo sync_conversation isteği başarısız: {str(e)}")
                # Odoo kapalı olsa da sistem çalışmaya devam etmeli.
                return None

    async def sync_message(self, msg: Message, odoo_conversation_id: int) -> Optional[int]:
        """Sohbet mesajını Odoo'ya senkronize eder."""
        if not self.enabled or not odoo_conversation_id:
            return None

        async with httpx.AsyncClient() as client:
            if not self.session_id:
                auth_ok = await self.authenticate(client)
                if not auth_ok:
                    return None

            try:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "service": "object",
                        "method": "execute_kw",
                        "args": [
                            self.db, self.session_id, self.password,
                            "ugurlar.chat.message", "create",
                            [{
                                "conversation_id": odoo_conversation_id,
                                "text": msg.text,
                                "sender_type": msg.sender_type,
                                "sender_name": msg.sender_name,
                            }]
                        ]
                    },
                    "id": 3
                }
                
                response = await client.post(f"{self.odoo_url}/jsonrpc", json=payload)
                data = response.json()
                
                if data.get("error"):
                    _logger.error(f"Odoo sync_message hatası: {data['error']}")
                    return None
                    
                odoo_id = data.get("result")
                _logger.info(f"Odoo senkronizasyonu başarılı (Message). Odoo ID: {odoo_id}")
                return odoo_id
                
            except Exception as e:
                _logger.error(f"Odoo sync_message isteği başarısız: {str(e)}")
                return None
