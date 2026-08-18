from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import products, stock

settings = get_settings()

app = FastAPI(title=settings.app_name)

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


app.include_router(products.router)
app.include_router(stock.router)

# Proximos routers entram conforme as fases forem implementadas:
# from app.routers import auth, cart, checkout, promotions
