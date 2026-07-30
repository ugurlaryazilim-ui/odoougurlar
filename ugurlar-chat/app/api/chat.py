import logging
import time
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.chat import ChatStartRequest, ChatStartResponse, ChatSendRequest, ChatSendResponse, ChatPollResponse, QuickReply
from app.services.chat_service import ChatService
from app.redis_client import get_redis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

async def check_rate_limit(request: Request, limit: int, window: int):
    """IP tabanlı rate limit kontrolü"""
    client_ip = request.client.host if request.client else "127.0.0.1"
    path = request.url.path
    key = f"rate_limit:{path}:{client_ip}"
    redis = await get_redis()
    
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window)
    
    if current > limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Çok fazla istek")

@router.post("/start", response_model=ChatStartResponse)
async def start_chat(request: Request, chat_request: ChatStartRequest, db: AsyncSession = Depends(get_db)):
    """Yeni bir sohbet başlatır veya mevcut olanı getirir"""
    await check_rate_limit(request, limit=10, window=60)
    service = ChatService(db)
    return await service.start_conversation(chat_request)

@router.post("/send", response_model=ChatSendResponse)
async def send_message(request: Request, send_req: ChatSendRequest, db: AsyncSession = Depends(get_db)):
    """Sohbete yeni bir mesaj gönderir"""
    await check_rate_limit(request, limit=30, window=60)
    service = ChatService(db)
    return await service.send_message(send_req)

@router.post("/poll", response_model=ChatPollResponse)
async def poll_messages(request: Request, db: AsyncSession = Depends(get_db)):
    """WebSocket desteklemeyen istemciler için mesajları çeker"""
    # İleride son_mesaj_id vb. kullanılarak eklenebilir. Şu an için stub.
    return ChatPollResponse(messages=[])

@router.get("/quick-replies", response_model=list[QuickReply])
async def get_quick_replies(store_id: str, db: AsyncSession = Depends(get_db)):
    """Hızlı yanıtları (quick replies) getirir"""
    service = ChatService(db)
    return await service.get_quick_replies(store_id)
