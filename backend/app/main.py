from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings, validar_configuracao_producao
from app.routers import (
    analytics,
    auth,
    cart,
    checkout,
    displays,
    orders,
    price_history,
    products,
    promotions,
    public_catalog,
    stock,
)

settings = get_settings()
# Falha rapido no boot se ENVIRONMENT=production estiver com config
# insegura (ex.: JWT_SECRET_KEY ainda no valor padrao do repositorio).
validar_configuracao_producao(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        if settings.enable_scheduler:
            from app.jobs.scheduler import iniciar_scheduler, parar_scheduler

            iniciar_scheduler()
            yield
            parar_scheduler()
        else:
            yield
    finally:
        # O cliente MQTT (push de preco pros displays) sobe sob demanda na
        # primeira aprovacao de promocao e mantem uma thread de rede viva --
        # encerrar aqui evita deixar a thread pendurada no shutdown.
        if settings.mqtt_enabled:
            from app.services.mqtt_publisher import fechar_cliente

            fechar_cliente()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict:
    """Endpoint simples para verificar se a API esta de pe e qual banco esta em uso."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "using_sqlite_fallback": settings.using_sqlite_fallback,
    }


app.include_router(auth.router)
app.include_router(products.router)
app.include_router(stock.router)
app.include_router(public_catalog.router)
app.include_router(cart.router)
app.include_router(checkout.router)
app.include_router(orders.router)
app.include_router(promotions.router)
app.include_router(price_history.router)
app.include_router(analytics.router)
app.include_router(displays.router)
