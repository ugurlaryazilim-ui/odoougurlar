import asyncio
import json
import logging
from typing import Dict, Set
from fastapi import WebSocket
from app.redis_client import get_redis
import websockets.exceptions

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # {conversation_uid: set[WebSocket]}
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.redis_task = None
        self.pubsub = None

    async def connect(self, websocket: WebSocket, conversation_uid: str):
        """WebSocket bağlantısını kabul eder ve Redis kanalına abone olur"""
        await websocket.accept()
        if conversation_uid not in self.active_connections:
            self.active_connections[conversation_uid] = set()
            # Redis'e abone ol
            redis = await get_redis()
            if not self.pubsub:
                self.pubsub = redis.pubsub()
            await self.pubsub.subscribe(f"chat:{conversation_uid}")
        
        self.active_connections[conversation_uid].add(websocket)
        logger.info(f"WebSocket bağlandı: {conversation_uid}")

    async def disconnect(self, websocket: WebSocket, conversation_uid: str):
        """Bağlantıyı keser ve gerektiğinde Redis kanalından çıkar"""
        if conversation_uid in self.active_connections:
            self.active_connections[conversation_uid].discard(websocket)
            if not self.active_connections[conversation_uid]:
                del self.active_connections[conversation_uid]
                # Abonelikten çık
                if self.pubsub:
                    try:
                        await self.pubsub.unsubscribe(f"chat:{conversation_uid}")
                    except Exception:
                        pass
        logger.info(f"WebSocket bağlantısı kesildi: {conversation_uid}")

    async def send_to_conversation(self, conversation_uid: str, data: dict):
        """Belirli bir sohbetteki tüm bağlı istemcilere mesaj gönderir"""
        if conversation_uid in self.active_connections:
            dead_connections = set()
            for connection in self.active_connections[conversation_uid]:
                try:
                    await connection.send_json(data)
                except Exception as e:
                    logger.warning(f"Mesaj gönderme hatası {conversation_uid}: {e}")
                    dead_connections.add(connection)
            
            for dead in dead_connections:
                await self.disconnect(dead, conversation_uid)

    async def broadcast(self, data: dict):
        """Yönetici yayınları (tüm aktif sohbetlere)"""
        for uid in list(self.active_connections.keys()):
            await self.send_to_conversation(uid, data)

    async def redis_listener(self):
        """Arka planda çalışarak Redis pub/sub mesajlarını dinler"""
        try:
            redis = await get_redis()
            self.pubsub = redis.pubsub()
            # Mevcut kanallara abone ol
            channels = [f"chat:{uid}" for uid in self.active_connections.keys()]
            if channels:
                await self.pubsub.subscribe(*channels)
            
            logger.info("Redis dinleyicisi başlatıldı")
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    channel = message["channel"].decode("utf-8")
                    conversation_uid = channel.split(":")[1]
                    data = json.loads(message["data"])
                    await self.send_to_conversation(conversation_uid, data)
        except asyncio.CancelledError:
            logger.info("Redis dinleyicisi durduruldu (Cancelled)")
        except Exception as e:
            logger.error(f"Redis dinleyicisi hatası: {e}")
            await asyncio.sleep(5)
            # İsteğe bağlı olarak yeniden başlatma eklenebilir

manager = ConnectionManager()
