import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Query, status
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

    try:
        redis = await get_redis()
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, window)
        if current > limit:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Çok fazla istek")
    except HTTPException:
        raise
    except Exception as e:
        # Redis hatası rate limiting'i bozmasın
        logger.warning(f"Rate limit kontrolü başarısız: {e}")


@router.post("/start", response_model=ChatStartResponse)
async def start_chat(request: Request, chat_request: ChatStartRequest, db: AsyncSession = Depends(get_db)):
    """Yeni bir sohbet başlatır"""
    await check_rate_limit(request, limit=10, window=60)
    service = ChatService(db)
    return await service.start_conversation(chat_request)


@router.post("/send", response_model=ChatSendResponse)
async def send_message(request: Request, send_req: ChatSendRequest, db: AsyncSession = Depends(get_db)):
    """Sohbete yeni bir mesaj gönderir"""
    await check_rate_limit(request, limit=30, window=60)
    service = ChatService(db)
    try:
        return await service.send_message(send_req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/poll", response_model=ChatPollResponse)
async def poll_messages(
    request: Request,
    conversation_uid: str = Query(...),
    after_id: int = Query(0),
    db: AsyncSession = Depends(get_db)
):
    """WebSocket desteklemeyen istemciler için mesajları çeker"""
    service = ChatService(db)
    messages = await service.get_messages(conversation_uid, after_id)
    return ChatPollResponse(success=True, messages=messages)


@router.get("/quick-replies", response_model=list[QuickReply])
async def get_quick_replies():
    """Hızlı yanıtları getirir"""
    service = ChatService()
    return await service.get_quick_replies()
