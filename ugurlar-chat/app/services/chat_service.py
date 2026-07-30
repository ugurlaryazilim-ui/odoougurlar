import json
import logging
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.chat import (
    ChatStartRequest,
    ChatStartResponse,
    ChatSendRequest,
    ChatSendResponse,
    OperatorReplyRequest,
    QuickReply,
    MessageSchema
)

# Servis logger'ı
_logger = logging.getLogger(__name__)

# Örnek Hızlı Yanıtlar (Türkçe)
QUICK_REPLIES = [
    QuickReply(id="qr_1", label="Sipariş Durumu", message="Siparişim ne durumda?"),
    QuickReply(id="qr_2", label="İade & Değişim", message="İade ve değişim koşulları nelerdir?"),
    QuickReply(id="qr_3", label="Kargo Bilgisi", message="Kargom ne zaman ulaşır?"),
]

WELCOME_MSG_TEXT = "Merhaba! Uğurlar Chat'e hoş geldiniz. Size nasıl yardımcı olabilirim?"

async def start_conversation(
    db: AsyncSession, 
    redis_client: Any, # redis-py async client expected
    data: ChatStartRequest
) -> ChatStartResponse:
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
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)

    # 2. Hoş geldin mesajı oluştur (Sistem tarafından)
    welcome_message = Message(
        conversation_id=conversation.id,
        text=WELCOME_MSG_TEXT,
        sender_type="system",
        sender_name="Sistem"
    )
    db.add(welcome_message)
    await db.commit()

    # 3. Odoo senkronizasyonu arka plan kuyruğuna alınmalı (Mocked for now)
    # TODO: BackgroundTasks ile OdooBridge çağrılacak

    _logger.info(f"Oturum oluşturuldu: {conversation.uid}")

    return ChatStartResponse(
        success=True,
        conversation_uid=conversation.uid,
        welcome_message=WELCOME_MSG_TEXT,
        quick_replies=QUICK_REPLIES
    )


async def send_message(
    db: AsyncSession, 
    redis_client: Any, 
    data: ChatSendRequest
) -> ChatSendResponse:
    """Müşteriden gelen bir mesajı kaydeder."""
    # 1. Oturumu bul
    result = await db.execute(select(Conversation).filter_by(uid=data.conversation_uid))
    conversation = result.scalars().first()

    if not conversation:
        _logger.error(f"Oturum bulunamadı: {data.conversation_uid}")
        raise ValueError("Oturum bulunamadı")
        
    if conversation.state == "closed":
        _logger.warning(f"Kapalı oturuma mesaj gönderilmeye çalışıldı: {data.conversation_uid}")
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
    db.add(new_message)
    await db.commit()
    await db.refresh(new_message)

    # 3. Redis kanalına yayınla (Pub/Sub)
    channel = f"chat:{conversation.uid}"
    if redis_client:
        msg_data = json.dumps({
            "type": "new_message",
            "message": {
                "id": new_message.id,
                "text": new_message.text,
                "sender_type": new_message.sender_type,
                "sender_name": new_message.sender_name,
                "created_at": new_message.created_at.isoformat(),
                "is_read": False
            }
        })
        await redis_client.publish(channel, msg_data)

    # 4. Odoo senkronizasyonu kuyruğa atılmalı (Mocked for now)
    
    _logger.info(f"Mesaj kaydedildi: conv={conversation.uid}, msg_id={new_message.id}")

    return ChatSendResponse(
        success=True,
        message_id=new_message.id,
        sent_at=new_message.created_at
    )


async def get_messages(
    db: AsyncSession, 
    conversation_uid: str, 
    after_id: int = 0
) -> List[MessageSchema]:
    """Bir oturumdaki mesajları getirir."""
    # Oturumu bul
    result = await db.execute(select(Conversation).filter_by(uid=conversation_uid))
    conversation = result.scalars().first()

    if not conversation:
        return []

    # Mesajları getir
    query = select(Message).filter(Message.conversation_id == conversation.id)
    if after_id > 0:
        query = query.filter(Message.id > after_id)
        
    query = query.order_by(Message.id.asc())
    msg_result = await db.execute(query)
    messages = msg_result.scalars().all()

    return [MessageSchema.model_validate(m) for m in messages]


async def operator_reply(
    db: AsyncSession, 
    redis_client: Any, 
    data: OperatorReplyRequest
) -> Dict[str, Any]:
    """Operatörden (veya Odoo'dan) gelen bir yanıtı sisteme kaydeder."""
    # Güvenlik kontrolü
    from app.config import get_settings
    settings = get_settings()
    if data.secret_key != settings.SECRET_KEY:
        raise ValueError("Geçersiz anahtar")

    result = await db.execute(select(Conversation).filter_by(uid=data.conversation_uid))
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
    db.add(new_message)
    await db.commit()
    await db.refresh(new_message)

    # Redis'e bildir — tam mesaj JSON olarak
    channel = f"chat:{conversation.uid}"
    if redis_client:
        msg_data = json.dumps({
            "type": "operator_reply",
            "message": {
                "id": new_message.id,
                "text": new_message.text,
                "sender_type": "operator",
                "sender_name": new_message.sender_name,
                "created_at": new_message.created_at.isoformat(),
                "is_read": False
            }
        })
        await redis_client.publish(channel, msg_data)

    _logger.info(f"Operatör yanıtı kaydedildi: {conversation.uid}")

    return {"success": True, "message_id": new_message.id, "sent_at": new_message.created_at}
