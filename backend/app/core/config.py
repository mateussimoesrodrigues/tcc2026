"""Configuracoes centrais da aplicacao, lidas de variaveis de ambiente (.env).

O banco de producao e PostgreSQL (Neon, serverless free tier). Se
DATABASE_URL ficar vazio, usamos um arquivo SQLite local (backend/dev.db)
so para permitir subir a API e testar os endpoints offline. Quando
DATABASE_URL estiver preenchido no .env, o app passa a usar o Postgres
real automaticamente -- nenhum outro codigo precisa mudar.
"""
from functools import lru_cache
from pathlib import Path

import truststore
from pydantic_settings import BaseSettings, SettingsConfigDict

# Usa o certificate store do SO (Windows/macOS) em vez do bundle estatico
# do certifi. Necessario em maquinas com antivirus/proxy corporativo que
# faz inspecao SSL e instala uma CA root propria so no store do sistema --
# sem isso, chamadas HTTPS de saida (ex.: ai/llm_provider.py chamando
# Groq/Gemini) falham com "CERTIFICATE_VERIFY_FAILED: unable to get local
# issuer certificate" mesmo o navegador confiando no site normalmente.
# Precisa rodar antes de qualquer uso de ssl/httpx no processo -- por isso
# fica aqui, no modulo de config importado por todo entrypoint (app,
# testes, seed, alembic).
truststore.inject_into_ssl()

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

    # Job diario do motor de promocoes (gerar sugestoes + expirar
    # promocoes vencidas). Desligado por padrao -- o TestClient do pytest
    # dispara os eventos de startup do FastAPI a cada teste, e um
    # scheduler ligado bateria na API do LLM de verdade nesse processo.
    # So habilita explicitamente no ambiente onde a app fica de pe 24/7
    # (producao).
    enable_scheduler: bool = False

    @property
    def sqlalchemy_database_url(self) -> str:
        return self.database_url or _DEV_SQLITE_URL

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def using_sqlite_fallback(self) -> bool:
        return not self.database_url


_JWT_SECRET_PADRAO = Settings.model_fields["jwt_secret_key"].default


class ConfiguracaoProducaoInvalidaError(RuntimeError):
    """Ambiente marcado como producao (ENVIRONMENT=production) mas com uma
    configuracao insegura -- melhor falhar rapido no startup do que subir
    e descobrir depois (ex.: JWT_SECRET_KEY no valor padrao, que e publico
    no repositorio, deixaria qualquer um forjar login de funcionario)."""


def validar_configuracao_producao(settings: Settings) -> None:
    if settings.environment != "production":
        return
    if settings.jwt_secret_key == _JWT_SECRET_PADRAO:
        raise ConfiguracaoProducaoInvalidaError(
            "JWT_SECRET_KEY continua no valor padrao em ENVIRONMENT=production. "
            "Gere uma chave real (python -c \"import secrets; print(secrets.token_hex(32))\") "
            "e configure a variavel de ambiente antes de subir."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
