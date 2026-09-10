from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_funcionario
from app.models.funcionario import Funcionario
from app.schemas.estoque import (
    AjusteEstoqueCreate,
    EntradaCreate,
    EntradaRecenteRead,
    EntradaResultado,
    EstoqueItemRead,
    MovimentacaoEstoqueRead,
)
from app.services import stock_service
from app.services.exceptions import ProdutoNaoEncontradoError

router = APIRouter(prefix="/estoque", tags=["estoque"], dependencies=[Depends(get_current_funcionario)])


@router.get("", response_model=list[EstoqueItemRead])
def listar_estoque(somente_baixo: bool = False, db: Session = Depends(get_db)):
    return stock_service.listar_estoque(db, somente_baixo=somente_baixo)


# As rotas de /entradas vem antes das de /{produto_id} de proposito: o
# FastAPI casa na ordem de declaracao, e uma rota futura de um segmento so
# (ex.: GET /estoque/{produto_id}) engoliria "entradas" como se fosse um id.
@router.post("/entradas", response_model=EntradaResultado, status_code=status.HTTP_201_CREATED)
def registrar_entrada(
    dados: EntradaCreate,
    db: Session = Depends(get_db),
    funcionario: Funcionario = Depends(get_current_funcionario),
):
    """Recebimento de mercadoria: soma no estoque, registra o custo pago e
    reancora o custo do produto pela media ponderada. Tudo ou nada."""
    try:
        return stock_service.registrar_entrada(db, dados, funcionario_id=funcionario.id)
    except ProdutoNaoEncontradoError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Produto {e} nao encontrado")


@router.get("/entradas", response_model=list[EntradaRecenteRead])
def listar_entradas(limite: int = 100, db: Session = Depends(get_db)):
    return stock_service.listar_entradas(db, limite=limite)


@router.post("/{produto_id}/ajuste", response_model=EstoqueItemRead)
def ajustar_estoque(
    produto_id: int,
    dados: AjusteEstoqueCreate,
    db: Session = Depends(get_db),
    funcionario: Funcionario = Depends(get_current_funcionario),
):
    try:
        stock_service.ajustar_estoque(db, produto_id, dados, funcionario_id=funcionario.id)
    except ProdutoNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produto nao encontrado")

    linhas = stock_service.listar_estoque(db)
    linha = next((l for l in linhas if l["produto_id"] == produto_id), None)
    if linha is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produto nao encontrado ou inativo")
    return linha


@router.get("/{produto_id}/movimentacoes", response_model=list[MovimentacaoEstoqueRead])
def listar_movimentacoes(produto_id: int, db: Session = Depends(get_db)):
    return stock_service.listar_movimentacoes(db, produto_id)
