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
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                msg_type = payload.get("type")

                if msg_type == "ping":
                    # Heartbeat — pong ile yanıtla
                    await websocket.send_json({"type": "pong"})

                elif msg_type == "message":
                    # İstemciden gelen mesajı işle
                    msg_data = payload.get("data", {})
                    msg_data["conversation_uid"] = conversation_uid
                    req = ChatSendRequest(**msg_data)
                    result = await service.send_message(req)
                    await websocket.send_json({
                        "type": "message_sent",
                        "message_id": result.message_id,
                        "sent_at": result.sent_at.isoformat()
                    })

                elif msg_type == "typing":
                    pass  # Müşteri yazıyor bilgisi (ileride)

                elif msg_type == "read":
                    pass  # Okundu bilgisi (ileride)

                else:
                    logger.warning(f"Bilinmeyen mesaj türü: {msg_type}")

            except Exception as e:
                logger.error(f"WebSocket mesajı işlenirken hata: {e}")
                await websocket.send_json({"type": "error", "detail": str(e)})

    except WebSocketDisconnect:
        await manager.disconnect(websocket, conversation_uid)
    except Exception as e:
        logger.error(f"WebSocket hatası {conversation_uid}: {e}")
        await manager.disconnect(websocket, conversation_uid)
