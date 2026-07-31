from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
import secrets

from app.database import get_db
from app.auth.jwt import get_current_user
from app.models.user import User
from app.models.store import Store
from app.models.conversation import Conversation
from app.schemas.store import (
    StoreCreateRequest, 
    StoreUpdateRequest, 
    StoreResponse, 
    EmbedCodeResponse
)

router = APIRouter(prefix='/api/stores', tags=['stores'])

@router.get('/', response_model=list[StoreResponse])
async def list_stores(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Kullanıcının mağazalarını ve konuşma sayılarını getirir."""
    # Mağazaları çek
    query = select(Store).where(Store.user_id == user.id)
    result = await db.execute(query)
    stores = result.scalars().all()
    
    # Konuşma sayılarını hesapla
    store_responses = []
    for store in stores:
        count_query = select(func.count(Conversation.id)).where(Conversation.store_id == store.id)
        count_result = await db.execute(count_query)
        conv_count = count_result.scalar() or 0
        
        # Pydantic modeline dönüştürürken conversation_count ekle
        store_data = store.__dict__.copy()
        store_data['conversation_count'] = conv_count
        store_responses.append(StoreResponse.model_validate(store_data))
        
    return store_responses

@router.post('/', response_model=StoreResponse, status_code=status.HTTP_201_CREATED)
async def create_store(
    data: StoreCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Yeni mağaza oluşturur ve api_key üretir."""
    # Domain kontrolü
    existing = await db.execute(select(Store).where(Store.domain == data.domain))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bu domain zaten kayıtlı."
        )
        
    api_key = secrets.token_urlsafe(32)
    
    new_store = Store(
        domain=data.domain,
        name=data.name,
        platform=data.platform,
        api_key=api_key,
        user_id=user.id
    )
    db.add(new_store)
    await db.commit()
    await db.refresh(new_store)
    
    store_data = new_store.__dict__.copy()
    store_data['conversation_count'] = 0
    return StoreResponse.model_validate(store_data)

@router.get('/{store_id}', response_model=StoreResponse)
async def get_store(
    store_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Belirli bir mağazanın detaylarını getirir."""
    result = await db.execute(
        select(Store).where(Store.id == store_id, Store.user_id == user.id)
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mağaza bulunamadı veya erişim yetkiniz yok."
        )
        
    count_query = select(func.count(Conversation.id)).where(Conversation.store_id == store.id)
    count_result = await db.execute(count_query)
    conv_count = count_result.scalar() or 0
    
    store_data = store.__dict__.copy()
    store_data['conversation_count'] = conv_count
    return StoreResponse.model_validate(store_data)

@router.put('/{store_id}', response_model=StoreResponse)
async def update_store(
    store_id: int,
    data: StoreUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mağaza ayarlarını günceller (isim, renk, karşılama mesajı vb.)."""
    result = await db.execute(
        select(Store).where(Store.id == store_id, Store.user_id == user.id)
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mağaza bulunamadı."
        )
        
    if data.name is not None:
        store.name = data.name
    if data.widget_color is not None:
        store.widget_color = data.widget_color
    if data.welcome_message is not None:
        store.welcome_message = data.welcome_message
        
    await db.commit()
    await db.refresh(store)
    
    count_query = select(func.count(Conversation.id)).where(Conversation.store_id == store.id)
    count_result = await db.execute(count_query)
    conv_count = count_result.scalar() or 0
    
    store_data = store.__dict__.copy()
    store_data['conversation_count'] = conv_count
    return StoreResponse.model_validate(store_data)

@router.delete('/{store_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_store(
    store_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mağazayı siler."""
    result = await db.execute(
        select(Store).where(Store.id == store_id, Store.user_id == user.id)
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mağaza bulunamadı."
        )
        
    await db.delete(store)
    await db.commit()

@router.get('/{store_id}/embed', response_model=EmbedCodeResponse)
async def get_embed_code(
    store_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mağazaya ait widget gömme kodunu (embed code) getirir."""
    result = await db.execute(
        select(Store).where(Store.id == store_id, Store.user_id == user.id)
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mağaza bulunamadı."
        )
        
    # Basit bir embed kod taslağı
    script_url = "https://chat.ugurlar.com/widget.js"
    embed_code = f"""
<!-- Uğurlar Chat Widget -->
<script>
  window.ugurlarChatConfig = {{
    apiKey: "{store.api_key}"
  }};
</script>
<script async src="{script_url}"></script>
<!-- /Uğurlar Chat Widget -->
"""
    return EmbedCodeResponse(embed_code=embed_code.strip(), api_key=store.api_key)
