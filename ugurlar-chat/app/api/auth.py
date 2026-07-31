import logging
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta

from app.database import get_db
from app.models.user import User
from app.schemas.auth import UserRegister, UserLogin, UserResponse, TokenResponse
from app.auth.password import hash_password, verify_password
from app.auth.jwt import create_access_token, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/auth', tags=['auth'])

@router.post('/register', response_model=TokenResponse)
async def register(user_data: UserRegister, response: Response, db: AsyncSession = Depends(get_db)):
    # Check if email exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        logger.warning(f"Kayıt hatası: Email zaten kullanımda ({user_data.email})")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bu email adresi zaten kullanımda."
        )
        
    # Hash password and create user
    hashed_pw = hash_password(user_data.password)
    new_user = User(
        email=user_data.email,
        password_hash=hashed_pw,
        name=user_data.name,
        role='admin' # İlk kayıt olan admin olabilir
    )
    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    
    logger.info(f"Yeni kullanıcı kaydedildi: {new_user.email}")
    
    # Create token
    access_token = create_access_token(data={"sub": new_user.email})
    
    # Set cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=86400, # 24 saat
        samesite="lax",
        secure=False # HTTPS gereksinimi için production'da True olmalı
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@router.post('/login', response_model=TokenResponse)
async def login(user_data: UserLogin, response: Response, db: AsyncSession = Depends(get_db)):
    # Find user
    result = await db.execute(select(User).where(User.email == user_data.email))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(user_data.password, user.password_hash):
        logger.warning(f"Giriş hatası: Hatalı email veya şifre ({user_data.email})")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Hatalı email veya şifre.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    if not user.is_active:
        logger.warning(f"Giriş hatası: Pasif kullanıcı ({user_data.email})")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kullanıcı hesabı aktif değil."
        )
        
    logger.info(f"Kullanıcı girişi başarılı: {user.email}")
    
    # Create token
    access_token = create_access_token(data={"sub": user.email})
    
    # Set cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=86400,
        samesite="lax",
        secure=False
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@router.get('/me', response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user

@router.post('/logout')
async def logout(response: Response):
    response.delete_cookie(key="access_token")
    return {"message": "Başarıyla çıkış yapıldı."}
