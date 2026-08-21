"""Aplica ou reverte a troca de preco de um produto, sempre gravando
`historico_preco` na mesma transacao (tudo ou nada) -- mesmo padrao ja
usado em `checkout_service.finalizar`. E o unico lugar do sistema que
realmente muda `produto.preco_promocional`/`promocao_ativa`; tanto a
aprovacao manual quanto a aprovacao de uma sugestao de IA passam por
aqui."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.historico_preco import HistoricoPreco, TipoAlteracaoPreco
from app.models.produto import Produto
from app.services.exceptions import ProdutoNaoEncontradoError

DIAS_VALIDADE_PADRAO = 14


def _obter_produto(db: Session, produto_id: int) -> Produto:
    produto = db.execute(select(Produto).where(Produto.id == produto_id)).scalar_one_or_none()
    if produto is None:
        raise ProdutoNaoEncontradoError(str(produto_id))
    return produto


def aplicar_promocao(
    db: Session,
    produto_id: int,
    preco_novo: Decimal,
    *,
    tipo_alteracao: TipoAlteracaoPreco = TipoAlteracaoPreco.MANUAL,
    sugestao_id: int | None = None,
    alterado_por: int | None = None,
    dias_validade: int = DIAS_VALIDADE_PADRAO,
    horas_validade: float | None = None,
) -> Produto:
    """`horas_validade`, quando informado, manda em cima de `dias_validade`
    -- existe pra permitir promocoes curtas (ex.: 2h, pra demo/teste),
    sem perder o default em dias usado no dia a dia."""
    produto = _obter_produto(db, produto_id)
    preco_anterior = produto.preco_vigente

    validade = timedelta(hours=horas_validade) if horas_validade is not None else timedelta(days=dias_validade)

    produto.preco_promocional = preco_novo
    produto.promocao_ativa = True
    produto.promocao_expira_em = datetime.now(UTC).replace(tzinfo=None) + validade

    db.add(
        HistoricoPreco(
            produto_id=produto.id,
            preco_anterior=preco_anterior,
            preco_novo=preco_novo,
            tipo_alteracao=tipo_alteracao,
            sugestao_id=sugestao_id,
            alterado_por=alterado_por,
        )
    )
    db.commit()
    db.refresh(produto)
    return produto


def listar_historico(db: Session, *, produto_id: int | None = None, limite: int = 200) -> list[HistoricoPreco]:
    stmt = (
        select(HistoricoPreco)
        .options(joinedload(HistoricoPreco.produto))
        .order_by(HistoricoPreco.criado_em.desc())
        .limit(limite)
    )
    if produto_id is not None:
        stmt = stmt.where(HistoricoPreco.produto_id == produto_id)
    return list(db.execute(stmt).unique().scalars())


def reverter_promocao(db: Session, produto_id: int, *, alterado_por: int | None = None) -> Produto:
    """Encerra a promocao ativa (se houver), voltando o preco vigente pro
    `preco_normal`. Usado pela expiracao automatica (`promocao_expira_em`
    no passado) -- ver `promotion_service.expirar_promocoes_vencidas`."""
    produto = _obter_produto(db, produto_id)
    if not produto.promocao_ativa:
        return produto

    preco_anterior = produto.preco_vigente
    produto.promocao_ativa = False
    produto.preco_promocional = None
    produto.promocao_expira_em = None

    db.add(
        HistoricoPreco(
            produto_id=produto.id,
            preco_anterior=preco_anterior,
            preco_novo=produto.preco_normal,
            tipo_alteracao=TipoAlteracaoPreco.FIM_PROMOCAO,
            alterado_por=alterado_por,
        )
    )
    db.commit()
    db.refresh(produto)
    return produto
