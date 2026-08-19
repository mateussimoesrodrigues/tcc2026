"""Regras do carrinho anonimo do cliente. A identidade do cliente e o UUID
de `sessao_carrinho`, gerado no primeiro acesso e enviado pelo frontend em
toda chamada via header `X-Cart-Session` (ver `routers/cart.py`).

O preco mostrado no carrinho e sempre o `preco_unitario_snapshot` travado
no momento em que o item foi escaneado/adicionado, nao o preco atual do
produto (que pode mudar por uma promocao aprovada entre o scan e o
checkout)."""
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.carrinho_item import CarrinhoItem
from app.models.produto import Produto
from app.models.sessao_carrinho import SessaoCarrinho, StatusSessaoCarrinho
from app.services.exceptions import ProdutoNaoEncontradoError, SessaoCarrinhoInvalidaError


def criar_sessao(db: Session) -> SessaoCarrinho:
    sessao = SessaoCarrinho()
    db.add(sessao)
    db.commit()
    db.refresh(sessao)
    return sessao


def obter_sessao_valida(db: Session, sessao_id: str) -> SessaoCarrinho:
    sessao = db.get(SessaoCarrinho, sessao_id)
    agora = datetime.now(UTC).replace(tzinfo=None)
    if (
        sessao is None
        or sessao.status != StatusSessaoCarrinho.ABERTA
        or sessao.expira_em < agora
    ):
        raise SessaoCarrinhoInvalidaError(sessao_id)
    return sessao


def _item_com_produto(db: Session, sessao_id: str, produto_id: int) -> CarrinhoItem | None:
    stmt = select(CarrinhoItem).where(
        CarrinhoItem.sessao_carrinho_id == sessao_id,
        CarrinhoItem.produto_id == produto_id,
    )
    return db.execute(stmt).scalar_one_or_none()


def adicionar_item(db: Session, sessao_id: str, produto_id: int, quantidade: int) -> CarrinhoItem:
    obter_sessao_valida(db, sessao_id)

    produto = db.execute(
        select(Produto).where(Produto.id == produto_id, Produto.ativo.is_(True))
    ).scalar_one_or_none()
    if produto is None:
        raise ProdutoNaoEncontradoError(str(produto_id))

    item = _item_com_produto(db, sessao_id, produto_id)
    if item is None:
        item = CarrinhoItem(
            sessao_carrinho_id=sessao_id,
            produto_id=produto_id,
            quantidade=quantidade,
            preco_unitario_snapshot=produto.preco_vigente,
        )
        db.add(item)
    else:
        item.quantidade += quantidade
        # Reancora o preco no valor vigente agora -- evita carrinho com
        # preco "congelado" ha muito tempo numa sessao de longa duracao.
        item.preco_unitario_snapshot = produto.preco_vigente

    db.commit()
    db.refresh(item)
    return item


def atualizar_quantidade(db: Session, sessao_id: str, produto_id: int, quantidade: int) -> None:
    obter_sessao_valida(db, sessao_id)

    item = _item_com_produto(db, sessao_id, produto_id)
    if item is None:
        raise ProdutoNaoEncontradoError(str(produto_id))

    if quantidade <= 0:
        db.delete(item)
    else:
        item.quantidade = quantidade
    db.commit()


def remover_item(db: Session, sessao_id: str, produto_id: int) -> None:
    obter_sessao_valida(db, sessao_id)

    item = _item_com_produto(db, sessao_id, produto_id)
    if item is None:
        raise ProdutoNaoEncontradoError(str(produto_id))

    db.delete(item)
    db.commit()


def listar_itens(db: Session, sessao_id: str) -> tuple[list[CarrinhoItem], Decimal]:
    obter_sessao_valida(db, sessao_id)

    stmt = (
        select(CarrinhoItem)
        .options(joinedload(CarrinhoItem.produto))
        .where(CarrinhoItem.sessao_carrinho_id == sessao_id)
        .order_by(CarrinhoItem.criado_em)
    )
    itens = list(db.execute(stmt).scalars())
    total = sum((item.quantidade * item.preco_unitario_snapshot for item in itens), Decimal("0.00"))
    return itens, total
