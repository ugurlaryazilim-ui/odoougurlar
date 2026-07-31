import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Integer, String, Enum, DateTime, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

class Conversation(Base):
    """Müşteri ile operatör/bot arasındaki sohbet oturumu."""
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Sohbetin dışarıya açılan benzersiz ID'si
    uid: Mapped[str] = mapped_column(String(36), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    store_domain: Mapped[str] = mapped_column(String(255), index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Sohbet durumu
    state: Mapped[str] = mapped_column(
        Enum('open', 'assigned', 'closed', name='conversation_state'), 
        default='open'
    )
    
    operator_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    page_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    page_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Odoo'daki kayıt ID'si (senkronizasyon için)
    odoo_conversation_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    
    # Store relationship
    store_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey('stores.id'), nullable=True)
    store = relationship('Store', back_populates='conversations')
