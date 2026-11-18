from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
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
    SugestaoReposicaoRead,
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


@router.get("/reposicao", response_model=SugestaoReposicaoRead)
def reposicao(
    dias_alerta: int = analytics_service.DIAS_ALERTA_REPOSICAO_PADRAO,
    dias_cobertura: int = analytics_service.DIAS_COBERTURA_PADRAO,
    limite: int = analytics_service.LIMITE_REPOSICAO_PADRAO,
    db: Session = Depends(get_db),
):
    """O que vai faltar: produtos que acabam dentro de `dias_alerta` no
    ritmo atual, mais os que ja romperam. Espelho de `produtos-parados`.

    Fora do `/resumo` de proposito: aquele endpoint monta a tela de
    indicadores inteira numa chamada e ja carrega tres agregacoes; esta
    varre o catalogo e nao e renderizada la."""
    return SugestaoReposicaoRead(
        **analytics_service.sugerir_reposicao(
            db, dias_alerta=dias_alerta, dias_cobertura=dias_cobertura, limite=limite
        )
    )


@router.get("/resumo", response_model=ResumoAnalyticsRead)
def resumo(
    janela_dias: int = analytics_service.JANELA_PADRAO_DIAS,
    data_desde: date | None = None,
    data_ate: date | None = None,
    db: Session = Depends(get_db),
):
    """Tudo que a tela de indicadores precisa numa chamada so."""
    if (data_desde is None) != (data_ate is None):
        raise HTTPException(
            status_code=400,
            detail="data_desde e data_ate devem ser informadas juntas.",
        )
    if data_desde is not None and data_ate is not None:
        if data_desde > data_ate:
            raise HTTPException(status_code=400, detail="data_desde nao pode ser maior que data_ate.")
        inicio = datetime.combine(data_desde, time.min)
        fim = datetime.combine(data_ate + timedelta(days=1), time.min)
        dados = analytics_service.resumo(db, desde=inicio, ate=fim)
    else:
        dados = analytics_service.resumo(db, janela_dias=janela_dias)
    settings = get_settings()
    return ResumoAnalyticsRead(
        dados_simulados=settings.dados_simulados, origem_dados=settings.origem_dados, **dados
    )
