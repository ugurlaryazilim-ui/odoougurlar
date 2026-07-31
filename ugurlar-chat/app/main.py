import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import engine, get_db
from app.models.base import Base
from app.api import health, chat, operator
from app.api import auth as auth_api
from app.api import stores as stores_api
from app.api import dashboard as dashboard_api
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

# Dizin yolları
APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"

# Jinja2 template engine
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama yaşam döngüsü yönetimi"""
    logger.info("🚀 Uğurlar Chat Service başlatılıyor...")

    # Tüm modelleri import et (tablo oluşturma için)
    from app.models import user, store, conversation, message  # noqa

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
    version="2.0.0",
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

# ─── API Router'ları ────────────────────────────────────
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(operator.router)
app.include_router(auth_api.router)
app.include_router(stores_api.router)
app.include_router(dashboard_api.router)


# ─── Auth helper ────────────────────────────────────────
def _get_token_from_cookie(request: Request) -> str | None:
    """Cookie'den JWT token al"""
    return request.cookies.get("access_token")


# ─── Sayfa Route'ları ───────────────────────────────────

# Landing page
@app.get("/", include_in_schema=False)
async def landing_page():
    """Ana sayfa — SaaS landing page"""
    from fastapi.responses import FileResponse
    return FileResponse(str(STATIC_DIR / "index.html"))


# Demo
@app.get("/demo", include_in_schema=False)
async def demo_page():
    """Canlı demo sayfası"""
    from fastapi.responses import FileResponse
    return FileResponse(str(STATIC_DIR / "demo.html"))


# Login
@app.get("/login", include_in_schema=False)
async def login_page(request: Request):
    """Giriş sayfası"""
    # Zaten giriş yapmışsa dashboard'a yönlendir
    if _get_token_from_cookie(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


# Register
@app.get("/register", include_in_schema=False)
async def register_page(request: Request):
    """Kayıt sayfası"""
    if _get_token_from_cookie(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("register.html", {"request": request})


# Dashboard
@app.get("/dashboard", include_in_schema=False)
async def dashboard_page(request: Request):
    """Ana panel"""
    if not _get_token_from_cookie(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("dashboard/index.html", {"request": request})


# Mağazalar
@app.get("/dashboard/stores", include_in_schema=False)
async def stores_page(request: Request):
    """Mağaza yönetimi"""
    if not _get_token_from_cookie(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("dashboard/stores.html", {"request": request})


# Sohbetler
@app.get("/dashboard/chats", include_in_schema=False)
async def chats_page(request: Request):
    """Konuşma listesi"""
    if not _get_token_from_cookie(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("dashboard/chats.html", {"request": request})


# Sohbet detay
@app.get("/dashboard/chats/{uid}", include_in_schema=False)
async def chat_detail_page(request: Request, uid: str):
    """Konuşma detayı"""
    if not _get_token_from_cookie(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("dashboard/chat_detail.html", {
        "request": request,
        "conversation_uid": uid
    })


# Ayarlar
@app.get("/dashboard/settings", include_in_schema=False)
async def settings_page(request: Request):
    """Ayarlar"""
    if not _get_token_from_cookie(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("dashboard/settings.html", {"request": request})


# ─── Statik Dosyalar ────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ─── WebSocket ──────────────────────────────────────────
@app.websocket("/ws/chat/{conversation_uid}")
async def websocket_endpoint(
    websocket: WebSocket,
    conversation_uid: str,
    db: AsyncSession = Depends(get_db)
):
    """Sohbet WebSocket uç noktası"""
    await chat_websocket_endpoint(websocket, conversation_uid, db)
