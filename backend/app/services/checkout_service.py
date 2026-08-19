"""Finalizacao do pedido (checkout sem pagamento). Estoque so e decrementado
aqui -- nunca ao adicionar item ao carrinho -- para nao travar estoque com
carrinhos abandonados. Tudo roda numa unica transacao: ou o pedido inteiro
e confirmado, ou nada e alterado (nem estoque, nem carrinho)."""
import random
import string

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.carrinho_item import CarrinhoItem
from app.models.estoque import Estoque
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.pedido import Pedido
from app.models.pedido_item import PedidoItem
from app.models.produto import Produto
from app.models.sessao_carrinho import StatusSessaoCarrinho
from app.services.cart_service import obter_sessao_valida
from app.services.exceptions import CarrinhoVazioError, EstoqueInsuficienteError

_ALFABETO_NUMERO_PEDIDO = string.digits


def _gerar_numero_pedido(db: Session) -> str:
    while True:
        numero = "".join(random.choices(_ALFABETO_NUMERO_PEDIDO, k=6))
        existe = db.execute(select(Pedido).where(Pedido.numero_pedido == numero)).scalar_one_or_none()
        if existe is None:
            return numero


def finalizar(db: Session, sessao_id: str) -> Pedido:
    sessao = obter_sessao_valida(db, sessao_id)

    stmt = (
        select(CarrinhoItem)
        .options(joinedload(CarrinhoItem.produto).joinedload(Produto.estoque))
        .where(CarrinhoItem.sessao_carrinho_id == sessao_id)
    )
    itens_carrinho = list(db.execute(stmt).unique().scalars())
    if not itens_carrinho:
        raise CarrinhoVazioError()

    # Passo 1: valida estoque de TODOS os itens antes de alterar qualquer
    # coisa (tudo ou nada -- nao decrementa parcialmente).
    insuficientes = []
    for item in itens_carrinho:
        disponivel = item.produto.estoque.quantidade if item.produto.estoque else 0
        if disponivel < item.quantidade:
            insuficientes.append(
                {
                    "produto_id": item.produto_id,
                    "nome": item.produto.nome,
                    "solicitado": item.quantidade,
                    "disponivel": disponivel,
                }
            )
    if insuficientes:
        raise EstoqueInsuficienteError(insuficientes)

    valor_total = sum((item.quantidade * item.preco_unitario_snapshot for item in itens_carrinho))

    pedido = Pedido(
        numero_pedido=_gerar_numero_pedido(db),
        sessao_carrinho_id=sessao_id,
        valor_total=valor_total,
    )
    db.add(pedido)
    db.flush()  # garante pedido.id

    for item in itens_carrinho:
        db.add(
            PedidoItem(
                pedido_id=pedido.id,
                produto_id=item.produto_id,
                nome_produto_snapshot=item.produto.nome,
                preco_unitario_snapshot=item.preco_unitario_snapshot,
                quantidade=item.quantidade,
                subtotal=item.quantidade * item.preco_unitario_snapshot,
            )
        )

        estoque = db.execute(
            select(Estoque).where(Estoque.produto_id == item.produto_id)
        ).scalar_one()
        estoque.quantidade -= item.quantidade

        # `quantidade` aqui e a contagem de unidades vendidas (positiva),
        # no mesmo padrao usado pelo historico simulado do seed -- e o que
        # as regras de giro/dias-sem-venda da IA (Fase 4) vao somar por
        # tipo=SAIDA_VENDA. O decremento em si ja foi aplicado acima,
        # direto no `estoque.quantidade`.
        db.add(
            MovimentacaoEstoque(
                produto_id=item.produto_id,
                tipo=TipoMovimentacao.SAIDA_VENDA,
                quantidade=item.quantidade,
                pedido_id=pedido.id,
            )
        )

        db.delete(item)

    sessao.status = StatusSessaoCarrinho.FINALIZADA

    db.commit()
    db.refresh(pedido)
    return pedido
