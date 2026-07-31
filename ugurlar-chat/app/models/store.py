from sqlalchemy import Integer, String, Boolean, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
import secrets
from typing import Optional

def generate_api_key():
    return 'uk_' + secrets.token_hex(24)

class Store(Base):
    __tablename__ = 'stores'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    platform: Mapped[str] = mapped_column(String(50), default='shopify')
    api_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=generate_api_key)
    widget_color: Mapped[str] = mapped_column(String(7), default='#6366f1')
    welcome_message: Mapped[str] = mapped_column(Text, default='Merhaba! 👋 Size nasıl yardımcı olabiliriz?')
    quick_replies_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship('User')
    conversations = relationship('Conversation', back_populates='store')
