from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.carrinho import (
    CarrinhoItemAtualizar,
    CarrinhoItemCreate,
    CarrinhoItemRead,
    CarrinhoRead,
    SessaoCarrinhoRead,
)
from app.services import cart_service
from app.services.exceptions import ProdutoNaoEncontradoError, SessaoCarrinhoInvalidaError

router = APIRouter(prefix="/carrinho", tags=["carrinho"])
# Area publica (sem login): a identidade do cliente e o UUID da
# sessao_carrinho, enviado pelo frontend no header X-Cart-Session.


def _sessao_id(x_cart_session: str = Header(..., alias="X-Cart-Session")) -> str:
    return x_cart_session


def _sessao_invalida() -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND, "Sessao de carrinho invalida, expirada ou ja finalizada"
    )


def _para_item_read(item) -> CarrinhoItemRead:
    return CarrinhoItemRead(
        produto_id=item.produto_id,
        nome=item.produto.nome,
        marca=item.produto.marca,
        tamanho=item.produto.tamanho,
        quantidade=item.quantidade,
        preco_unitario_snapshot=item.preco_unitario_snapshot,
        subtotal=item.quantidade * item.preco_unitario_snapshot,
    )


@router.post("/sessoes", response_model=SessaoCarrinhoRead, status_code=status.HTTP_201_CREATED)
def criar_sessao(db: Session = Depends(get_db)):
    """Chamado uma vez pelo frontend (primeiro acesso do cliente) -- o
    UUID devolvido e guardado no localStorage e reenviado em toda chamada
    seguinte via X-Cart-Session."""
    sessao = cart_service.criar_sessao(db)
    return SessaoCarrinhoRead(sessao_id=sessao.id)


@router.get("", response_model=CarrinhoRead)
def ver_carrinho(sessao_id: str = Depends(_sessao_id), db: Session = Depends(get_db)):
    try:
        itens, total = cart_service.listar_itens(db, sessao_id)
    except SessaoCarrinhoInvalidaError:
        raise _sessao_invalida()
    return CarrinhoRead(itens=[_para_item_read(i) for i in itens], total=total)


@router.post("/itens", response_model=CarrinhoRead, status_code=status.HTTP_201_CREATED)
def adicionar_item(
    dados: CarrinhoItemCreate,
    sessao_id: str = Depends(_sessao_id),
    db: Session = Depends(get_db),
):
    try:
        cart_service.adicionar_item(db, sessao_id, dados.produto_id, dados.quantidade)
    except SessaoCarrinhoInvalidaError:
        raise _sessao_invalida()
    except ProdutoNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produto nao encontrado ou inativo")

    itens, total = cart_service.listar_itens(db, sessao_id)
    return CarrinhoRead(itens=[_para_item_read(i) for i in itens], total=total)


@router.put("/itens/{produto_id}", response_model=CarrinhoRead)
def atualizar_item(
    produto_id: int,
    dados: CarrinhoItemAtualizar,
    sessao_id: str = Depends(_sessao_id),
    db: Session = Depends(get_db),
):
    try:
        cart_service.atualizar_quantidade(db, sessao_id, produto_id, dados.quantidade)
    except SessaoCarrinhoInvalidaError:
        raise _sessao_invalida()
    except ProdutoNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item nao esta no carrinho")

    itens, total = cart_service.listar_itens(db, sessao_id)
    return CarrinhoRead(itens=[_para_item_read(i) for i in itens], total=total)


@router.delete("/itens/{produto_id}", response_model=CarrinhoRead)
def remover_item(
    produto_id: int, sessao_id: str = Depends(_sessao_id), db: Session = Depends(get_db)
):
    try:
        cart_service.remover_item(db, sessao_id, produto_id)
    except SessaoCarrinhoInvalidaError:
        raise _sessao_invalida()
    except ProdutoNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item nao esta no carrinho")

    itens, total = cart_service.listar_itens(db, sessao_id)
    return CarrinhoRead(itens=[_para_item_read(i) for i in itens], total=total)
