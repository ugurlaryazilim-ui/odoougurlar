from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_, and_
from datetime import datetime, date, timezone
from pydantic import BaseModel
from typing import List

from app.database import get_db
from app.auth.jwt import get_current_user
from app.models.user import User
from app.models.store import Store
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.dashboard import (
    DashboardStats,
    ConversationListItem,
    ConversationDetail
)

router = APIRouter(prefix='/api/dashboard', tags=['dashboard'])

class ReplyRequest(BaseModel):
    message: str

@router.get('/stats', response_model=DashboardStats)
async def get_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Dashboard için genel istatistikleri getirir."""
    
    # Kullanıcının mağaza ID'lerini al
    store_result = await db.execute(select(Store.id).where(Store.user_id == user.id))
    store_ids = [row[0] for row in store_result.all()]
    
    if not store_ids:
        return DashboardStats(
            total_conversations=0,
            open_count=0,
            assigned_count=0,
            closed_count=0,
            total_messages=0,
            total_stores=0,
            today_conversations=0
        )
        
    # İstatistikler için temel sorgu condition'ı
    conv_condition = Conversation.store_id.in_(store_ids)
    
    # Tüm konuşma sayıları
    conv_counts = await db.execute(
        select(
            func.count(Conversation.id).label('total'),
            func.sum(func.cast(Conversation.state == 'open', func.integer)).label('open'),
            func.sum(func.cast(Conversation.state == 'assigned', func.integer)).label('assigned'),
            func.sum(func.cast(Conversation.state == 'closed', func.integer)).label('closed')
        ).where(conv_condition)
    )
    counts = conv_counts.one()
    
    # Toplam mesaj sayısı
    msg_count_result = await db.execute(
        select(func.count(Message.id))
        .join(Conversation)
        .where(conv_condition)
    )
    total_messages = msg_count_result.scalar() or 0
    
    # Bugünün konuşmaları (UTC'ye göre veya sunucu saatine göre)
    today = datetime.now(timezone.utc).date()
    today_conv_result = await db.execute(
        select(func.count(Conversation.id))
        .where(and_(conv_condition, func.date(Conversation.created_at) == today))
    )
    today_conversations = today_conv_result.scalar() or 0
    
    return DashboardStats(
        total_conversations=counts.total or 0,
        open_count=counts.open or 0,
        assigned_count=counts.assigned or 0,
        closed_count=counts.closed or 0,
        total_messages=total_messages,
        total_stores=len(store_ids),
        today_conversations=today_conversations
    )

@router.get('/conversations', response_model=List[ConversationListItem])
async def list_conversations(
    state: str = Query(None, description="Durum filtresi (open, assigned, closed)"),
    store_id: int = Query(None, description="Mağaza ID filtresi"),
    search: str = Query(None, description="Müşteri adı arama filtresi"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Konuşma listesini sayfalı ve filtrelenmiş olarak getirir."""
    
    # Kullanıcının mağazalarını bul
    stores_query = select(Store).where(Store.user_id == user.id)
    stores_result = await db.execute(stores_query)
    user_stores = {store.id: store for store in stores_result.scalars().all()}
    
    if not user_stores:
        return []
        
    store_ids = list(user_stores.keys())
    
    # Eğer özel bir store_id istenmişse ve kullanıcının yetkisi varsa
    if store_id:
        if store_id not in store_ids:
            return []
        filter_store_ids = [store_id]
    else:
        filter_store_ids = store_ids
        
    # Temel sorguyu oluştur
    query = select(Conversation).where(Conversation.store_id.in_(filter_store_ids))
    
    # Durum filtresi
    if state:
        query = query.where(Conversation.state == state)
        
    # Arama filtresi (müşteri adına göre)
    if search:
        query = query.where(Conversation.customer_name.ilike(f"%{search}%"))
        
    # Sıralama ve sayfalama
    offset = (page - 1) * limit
    query = query.order_by(desc(Conversation.created_at)).offset(offset).limit(limit)
    
    result = await db.execute(query)
    conversations = result.scalars().all()
    
    items = []
    for conv in conversations:
        # Son mesajı çekmek ve mesaj sayısını bulmak için ekstra sorgu
        msg_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(desc(Message.created_at))
            .limit(1)
        )
        last_msg = msg_result.scalar_one_or_none()
        
        count_result = await db.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conv.id)
        )
        msg_count = count_result.scalar() or 0
        
        store_domain = user_stores[conv.store_id].domain
        
        items.append(ConversationListItem(
            uid=conv.uid,
            store_domain=store_domain,
            customer_name=conv.customer_name,
            state=conv.state,
            last_message_preview=last_msg.content[:50] + "..." if last_msg and last_msg.content else None,
            message_count=msg_count,
            created_at=conv.created_at,
            updated_at=last_msg.created_at if last_msg else conv.updated_at
        ))
        
    return items

