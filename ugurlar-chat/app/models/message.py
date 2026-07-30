from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, Enum, DateTime, ForeignKey, Text, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

class Message(Base):
    """Sohbet içindeki tekil mesajlar."""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Mesajı gönderen tipi
    sender_type: Mapped[str] = mapped_column(
        Enum('customer', 'operator', 'bot', 'system', name='sender_type'), 
        default='customer'
    )
    
    sender_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Odoo'daki mesaj kayıt ID'si (senkronizasyon için)
    odoo_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # İlişki
    conversation = relationship("Conversation", back_populates="messages")
