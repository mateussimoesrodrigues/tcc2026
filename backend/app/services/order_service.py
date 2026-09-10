"""Leitura e conferencia de pedidos no caixa fisico.

Fecha o ciclo que o checkout deixava em aberto: ate aqui `POST /checkout`
gerava um numero de 6 digitos e o fluxo digital terminava ali -- nenhuma
rota lia `pedido`, entao o caixa nem conseguia ver o que o cliente tinha
comprado, e `pedido.status` nunca saia de GERADO.

Duas decisoes de negocio que valem registro:

1. **Pedido expirado ainda pode ser conferido.** Os 20 minutos de
   `expira_em` sao uma expectativa de tempo ate o caixa, nao uma regra
   rigida -- cliente pega fila, atende telefone, volta pra pegar mais um
   item. Recusar a conferencia puniria o cliente por algo que o sistema
   nao controla. A conferencia devolve `estava_expirado` pro caixa ver o
   aviso e conferir com mais atencao.

2. **Expirar um pedido NAO devolve estoque.** A baixa acontece no
   checkout, quando a mercadoria ja saiu da prateleira e foi pro carrinho
   fisico do cliente. Devolver estoque automaticamente criaria divergencia
   com a prateleira real; a correcao de um pedido abandonado e um ajuste
   manual de estoque (ver `stock_service`), feito por quem recolocou os
   itens na prateleira.
"""
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.funcionario import Funcionario
from app.models.pedido import Pedido, StatusPedido
from app.services.exceptions import PedidoJaConferidoError, PedidoNaoEncontradoError

LIMITE_LISTAGEM_PADRAO = 100


def _agora() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def buscar_por_numero(db: Session, numero: str) -> Pedido:
    pedido = db.execute(
        select(Pedido).options(joinedload(Pedido.itens)).where(Pedido.numero_pedido == numero.strip())
    ).unique().scalar_one_or_none()
    if pedido is None:
        raise PedidoNaoEncontradoError(numero)
    return pedido


def nome_do_conferente(db: Session, pedido: Pedido) -> str | None:
    if pedido.conferido_por is None:
        return None
    return db.execute(
        select(Funcionario.nome).where(Funcionario.id == pedido.conferido_por)
    ).scalar_one_or_none()


def conferir(db: Session, numero: str, funcionario_id: int) -> tuple[Pedido, bool]:
    """Marca o pedido como conferido no caixa. Devolve (pedido,
    estava_expirado) -- o segundo elemento so alimenta o aviso na tela, nao
    impede a conferencia (ver decisao 1 no docstring do modulo)."""
    pedido = buscar_por_numero(db, numero)

    if pedido.status == StatusPedido.CONFERIDO_NO_CAIXA:
        raise PedidoJaConferidoError(pedido.conferido_em, nome_do_conferente(db, pedido))

    agora = _agora()
    estava_expirado = pedido.expira_em < agora

    pedido.status = StatusPedido.CONFERIDO_NO_CAIXA
    pedido.conferido_em = agora
    pedido.conferido_por = funcionario_id
    db.commit()
    db.refresh(pedido)
    return pedido, estava_expirado


def listar_pedidos(
    db: Session,
    *,
    status: StatusPedido | None = None,
    desde: datetime | None = None,
    limite: int = LIMITE_LISTAGEM_PADRAO,
) -> list[Pedido]:
    stmt = select(Pedido).order_by(Pedido.criado_em.desc()).limit(limite)
    if status is not None:
        stmt = stmt.where(Pedido.status == status)
    if desde is not None:
        stmt = stmt.where(Pedido.criado_em >= desde)
    return list(db.execute(stmt).unique().scalars())


def expirar_pedidos_vencidos(db: Session) -> int:
    """Marca como EXPIRADO os pedidos que passaram de `expira_em` sem
    conferencia. So muda o status -- nao mexe em estoque (decisao 2).

    Ate existir esta rotina o `expira_em` era decorativo: nenhum pedido
    saia de GERADO, e nao dava pra distinguir venda concretizada de
    carrinho abandonado na camada de metricas."""
    agora = _agora()
    pedidos = list(
        db.execute(
            select(Pedido).where(Pedido.status == StatusPedido.GERADO, Pedido.expira_em < agora)
        ).scalars()
    )
    for pedido in pedidos:
        pedido.status = StatusPedido.EXPIRADO
    if pedidos:
        db.commit()
    return len(pedidos)
