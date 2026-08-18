from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.estoque import AjusteEstoqueCreate, EstoqueItemRead, MovimentacaoEstoqueRead
from app.services import stock_service
from app.services.exceptions import ProdutoNaoEncontradoError

router = APIRouter(prefix="/estoque", tags=["estoque"])


@router.get("", response_model=list[EstoqueItemRead])
def listar_estoque(somente_baixo: bool = False, db: Session = Depends(get_db)):
    return stock_service.listar_estoque(db, somente_baixo=somente_baixo)


@router.post("/{produto_id}/ajuste", response_model=EstoqueItemRead)
def ajustar_estoque(produto_id: int, dados: AjusteEstoqueCreate, db: Session = Depends(get_db)):
    # TODO Fase 2: passar o funcionario autenticado (funcionario_id) para
    # registrar quem fez o ajuste, quando o login existir.
    try:
        stock_service.ajustar_estoque(db, produto_id, dados)
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
