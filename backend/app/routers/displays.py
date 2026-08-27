from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_funcionario, get_display_by_token
from app.models.display import Display
from app.schemas.display import (
    DisplayCreate,
    DisplayCriadoResponse,
    DisplayEstadoResponse,
    DisplayRead,
    DisplaySincronizarRequest,
    DisplayUpdate,
    TokenRegeneradoResponse,
)
from app.services import display_service
from app.services.exceptions import DisplayNaoEncontradoError

router = APIRouter(prefix="/displays", tags=["displays"])
# Rotas de gestao (criar/listar/editar display, vincular a um produto)
# exigem funcionario logado -- ver dependencies por rota abaixo. A rota
# usada pelo proprio dispositivo (`/sincronizar`) e a excecao: nao tem
# como um ESP32 fazer login de funcionario, entao se autentica sozinho
# via `X-Display-Token` (ver `get_display_by_token`). Arquitetura completa
# em `docs/displays-fisicos.md`.


@router.post(
    "",
    response_model=DisplayCriadoResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_funcionario)],
)
def criar_display(dados: DisplayCreate, db: Session = Depends(get_db)):
    """O `token` da resposta so aparece aqui -- copiar pro firmware do
    dispositivo na hora de configurar (ver README/docs). Se perder, use
    `POST /displays/{id}/token` pra gerar outro (invalida o anterior)."""
    return display_service.criar_display(db, dados)


@router.get("", response_model=list[DisplayRead], dependencies=[Depends(get_current_funcionario)])
def listar_displays(db: Session = Depends(get_db)):
    return display_service.listar_displays(db)


@router.get("/{display_id}", response_model=DisplayRead, dependencies=[Depends(get_current_funcionario)])
def obter_display(display_id: int, db: Session = Depends(get_db)):
    try:
        return display_service.obter_display(db, display_id)
    except DisplayNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Display nao encontrado")


@router.put("/{display_id}", response_model=DisplayRead, dependencies=[Depends(get_current_funcionario)])
def atualizar_display(display_id: int, dados: DisplayUpdate, db: Session = Depends(get_db)):
    """Usado tambem pra (re)vincular o display a um produto -- so mandar
    `produto_id` (ou `null` pra desvincular)."""
    try:
        return display_service.atualizar_display(db, display_id, dados)
    except DisplayNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Display nao encontrado")


@router.delete("/{display_id}", response_model=DisplayRead, dependencies=[Depends(get_current_funcionario)])
def desativar_display(display_id: int, db: Session = Depends(get_db)):
    """Soft delete: desativa o display e invalida seu token na pratica (a
    dependency de autenticacao do dispositivo rejeita display inativo)."""
    try:
        return display_service.desativar_display(db, display_id)
    except DisplayNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Display nao encontrado")


@router.post(
    "/{display_id}/token",
    response_model=TokenRegeneradoResponse,
    dependencies=[Depends(get_current_funcionario)],
)
def regenerar_token(display_id: int, db: Session = Depends(get_db)):
    """Gera um token novo e invalida o anterior -- usar se o dispositivo
    for extraviado/substituido. Precisa regravar o firmware com o token
    novo depois."""
    try:
        display = display_service.regenerar_token(db, display_id)
    except DisplayNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Display nao encontrado")
    return TokenRegeneradoResponse(token=display.token)


@router.post("/sincronizar", response_model=DisplayEstadoResponse)
def sincronizar(
    dados: DisplaySincronizarRequest = DisplaySincronizarRequest(),
    display: Display = Depends(get_display_by_token),
    db: Session = Depends(get_db),
):
    """Chamada pelo proprio dispositivo (nao pelo funcionario) -- autentica
    via header `X-Display-Token`, nao via JWT. Devolve o preco vigente do
    produto vinculado (se houver) pronto pra desenhar na etiqueta, mais
    `proximo_sync_em_segundos` pra o firmware saber quanto tempo dormir
    ate a proxima chamada."""
    return display_service.sincronizar(db, display, dados)
