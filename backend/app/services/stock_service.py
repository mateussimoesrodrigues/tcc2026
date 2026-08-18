"""Regras de estoque: listagem com alerta de estoque baixo e ajustes
manuais (entrada/perda), sempre gravando a movimentacao correspondente.

LIMITE_ESTOQUE_BAIXO_PADRAO e o limite global usado quando o produto nao
tem `quantidade_minima` proprio definido. Na Fase 2 isso vira configuravel
via a tabela `configuracao`; por ora e uma constante (mesmo valor usado
pelo seed, para os dados de exemplo baterem com o alerta).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.estoque import Estoque
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.produto import Produto
from app.schemas.estoque import AjusteEstoqueCreate
from app.services.exceptions import ProdutoNaoEncontradoError

LIMITE_ESTOQUE_BAIXO_PADRAO = 5


def listar_estoque(db: Session, *, somente_baixo: bool = False) -> list[dict]:
    stmt = (
        select(Produto)
        .join(Estoque)
        .options(joinedload(Produto.estoque))
        .where(Produto.ativo.is_(True))
        .order_by(Produto.nome)
    )
    produtos = db.execute(stmt).unique().scalars().all()

    linhas = []
    for produto in produtos:
        estoque = produto.estoque
        limite = estoque.quantidade_minima if estoque.quantidade_minima is not None else LIMITE_ESTOQUE_BAIXO_PADRAO
        baixo = estoque.quantidade <= limite
        if somente_baixo and not baixo:
            continue
        linhas.append(
            {
                "produto_id": produto.id,
                "nome": produto.nome,
                "marca": produto.marca,
                "tamanho": produto.tamanho,
                "quantidade": estoque.quantidade,
                "quantidade_minima": estoque.quantidade_minima,
                "limite_aplicado": limite,
                "estoque_baixo": baixo,
            }
        )
    return linhas


def ajustar_estoque(
    db: Session, produto_id: int, dados: AjusteEstoqueCreate, funcionario_id: int | None = None
) -> Estoque:
    estoque = db.execute(
        select(Estoque).where(Estoque.produto_id == produto_id)
    ).scalar_one_or_none()
    if estoque is None:
        raise ProdutoNaoEncontradoError(str(produto_id))

    estoque.quantidade += dados.quantidade
    db.add(
        MovimentacaoEstoque(
            produto_id=produto_id,
            tipo=dados.tipo,
            quantidade=dados.quantidade,
            funcionario_id=funcionario_id,
        )
    )
    db.commit()
    db.refresh(estoque)
    return estoque


def listar_movimentacoes(db: Session, produto_id: int) -> list[MovimentacaoEstoque]:
    stmt = (
        select(MovimentacaoEstoque)
        .where(MovimentacaoEstoque.produto_id == produto_id)
        .order_by(MovimentacaoEstoque.criado_em.desc())
        .limit(200)
    )
    return list(db.execute(stmt).scalars())
