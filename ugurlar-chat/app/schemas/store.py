from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime

class StoreCreateRequest(BaseModel):
    """Mağaza oluşturma isteği şeması"""
    domain: str
    name: str
    platform: str = 'shopify'

class StoreUpdateRequest(BaseModel):
    """Mağaza güncelleme isteği şeması"""
    name: Optional[str] = None
    widget_color: Optional[str] = None
    welcome_message: Optional[str] = None

class StoreResponse(BaseModel):
    """Mağaza yanıt şeması"""
    id: int
    domain: str
    name: str
    platform: str
    api_key: str
    widget_color: Optional[str] = None
    welcome_message: Optional[str] = None
    is_active: bool
    created_at: datetime
    conversation_count: Optional[int] = 0

    model_config = ConfigDict(from_attributes=True)

class EmbedCodeResponse(BaseModel):
    """Embed kod yanıt şeması"""
    embed_code: str
    api_key: str
