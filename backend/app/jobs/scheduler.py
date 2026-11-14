"""Jobs de manutencao e simulacao do motor de promocoes. So sobem se
`ENABLE_SCHEDULER=true` no `.env` (ver `core/config.py`) -- desligado por
padrao pra nao rodar dentro do processo de teste.

A *geracao* de sugestoes nao tem mais job por tempo: ela roda apenas sob
demanda, quando o funcionario clica em "Gerar sugestoes agora" na tela de
Promocoes (`POST /promocoes/gerar-agora`, ver `routers/promotions.py`).
Alem do custo/latencia do LLM, promocao gerada sozinha de madrugada
chegava sem ninguem pra avaliar; o clique deixa o disparo explicito.

O job de limpeza continua sendo executado a cada 15 minutos: promocoes vencidas
voltam ao preco normal e pedidos abandonados saem de GERADO. Roda a cada
`INTERVALO_EXPIRACAO_MINUTOS` porque e so leitura/escrita no banco
(barato) e promocoes curtas (ex.: aprovadas com `horas_validade=2`)
precisam voltar ao preco normal poucos minutos depois de vencer. O clique
em "Gerar sugestoes agora" tambem expira as vencidas antes de gerar, e
`POST /promocoes/expirar-agora` cobre a expiracao sob demanda enquanto o
scheduler estiver desligado.

Opcionalmente, `ENABLE_DAILY_SALES_SIMULATOR=true` adiciona um job diario
no horario configurado para alimentar o historico com vendas simuladas.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.database import SessionLocal
from app.core.config import get_settings
from app.services import order_service, promotion_service
from app.services.daily_sales_service import simular_promocoes_do_dia, simular_vendas_do_dia

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


def _rodar_job_vendas_diarias() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        simular_promocoes_do_dia(
            db,
            semente=settings.daily_sales_simulation_seed,
            ativar_produtos=True,
        )
        simular_vendas_do_dia(db, semente=settings.daily_sales_simulation_seed)
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
    settings = get_settings()
    if settings.enable_daily_sales_simulator:
        _scheduler.add_job(
            _rodar_job_vendas_diarias,
            CronTrigger(
                hour=settings.daily_sales_simulation_hour,
                minute=settings.daily_sales_simulation_minute,
            ),
            id="simulacao_vendas_diarias",
            replace_existing=True,
        )
    _scheduler.start()
    return _scheduler


def parar_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
