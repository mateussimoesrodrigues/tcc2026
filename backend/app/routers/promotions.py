from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_funcionario
from app.models.funcionario import Funcionario
from app.models.promocao_sugestao import StatusSugestao
from app.schemas.promocao import (
    AprovarSugestaoRequest,
    FalhaGeracao,
    GerarSugestoesResposta,
    RejeitarSugestaoRequest,
    SugestaoRead,
)
from app.services import promotion_service
from app.services.exceptions import SugestaoJaAvaliadaError, SugestaoNaoEncontradaError

router = APIRouter(prefix="/promocoes", tags=["promocoes"], dependencies=[Depends(get_current_funcionario)])


@router.post("/gerar-agora", response_model=GerarSugestoesResposta)
def gerar_agora(db: Session = Depends(get_db)):
    """Roda o motor de IA na hora (regras + LLM), sem esperar o job diario
    -- essencial pra demonstrar o fluxo completo ao vivo. Sugestoes com
    erro de LLM (key ausente, timeout, resposta invalida) aparecem em
    `falhas`, sem travar as demais."""
    resultado = promotion_service.gerar_sugestoes(db)
    return GerarSugestoesResposta(
        candidatos_avaliados=resultado["candidatos_avaliados"],
        sugestoes_criadas=[SugestaoRead.de_model(s) for s in resultado["criadas"]],
        falhas=[FalhaGeracao(**f) for f in resultado["falhas"]],
    )


@router.post("/expirar-agora")
def expirar_agora(db: Session = Depends(get_db)):
    """Reverte na hora as promocoes cujo `promocao_expira_em` ja passou,
    sem esperar o job periodico do scheduler -- util pra testar/demonstrar
    a expiracao automatica (ver `enable_scheduler` em core/config.py)."""
    total = promotion_service.expirar_promocoes_vencidas(db)
    return {"promocoes_revertidas": total}


@router.get("", response_model=list[SugestaoRead])
def listar(status_filtro: StatusSugestao | None = None, db: Session = Depends(get_db)):
    sugestoes = promotion_service.listar_sugestoes(db, status=status_filtro)
    return [SugestaoRead.de_model(s) for s in sugestoes]


@router.post("/{sugestao_id}/aprovar", response_model=SugestaoRead)
def aprovar(
    sugestao_id: int,
    dados: AprovarSugestaoRequest,
    db: Session = Depends(get_db),
    funcionario: Funcionario = Depends(get_current_funcionario),
):
    try:
        sugestao = promotion_service.aprovar(
            db,
            sugestao_id,
            funcionario.id,
            observacao=dados.observacao,
            dias_validade=dados.dias_validade,
            horas_validade=dados.horas_validade,
        )
    except SugestaoNaoEncontradaError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sugestao nao encontrada")
    except SugestaoJaAvaliadaError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Sugestao ja avaliada (status atual: {e})")
    return SugestaoRead.de_model(sugestao)


@router.post("/{sugestao_id}/rejeitar", response_model=SugestaoRead)
def rejeitar(
    sugestao_id: int,
    dados: RejeitarSugestaoRequest,
    db: Session = Depends(get_db),
    funcionario: Funcionario = Depends(get_current_funcionario),
):
    try:
        sugestao = promotion_service.rejeitar(db, sugestao_id, funcionario.id, observacao=dados.observacao)
    except SugestaoNaoEncontradaError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sugestao nao encontrada")
    except SugestaoJaAvaliadaError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Sugestao ja avaliada (status atual: {e})")
    return SugestaoRead.de_model(sugestao)
