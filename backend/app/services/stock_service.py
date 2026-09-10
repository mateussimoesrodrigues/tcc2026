"""Regras de estoque: listagem com alerta de estoque baixo, ajustes manuais
(entrada/perda) e entrada de mercadoria com custo, sempre gravando a
movimentacao correspondente.

Este e o unico modulo que escreve `MovimentacaoEstoque` fora do checkout --
mesma ideia de `price_service` ser o unico que muda preco. Por isso a
entrada de mercadoria mora aqui e nao num servico proprio: dois modulos
mexendo em `Estoque` seria pedir divergencia.

LIMITE_ESTOQUE_BAIXO_PADRAO e o limite global usado quando o produto nao
tem `quantidade_minima` proprio definido. Na Fase 2 isso vira configuravel
via a tabela `configuracao`; por ora e uma constante (mesmo valor usado
pelo seed, para os dados de exemplo baterem com o alerta).
"""
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.estoque import Estoque
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.produto import Produto
from app.schemas.estoque import AjusteEstoqueCreate, EntradaCreate
from app.services import price_service
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


def _aplicar_movimentacao(
    db: Session,
    produto_id: int,
    quantidade: int,
    tipo: TipoMovimentacao,
    *,
    funcionario_id: int | None = None,
    custo_unitario: Decimal | None = None,
    observacao: str | None = None,
) -> Estoque:
    """Soma no saldo e grava a linha do razao, **sem commitar**.

    O commit fica com quem chama porque `registrar_entrada` aplica varias
    movimentacoes numa transacao so: se cada uma commitasse, uma entrada de
    cinco itens viraria cinco transacoes e um erro no quarto item deixaria
    tres lancados. Mesma separacao que `aplicar_promocao` ja faz com
    `commit=False`.
    """
    estoque = db.execute(
        select(Estoque).where(Estoque.produto_id == produto_id)
    ).scalar_one_or_none()
    if estoque is None:
        raise ProdutoNaoEncontradoError(str(produto_id))

    estoque.quantidade += quantidade
    db.add(
        MovimentacaoEstoque(
            produto_id=produto_id,
            tipo=tipo,
            quantidade=quantidade,
            funcionario_id=funcionario_id,
            custo_unitario=custo_unitario,
            observacao=observacao,
        )
    )
    return estoque


def ajustar_estoque(
    db: Session, produto_id: int, dados: AjusteEstoqueCreate, funcionario_id: int | None = None
) -> Estoque:
    estoque = _aplicar_movimentacao(
        db,
        produto_id,
        dados.quantidade,
        dados.tipo,
        funcionario_id=funcionario_id,
        observacao=dados.observacao,
    )
    db.commit()
    db.refresh(estoque)
    return estoque


def custo_medio_ponderado(
    custo_atual: Decimal | None,
    estoque_atual: int,
    custo_unitario: Decimal,
    quantidade: int,
) -> Decimal:
    """Custo das unidades que ficam na prateleira depois da entrada.

    Funcao pura (sem `db`) pra ser testada e explicada isolada, no mesmo
    estilo de `price_service.piso_de_preco`.

    Cai no custo da propria entrada quando nao ha com o que ponderar: sem
    custo anterior (primeira compra registrada) ou sem saldo positivo
    (estoque zerado, ou negativo por ajuste -- ponderar contra saldo
    negativo produziria um custo sem sentido).

    Por que media ponderada e nao ultimo custo: `custo` alimenta
    `price_service.piso_de_preco`, que e o piso que impede a IA de sugerir
    venda no prejuizo. Com ultimo custo, uma unica compra atipica (reposicao
    de emergencia mais cara, lote promocional mais barato) move esse piso na
    hora. A media descreve o custo das unidades que serao vendidas, que e o
    que "margem deste produto" significa quando elas saem.
    """
    if custo_atual is None or estoque_atual <= 0:
        return price_service.quantizar_preco(custo_unitario)

    total = (Decimal(estoque_atual) * custo_atual) + (Decimal(quantidade) * custo_unitario)
    return price_service.quantizar_preco(total / Decimal(estoque_atual + quantidade))


