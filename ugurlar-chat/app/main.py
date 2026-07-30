import logging
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import engine, Base, get_db
from app.api import health, chat, operator
from app.websocket.manager import manager
from app.websocket.handlers import chat_websocket_endpoint

# Ayarları yükle
settings = get_settings()

# Loglama yapılandırması
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

# Static dizin yolu (app/static/)
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama yaşam döngüsü yönetimi"""
    logger.info("🚀 Uğurlar Chat Service başlatılıyor...")
    
    # Veritabanı tablolarını oluştur
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Veritabanı tabloları hazır")

    # Static dizini oluştur
    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    # Redis dinleyicisini başlat
    logger.info("📡 Redis Pub/Sub dinleyicisi başlatılıyor...")
    manager.redis_task = asyncio.create_task(manager.redis_listener())

    logger.info("✅ Uğurlar Chat Service hazır!")
    yield

    # Kapanışta işlemleri durdur
    logger.info("🛑 Uğurlar Chat Service kapatılıyor...")
    if manager.redis_task:
        manager.redis_task.cancel()
        try:
            await manager.redis_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Uğurlar Chat Service",
    description="Shopify mağazalar için gerçek zamanlı canlı destek chat servisi",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Router'ları ekle
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(operator.router)

# Statik dosyalar (widget.js, widget.css)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# WebSocket uç noktası
@app.websocket("/ws/chat/{conversation_uid}")
async def websocket_endpoint(
    websocket: WebSocket,
    conversation_uid: str,
    db: AsyncSession = Depends(get_db)
):
    """Sohbet WebSocket uç noktası"""
    await chat_websocket_endpoint(websocket, conversation_uid, db)

