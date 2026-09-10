"""Jobs do motor de promocoes. So sobe se `ENABLE_SCHEDULER=true` no
`.env` (ver `core/config.py`) -- desligado por padrao pra nao bater na
API do LLM de verdade durante dev/teste. O endpoint
`POST /promocoes/gerar-agora` cobre a geracao sob demanda e
`POST /promocoes/expirar-agora` cobre a expiracao sob demanda enquanto o
scheduler estiver desligado (ver `routers/promotions.py`).

Dois jobs, cadencias diferentes:
- expirar promocoes vencidas: e so leitura/escrita no banco (barato), roda
  a cada `INTERVALO_EXPIRACAO_MINUTOS` pra promocoes curtas (ex.: aprovadas
  com `horas_validade=2`) voltarem ao preco normal poucos minutos depois
  de vencer, nao so no dia seguinte.
- gerar sugestoes novas: chama o LLM (tem custo/latencia), continua so
  uma vez por dia.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.database import SessionLocal
from app.services import order_service, promotion_service

_scheduler: BackgroundScheduler | None = None

INTERVALO_EXPIRACAO_MINUTOS = 15


def _rodar_job_expiracao() -> None:
    """Duas expiracoes baratas (so banco) na mesma passada: promocoes que
    venceram voltam ao preco normal, e pedidos que ninguem levou ao caixa
    saem de GERADO (sem mexer em estoque -- ver order_service)."""
    db = SessionLocal()
    try:
        promotion_service.expirar_promocoes_vencidas(db)
        order_service.expirar_pedidos_vencidos(db)
    finally:
        db.close()


def _rodar_job_geracao_diaria() -> None:
    db = SessionLocal()
    try:
        promotion_service.gerar_sugestoes(db)
    finally:
        db.close()


def iniciar_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    _scheduler.add_job(
        _rodar_job_expiracao,
        IntervalTrigger(minutes=INTERVALO_EXPIRACAO_MINUTOS),
        id="motor_promocoes_expiracao",
    )
    _scheduler.add_job(_rodar_job_geracao_diaria, CronTrigger(hour=6, minute=0), id="motor_promocoes_geracao_diaria")
    _scheduler.start()
    return _scheduler


def parar_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
