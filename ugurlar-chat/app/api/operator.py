import logging
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.operator import OperatorReplyRequest, OperatorTypingRequest, OperatorCloseRequest
from app.services.chat_service import ChatService
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/operator", tags=["operator"])

async def verify_secret(x_operator_secret: str = Header(...)):
    """Odoo'dan gelen isteklerin yetkilendirmesini kontrol eder"""
    settings = get_settings()
    if x_operator_secret != settings.SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz secret key")
    return x_operator_secret

@router.post("/reply")
async def operator_reply(req: OperatorReplyRequest, db: AsyncSession = Depends(get_db), secret: str = Depends(verify_secret)):
    """Operatör tarafından gönderilen mesajı işler ve müşteriye iletir"""
    service = ChatService(db)
    await service.operator_reply(req)
    return {"status": "ok"}

@router.post("/typing")
async def operator_typing(req: OperatorTypingRequest, secret: str = Depends(verify_secret)):
    """Operatörün yazıyor bilgisini iletir"""
    # Typing için db gerekmiyorsa None geçilebilir
    service = ChatService(None)
    await service.operator_typing(req)
    return {"status": "ok"}

@router.post("/close")
async def operator_close(req: OperatorCloseRequest, db: AsyncSession = Depends(get_db), secret: str = Depends(verify_secret)):
    """Operatör sohbeti kapattığında çalışır"""
    service = ChatService(db)
    await service.operator_close(req)
    return {"status": "ok"}
