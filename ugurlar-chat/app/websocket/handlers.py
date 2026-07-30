import logging
import json
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from app.websocket.manager import manager
from app.services.chat_service import ChatService
from app.schemas.chat import ChatSendRequest

logger = logging.getLogger(__name__)

async def chat_websocket_endpoint(websocket: WebSocket, conversation_uid: str, db: AsyncSession):
    """Sohbet WebSocket bağlantısını yönetir"""
    await manager.connect(websocket, conversation_uid)
    service = ChatService(db)
    
    try:
        while True:
            # {type: 'message'|'typing'|'read', data: {...}}
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                msg_type = payload.get("type")
                
                if msg_type == "message":
                    # İstemciden gelen bir mesajı işle
                    req = ChatSendRequest(**payload.get("data", {}))
                    await service.send_message(req)
                elif msg_type == "typing":
                    # Yazıyor bilgisini yönet
                    pass
                elif msg_type == "read":
                    # Okundu bilgisini yönet
                    pass
                else:
                    logger.warning(f"Bilinmeyen mesaj türü: {msg_type}")
            except Exception as e:
                logger.error(f"WebSocket mesajı işlenirken hata: {e}")
                
    except WebSocketDisconnect:
        await manager.disconnect(websocket, conversation_uid)
    except Exception as e:
        logger.error(f"WebSocket hatası {conversation_uid}: {e}")
        await manager.disconnect(websocket, conversation_uid)
