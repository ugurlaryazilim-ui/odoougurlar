import redis.asyncio as redis
from typing import AsyncGenerator
from app.config import get_settings

settings = get_settings()

# Redis bağlantı havuzu oluşturulması
redis_pool = redis.ConnectionPool.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=50
)

async def get_redis() -> AsyncGenerator[redis.Redis, None]:
    """FastAPI bağımlılığı olarak Redis istemcisini döndürür."""
    client = redis.Redis(connection_pool=redis_pool)
    try:
        yield client
    finally:
        await client.close()

# Uygulama genelinde Pub/Sub işlemleri vb. için paylaşılan Redis istemcisi
redis_client = redis.Redis(connection_pool=redis_pool)

async def publish_message(channel: str, message: str) -> None:
    """Belirtilen kanala Redis üzerinden mesaj yayınlar."""
    await redis_client.publish(channel, message)
