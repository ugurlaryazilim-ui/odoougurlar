from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import get_settings
from app.database import get_db
from app.models.user import User

ALGORITHM = "HS256"

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    settings = get_settings()
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=1440) # 24 saat
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz kimlik doğrulama bilgileri",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        # Authorization header kontrolü
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kimlik doğrulama bulunamadı",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    try:
        payload = verify_token(token)
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Geçersiz token")
    except HTTPException:
        raise
        
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    
    if user is None:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı")
        
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Kullanıcı pasif durumda")
        
    return user
