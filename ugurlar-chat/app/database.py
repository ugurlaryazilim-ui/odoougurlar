from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from typing import AsyncGenerator
from app.config import get_settings

settings = get_settings()

# Async veritabanı motoru oluşturulması
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    pool_size=20,
    max_overflow=10
)

# Async session üretici (sessionmaker)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Temel model sınıfı
Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI bağımlılığı (dependency) olarak kullanılacak veritabanı oturumu."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
