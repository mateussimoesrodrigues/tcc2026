from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import auth, cart, checkout, price_history, products, promotions, public_catalog, stock

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.enable_scheduler:
        from app.jobs.scheduler import iniciar_scheduler, parar_scheduler

        iniciar_scheduler()
        yield
        parar_scheduler()
    else:
        yield


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
app.include_router(promotions.router)
app.include_router(price_history.router)
