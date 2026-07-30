from functools import lru_cache
from typing import List, Union
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Veritabanı ve Redis yapılandırmaları
    DATABASE_URL: str
    REDIS_URL: str

    # Odoo Entegrasyonu yapılandırmaları
    ODOO_URL: str
    ODOO_DB: str
    ODOO_USER: str
    ODOO_PASSWORD: str

    # Güvenlik ve CORS
    SECRET_KEY: str
    CORS_ORIGINS: str | list[str] = []
    DEBUG: bool = False

    # Odoo senkronizasyon (kapalıyken bile chat çalışır)
    ODOO_SYNC_ENABLED: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS origin'leri liste olarak döndürür."""
        if isinstance(self.CORS_ORIGINS, str):
            return [x.strip() for x in self.CORS_ORIGINS.split(",") if x.strip()]
        return self.CORS_ORIGINS

@lru_cache()
def get_settings() -> Settings:
    """Uygulama ayarlarını önbelleğe alarak döndürür. (Singleton)"""
    return Settings()
