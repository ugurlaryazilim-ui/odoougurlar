import json
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.chat import (
    ChatStartRequest,
    ChatStartResponse,
    ChatSendRequest,
    ChatSendResponse,
    ChatPollResponse,
    QuickReply,
    MessageSchema
)
from app.redis_client import get_redis

# Servis logger'ı
_logger = logging.getLogger(__name__)

# Hızlı Yanıtlar (Türkçe)
QUICK_REPLIES = [
    QuickReply(id="qr_1", label="Sipariş Durumu", message="Siparişim ne durumda?"),
    QuickReply(id="qr_2", label="İade & Değişim", message="İade ve değişim koşulları nelerdir?"),
    QuickReply(id="qr_3", label="Kargo Bilgisi", message="Kargom ne zaman ulaşır?"),
    QuickReply(id="qr_4", label="Beden Bilgisi", message="Beden tablosu hakkında bilgi alabilir miyim?"),
    QuickReply(id="qr_5", label="Canlı Destek", message="Canlı destek ile görüşmek istiyorum"),
]

WELCOME_MSG_TEXT = "Merhaba! 👋 Uğurlar'a hoş geldiniz. Size nasıl yardımcı olabiliriz?"


class ChatService:
    """Sohbet iş mantığı servisi"""

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db

    async def _get_redis(self):
        """Redis bağlantısı al"""
        try:
            return await get_redis()
        except Exception as e:
            _logger.warning(f"Redis bağlantı hatası: {e}")
            return None

    async def _publish_message(self, conversation_uid: str, msg_type: str, message: Message):
        """Redis Pub/Sub üzerinden mesaj yayınla"""
        redis = await self._get_redis()
        if redis:
            try:
                channel = f"chat:{conversation_uid}"
                msg_data = json.dumps({
                    "type": msg_type,
                    "message": {
                        "id": message.id,
                        "text": message.text,
                        "sender_type": message.sender_type,
                        "sender_name": message.sender_name,
                        "created_at": message.created_at.isoformat() if message.created_at else None,
                        "is_read": False
                    }
                })
                await redis.publish(channel, msg_data)
            except Exception as e:
                _logger.warning(f"Redis publish hatası: {e}")

    async def start_conversation(self, data: ChatStartRequest) -> ChatStartResponse:
        """Yeni bir sohbet oturumu başlatır."""
        _logger.info(f"Sohbet başlatılıyor: {data.shop_domain}")

        # 1. Veritabanında oturum oluştur
        conversation = Conversation(
            store_domain=data.shop_domain,
            customer_name=data.customer_name,
            customer_email=data.customer_email,
            page_url=data.page_url,
            page_title=data.page_title,
            state="open"
        )
        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)

        # 2. Hoş geldin mesajı oluştur
        welcome_message = Message(
            conversation_id=conversation.id,
            text=WELCOME_MSG_TEXT,
            sender_type="system",
            sender_name="Uğurlar Destek"
        )
        self.db.add(welcome_message)
        await self.db.commit()
        await self.db.refresh(welcome_message)

        _logger.info(f"Oturum oluşturuldu: {conversation.uid}")

        return ChatStartResponse(
            success=True,
            conversation_uid=conversation.uid,
            welcome_message=WELCOME_MSG_TEXT,
            quick_replies=QUICK_REPLIES
        )

    async def send_message(self, data: ChatSendRequest) -> ChatSendResponse:
        """Müşteriden gelen bir mesajı kaydeder."""
        # 1. Oturumu bul
        result = await self.db.execute(select(Conversation).filter_by(uid=data.conversation_uid))
        conversation = result.scalars().first()

        if not conversation:
            _logger.error(f"Oturum bulunamadı: {data.conversation_uid}")
            raise ValueError("Oturum bulunamadı")

        if conversation.state == "closed":
            raise ValueError("Bu sohbet kapalı")

        # Müşteri bilgisini güncelle
        if data.customer_name and not conversation.customer_name:
            conversation.customer_name = data.customer_name
        if data.customer_email and not conversation.customer_email:
            conversation.customer_email = data.customer_email

        # 2. Mesajı veritabanına kaydet
        new_message = Message(
            conversation_id=conversation.id,
            text=data.message,
            sender_type="customer",
            sender_name=conversation.customer_name or "Müşteri"
        )
        self.db.add(new_message)
        await self.db.commit()
        await self.db.refresh(new_message)

        # 3. Redis'e yayınla
        await self._publish_message(conversation.uid, "new_message", new_message)

        _logger.info(f"Mesaj kaydedildi: conv={conversation.uid}, msg_id={new_message.id}")

        return ChatSendResponse(
            success=True,
            message_id=new_message.id,
            sent_at=new_message.created_at
        )

    async def get_messages(self, conversation_uid: str, after_id: int = 0) -> List[MessageSchema]:
        """Bir oturumdaki mesajları getirir."""
        result = await self.db.execute(select(Conversation).filter_by(uid=conversation_uid))
        conversation = result.scalars().first()

        if not conversation:
            return []

        query = select(Message).filter(Message.conversation_id == conversation.id)
        if after_id > 0:
            query = query.filter(Message.id > after_id)

        query = query.order_by(Message.id.asc())
        msg_result = await self.db.execute(query)
        messages = msg_result.scalars().all()

        return [MessageSchema.model_validate(m) for m in messages]

    async def operator_reply(self, data) -> Dict[str, Any]:
        """Operatörden gelen bir yanıtı sisteme kaydeder."""
        result = await self.db.execute(select(Conversation).filter_by(uid=data.conversation_uid))
        conversation = result.scalars().first()

        if not conversation:
            raise ValueError("Oturum bulunamadı")

        # Operatör mesajını kaydet
        new_message = Message(
            conversation_id=conversation.id,
            text=data.message,
            sender_type="operator",
            sender_name=data.operator_name
        )
        self.db.add(new_message)

        # Durumu 'assigned' yap
        if conversation.state == "open":
            conversation.state = "assigned"
            conversation.operator_name = data.operator_name

        await self.db.commit()
        await self.db.refresh(new_message)

        # Redis'e yayınla
        await self._publish_message(conversation.uid, "operator_reply", new_message)

        _logger.info(f"Operatör yanıtı kaydedildi: {conversation.uid}")
        return {"success": True, "message_id": new_message.id}

    async def operator_typing(self, data) -> None:
        """Operatör yazıyor bilgisini iletir."""
        redis = await self._get_redis()
        if redis:
            try:
                channel = f"chat:{data.conversation_uid}"
                msg_data = json.dumps({
                    "type": "typing",
                    "operator_name": data.operator_name
                })
                await redis.publish(channel, msg_data)
            except Exception as e:
                _logger.warning(f"Typing publish hatası: {e}")

    async def operator_close(self, data) -> None:
        """Sohbeti kapatır."""
        result = await self.db.execute(select(Conversation).filter_by(uid=data.conversation_uid))
        conversation = result.scalars().first()

        if conversation:
            conversation.state = "closed"
            from datetime import datetime, timezone
            conversation.closed_at = datetime.now(timezone.utc)
            await self.db.commit()

            # Redis'e bildir
            redis = await self._get_redis()
            if redis:
                channel = f"chat:{data.conversation_uid}"
                await redis.publish(channel, json.dumps({"type": "closed"}))

            _logger.info(f"Sohbet kapatıldı: {data.conversation_uid}")

    async def get_quick_replies(self, store_id: str = None) -> List[QuickReply]:
        """Hızlı yanıtları döndürür."""
        return QUICK_REPLIES
