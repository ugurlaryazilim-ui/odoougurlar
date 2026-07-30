from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class QuickReply(BaseModel):
    id: str
    label: str
    message: str

class MessageSchema(BaseModel):
    id: int
    text: str
    sender_type: str
    sender_name: Optional[str] = None
    created_at: datetime
    is_read: bool

    class Config:
        from_attributes = True

class ChatStartRequest(BaseModel):
    shop_domain: str = Field(..., description="Shopify mağaza domaini (örn: monalure.com)")
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    page_url: Optional[str] = None
    page_title: Optional[str] = None

class ChatStartResponse(BaseModel):
    success: bool
    conversation_uid: str
    welcome_message: str
    quick_replies: List[QuickReply] = []

class ChatSendRequest(BaseModel):
    conversation_uid: str
    message: str
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None

class ChatSendResponse(BaseModel):
    success: bool
    message_id: int
    sent_at: datetime

class ChatPollResponse(BaseModel):
    success: bool
    messages: List[MessageSchema]

class OperatorReplyRequest(BaseModel):
    conversation_uid: str
    message: str
    operator_name: str
    secret_key: str = Field(..., description="Güvenlik için basit bir anahtar")
