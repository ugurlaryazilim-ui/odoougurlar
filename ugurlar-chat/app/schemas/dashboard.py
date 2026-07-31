from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Any
from datetime import datetime

class DashboardStats(BaseModel):
    """Dashboard istatistikleri şeması"""
    total_conversations: int
    open_count: int
    assigned_count: int
    closed_count: int
    total_messages: int
    total_stores: int
    today_conversations: int

class ConversationListItem(BaseModel):
    """Dashboard konuşma listesi elemanı şeması"""
    uid: str
    store_domain: str
    customer_name: Optional[str] = None
    state: str
    last_message_preview: Optional[str] = None
    message_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class ConversationDetail(BaseModel):
    """Dashboard konuşma detayı şeması"""
    uid: str
    store_domain: str
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    state: str
    operator_name: Optional[str] = None
    page_url: Optional[str] = None
    messages: List[Any] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