def registrar_entrada(
    db: Session, dados: EntradaCreate, *, funcionario_id: int | None = None
) -> dict:
    """Recebimento de mercadoria: soma no estoque, grava o razao com o custo
    pago e reancora `produto.custo` pela media ponderada.

    Tudo numa transacao so -- ou o recebimento inteiro entra, ou nada entra.
    Um produto inexistente no meio da lista nao pode deixar meio caminhao
    lancado.

    Produto repetido na mesma entrada nao precisa de tratamento especial: as
    linhas sao aplicadas em ordem e cada uma pondera contra o resultado da
    anterior, o que da exatamente a mesma media do lancamento agrupado.
    """
    itens_resultado = []
    valor_total = Decimal("0.00")

    try:
        for item in dados.itens:
            produto = db.execute(
                select(Produto).where(Produto.id == item.produto_id)
            ).scalar_one_or_none()
            if produto is None:
                raise ProdutoNaoEncontradoError(str(item.produto_id))

            estoque_anterior = produto.estoque.quantidade if produto.estoque else 0
            custo_anterior = produto.custo

            custo_resultante = custo_medio_ponderado(
                custo_anterior, estoque_anterior, item.custo_unitario, item.quantidade
            )
            produto.custo = custo_resultante

            _aplicar_movimentacao(
                db,
                item.produto_id,
                item.quantidade,
                TipoMovimentacao.ENTRADA,
                funcionario_id=funcionario_id,
                custo_unitario=item.custo_unitario,
                observacao=dados.observacao,
            )

            subtotal = price_service.quantizar_preco(
                Decimal(item.quantidade) * item.custo_unitario
            )
            valor_total += subtotal
            itens_resultado.append(
                {
                    "produto_id": produto.id,
                    "nome": produto.nome,
                    "quantidade": item.quantidade,
                    "custo_unitario": item.custo_unitario,
                    "custo_anterior": custo_anterior,
                    "custo_resultante": custo_resultante,
                    "estoque_anterior": estoque_anterior,
                    "estoque_resultante": estoque_anterior + item.quantidade,
                    "subtotal": subtotal,
                }
            )

        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "itens": itens_resultado,
        "valor_total": valor_total,
        "registrado_em": datetime.now(UTC).replace(tzinfo=None),
    }


def listar_entradas(db: Session, *, limite: int = 100) -> list[dict]:
    """Historico de recebimentos, lido do proprio razao. Nao existe tabela
    de documento de compra: uma entrada e o conjunto de linhas ENTRADA que
    compartilham `observacao` e horario."""
    stmt = (
        select(MovimentacaoEstoque, Produto.nome)
        .join(Produto, Produto.id == MovimentacaoEstoque.produto_id)
        .where(MovimentacaoEstoque.tipo == TipoMovimentacao.ENTRADA)
        .order_by(MovimentacaoEstoque.criado_em.desc(), MovimentacaoEstoque.id.desc())
        .limit(limite)
    )
    return [
        {
            "id": mov.id,
            "produto_id": mov.produto_id,
            "produto_nome": nome,
            "quantidade": mov.quantidade,
            "custo_unitario": mov.custo_unitario,
            "observacao": mov.observacao,
            "criado_em": mov.criado_em,
        }
        for mov, nome in db.execute(stmt).all()
    ]


def listar_movimentacoes(db: Session, produto_id: int) -> list[MovimentacaoEstoque]:
    stmt = (
        select(MovimentacaoEstoque)
        # Desempate por `id`: `criado_em` tem resolucao de segundo, e duas
        # movimentacoes do mesmo instante (cadastro com saldo inicial
        # seguido de ajuste, ou varios itens da mesma entrada) sairiam em
        # ordem arbitraria -- a lista na tela trocaria de ordem sozinha
        # entre dois carregamentos.
        .where(MovimentacaoEstoque.produto_id == produto_id)
        .order_by(MovimentacaoEstoque.criado_em.desc(), MovimentacaoEstoque.id.desc())
        .limit(200)
    )
    return list(db.execute(stmt).scalars())
