import time
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_db
from app.redis_client import get_redis

router = APIRouter()
START_TIME = time.time()

@router.get("/health")
async def health_check():
    """Temel sağlık kontrolü uç noktası"""
    return {"status": "ok", "version": "1.0.0", "uptime": int(time.time() - START_TIME)}

@router.get("/health/detailed")
async def detailed_health_check(db: AsyncSession = Depends(get_db)):
    """Detaylı sağlık kontrolü (DB ve Redis)"""
    redis = await get_redis()
    
    # Check DB
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"
        
    # Check Redis
    redis_status = "ok"
    try:
        await redis.ping()
    except Exception as e:
        redis_status = f"error: {str(e)}"
        
    return {
        "status": "ok" if db_status == "ok" and redis_status == "ok" else "degraded",
        "version": "1.0.0",
        "uptime": int(time.time() - START_TIME),
        "database": db_status,
        "redis": redis_status
    }
