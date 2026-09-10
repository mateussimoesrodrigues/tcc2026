from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_funcionario
from app.schemas.analytics import (
    MetricasSugestoesRead,
    PontoSerieRead,
    ProdutoParadoRead,
    PromocaoEfeitoRead,
    ResumoAnalyticsRead,
)
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(get_current_funcionario)])


def _desde(janela_dias: int | None) -> datetime | None:
    if janela_dias is None:
        return None
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=janela_dias)


@router.get("/sugestoes", response_model=MetricasSugestoesRead)
def sugestoes(janela_dias: int | None = None, db: Session = Depends(get_db)):
    """Funil de decisao humana: quantas sugestoes da IA o funcionario
    aprovou, quanto tempo levou pra decidir e como isso varia por modelo."""
    return MetricasSugestoesRead(**analytics_service.metricas_sugestoes(db, desde=_desde(janela_dias)))


@router.get("/promocoes", response_model=list[PromocaoEfeitoRead])
def promocoes(limite: int = analytics_service.LIMITE_PROMOCOES_PADRAO, db: Session = Depends(get_db)):
    """Efeito de cada promocao: vendas durante a janela contra a janela de
    mesmo tamanho imediatamente anterior. Ver a `observacao` de cada linha
    -- nao e experimento controlado."""
    return [PromocaoEfeitoRead(**p) for p in analytics_service.efeito_promocoes(db, limite=limite)]


@router.get("/vendas", response_model=list[PontoSerieRead])
def vendas(
    granularidade: Literal["dia", "semana", "mes"] = "dia",
    janela_dias: int = analytics_service.JANELA_PADRAO_DIAS,
    db: Session = Depends(get_db),
):
    serie = analytics_service.serie_vendas(db, granularidade=granularidade, desde=_desde(janela_dias))
    return [PontoSerieRead(**p) for p in serie]


@router.get("/produtos-parados", response_model=list[ProdutoParadoRead])
def parados(
    dias: int = analytics_service.DIAS_PARADO_PADRAO,
    limite: int = analytics_service.LIMITE_PARADOS_PADRAO,
    db: Session = Depends(get_db),
):
    return [ProdutoParadoRead(**p) for p in analytics_service.produtos_parados(db, dias=dias, limite=limite)]


@router.get("/resumo", response_model=ResumoAnalyticsRead)
def resumo(janela_dias: int = analytics_service.JANELA_PADRAO_DIAS, db: Session = Depends(get_db)):
    """Tudo que a tela de indicadores precisa numa chamada so."""
    dados = analytics_service.resumo(db, janela_dias=janela_dias)
    return ResumoAnalyticsRead(dados_simulados=get_settings().dados_simulados, **dados)
