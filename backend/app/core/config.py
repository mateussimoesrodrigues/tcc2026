"""Configuracoes centrais da aplicacao, lidas de variaveis de ambiente (.env).

O banco de producao e PostgreSQL (Neon, serverless free tier). Se
DATABASE_URL ficar vazio, usamos um arquivo SQLite local (backend/dev.db)
so para permitir subir a API e testar os endpoints offline. Quando
DATABASE_URL estiver preenchido no .env, o app passa a usar o Postgres
real automaticamente -- nenhum outro codigo precisa mudar.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
_DEV_SQLITE_URL = f"sqlite:///{(BASE_DIR / 'dev.db').as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    app_name: str = "Precificacao Inteligente API"
    environment: str = "development"

    database_url: str = ""

    jwt_secret_key: str = "troque-esta-chave-antes-de-ir-para-producao"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    cors_origins: str = "http://localhost:5173"

    groq_api_key: str = ""
    gemini_api_key: str = ""

    @property
    def sqlalchemy_database_url(self) -> str:
        return self.database_url or _DEV_SQLITE_URL

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def using_sqlite_fallback(self) -> bool:
        return not self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