@router.get('/conversations/{uid}', response_model=ConversationDetail)
async def get_conversation(
    uid: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Belirli bir konuşmanın detaylarını ve mesajlarını getirir."""
    
    # Kullanıcının mağaza ID'lerini al
    store_result = await db.execute(select(Store).where(Store.user_id == user.id))
    user_stores = {store.id: store for store in store_result.scalars().all()}
    
    # Konuşmayı bul
    result = await db.execute(select(Conversation).where(Conversation.uid == uid))
    conv = result.scalar_one_or_none()
    
    if not conv or conv.store_id not in user_stores:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Konuşma bulunamadı veya erişim yetkiniz yok."
        )
        
    # Mesajları getir
    msg_result = await db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )
    messages = msg_result.scalars().all()
    
    store_domain = user_stores[conv.store_id].domain
    
    return ConversationDetail(
        uid=conv.uid,
        store_domain=store_domain,
        customer_name=conv.customer_name,
        customer_email=conv.customer_email,
        state=conv.state,
        operator_name=conv.operator_name,
        page_url=conv.page_url,
        messages=messages,
        created_at=conv.created_at
    )

@router.post('/conversations/{uid}/reply', status_code=status.HTTP_200_OK)
async def reply_to_conversation(
    uid: str,
    data: ReplyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Dashboard üzerinden konuşmaya yanıt verir."""
    
    # Kullanıcının yetkisi olduğunu doğrulamak için konuşmayı bul
    store_result = await db.execute(select(Store.id).where(Store.user_id == user.id))
    store_ids = [row[0] for row in store_result.all()]
    
    result = await db.execute(select(Conversation).where(Conversation.uid == uid))
    conv = result.scalar_one_or_none()
    
    if not conv or conv.store_id not in store_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Konuşma bulunamadı veya erişim yetkiniz yok."
        )
        
    # Konuşma mesajını doğrudan oluştur ve Redis'e yayınla
    from app.models.message import Message as MessageModel
    from app.redis_client import get_redis
    import json

    new_message = MessageModel(
        conversation_id=conv.id,
        text=data.message,
        sender_type="operator",
        sender_name=user.name or "Operatör"
    )
    db.add(new_message)

    if conv.state == "open":
        conv.state = "assigned"
        conv.operator_name = user.name

    await db.commit()
    await db.refresh(new_message)

    # Redis'e yayınla
    try:
        redis = await get_redis()
        channel = f"chat:{conv.uid}"
        msg_data = json.dumps({
            "type": "operator_reply",
            "message": {
                "id": new_message.id,
                "text": new_message.text,
                "sender_type": "operator",
                "sender_name": new_message.sender_name,
                "created_at": new_message.created_at.isoformat() if new_message.created_at else None,
            }
        })
        await redis.publish(channel, msg_data)
    except Exception:
        pass

    return {"status": "success", "message": "Yanıt gönderildi."}
