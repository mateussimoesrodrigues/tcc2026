"""Job diario do motor de promocoes: expira promocoes vencidas e gera
sugestoes novas. So sobe se `ENABLE_SCHEDULER=true` no `.env` (ver
`core/config.py`) -- desligado por padrao pra nao bater na API do LLM de
verdade durante dev/teste. O endpoint `POST /promocoes/gerar-agora`
(ver `routers/promotions.py`) cobre a geracao sob demanda enquanto o
scheduler estiver desligado."""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.database import SessionLocal
from app.services import promotion_service

_scheduler: BackgroundScheduler | None = None


def _rodar_job_diario() -> None:
    db = SessionLocal()
    try:
        promotion_service.expirar_promocoes_vencidas(db)
        promotion_service.gerar_sugestoes(db)
    finally:
        db.close()


def iniciar_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    _scheduler.add_job(_rodar_job_diario, CronTrigger(hour=6, minute=0), id="motor_promocoes_diario")
    _scheduler.start()
    return _scheduler


def parar_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
