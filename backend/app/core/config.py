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

    # --- Guard-rails de preco (ver services/price_service.py) -------------
    # Nenhuma promocao pode deixar o preco abaixo de
    # custo * (1 + margem_minima_percentual/100). E o piso que impede a IA
    # (ou o funcionario aprovando na correria) de vender no prejuizo.
    margem_minima_percentual: float = 10.0
    # Teto de desconto, aplicado tanto na validacao da resposta do LLM
    # quanto na aplicacao do preco.
    desconto_maximo_percentual: float = 70.0
    # Margem comercial desejada no catalogo, medida SOBRE O PRECO -- mesma
    # base de `ai/rules.SinaisProduto.margem`, que e o numero que as telas
    # exibem. Alimenta o alerta de margem defasada e o preco sugerido.
    #
    # Atencao a diferenca de base, que e a pegadinha deste dominio:
    # `margem_minima_percentual` acima e um markup SOBRE O CUSTO
    # (custo * 1,10) e funciona como piso intransponivel; esta e uma meta
    # comercial sobre o preco (preco = custo / (1 - alvo)). Bases
    # diferentes, papeis diferentes.
    margem_alvo_percentual: float = 35.0
    # Produto sem `custo` cadastrado nao tem piso calculavel. True = deixa a
    # promocao passar mesmo assim (realidade da loja: nem todo custo esta
    # lancado). False = recusa, postura mais conservadora.
    permitir_promocao_sem_custo: bool = True
    # Divergencia maxima tolerada, em pontos percentuais do preco normal,
    # entre o `preco_sugerido` e o preco derivado do
    # `percentual_desconto_sugerido` -- pega LLM que devolve o par
    # incoerente (ex.: "30% off" com preco de 10% off).
    tolerancia_coerencia_pp: float = 2.0
    # Informa o desconto maximo permitido dentro do proprio prompt. Fica
    # como flag pra virar braco de A/B no harness de avaliacao
    # (scripts/avaliar_llm.py): informar o limite reduz resposta invalida?
    informar_piso_no_prompt: bool = True

    # Marca os dados de venda/promocao como simulados (gerados por
    # `app/seed.py`, nao pela operacao real da loja). Alimenta o banner de
    # aviso na tela de indicadores -- honestidade metodologica pro TCC.
    dados_simulados: bool = True

    # Job diario do motor de promocoes (gerar sugestoes + expirar
    # promocoes vencidas). Desligado por padrao -- o TestClient do pytest
    # dispara os eventos de startup do FastAPI a cada teste, e um
    # scheduler ligado bateria na API do LLM de verdade nesse processo.
    # So habilita explicitamente no ambiente onde a app fica de pe 24/7
    # (producao).
    enable_scheduler: bool = False

    # Intervalo (em segundos) que os displays fisicos de prateleira devem
    # esperar entre uma sincronizacao e outra (ver routers/displays.py e
    # docs/displays-fisicos.md). Devolvido a cada resposta de sync, em vez
    # de fixo no firmware, pra dar pra apertar (demo) ou alongar (producao,
    # poupar bateria) sem reflashear os dispositivos.
    display_sync_intervalo_segundos: int = 300

    # --- Push MQTT pros displays (variante de demonstracao) --------------
    # Existem duas variantes de firmware (ver docs/displays-fisicos.md):
    # e-paper + polling + deep sleep (producao, autonomia de bateria) e
    # OLED + MQTT push + alimentacao fixa (demonstracao, atualizacao
    # instantanea). O push abaixo alimenta a segunda.
    #
    # Desligado por padrao de proposito: dev e CI nao tem broker, e o
    # sistema inteiro funciona sem ele -- a mudanca de preco no banco e a
    # fonte da verdade, o push e best-effort por cima disso.
    mqtt_enabled: bool = False
    mqtt_host: str = ""
    # 8883 = MQTT sobre TLS (padrao dos brokers gerenciados, ex.: HiveMQ
    # Cloud). 1883 = sem TLS, so pra broker local (ex.: mosquitto na LAN).
    mqtt_port: int = 8883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_use_tls: bool = True
    # Topico publicado: {prefixo}/{display_id}/preco
    mqtt_topic_prefix: str = "loja/displays"

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
