from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_funcionario
from app.models.funcionario import Funcionario
from app.models.pedido import StatusPedido
from app.schemas.pedido import ConferirPedidoResposta, PedidoDetalheRead, PedidoResumoRead
from app.services import order_service
from app.services.exceptions import PedidoJaConferidoError, PedidoNaoEncontradoError

router = APIRouter(prefix="/pedidos", tags=["pedidos"], dependencies=[Depends(get_current_funcionario)])


def _agora() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("", response_model=list[PedidoResumoRead])
def listar(
    status_filtro: StatusPedido | None = None,
    limite: int = order_service.LIMITE_LISTAGEM_PADRAO,
    db: Session = Depends(get_db),
):
    pedidos = order_service.listar_pedidos(db, status=status_filtro, limite=limite)
    return [PedidoResumoRead.de_model(p) for p in pedidos]


@router.post("/expirar-agora")
def expirar_agora(db: Session = Depends(get_db)):
    """Marca como expirados os pedidos que passaram do prazo sem conferencia,
    sem esperar o job periodico. Nao mexe em estoque -- ver o docstring de
    `services/order_service`."""
    return {"pedidos_expirados": order_service.expirar_pedidos_vencidos(db)}


@router.get("/{numero}", response_model=PedidoDetalheRead)
def buscar(numero: str, db: Session = Depends(get_db)):
    """Consulta pelo numero de 6 digitos que o cliente leva ao caixa."""
    try:
        pedido = order_service.buscar_por_numero(db, numero)
    except PedidoNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido nao encontrado")
    return PedidoDetalheRead.de_model(
        pedido, agora=_agora(), conferido_por_nome=order_service.nome_do_conferente(db, pedido)
    )


@router.post("/{numero}/conferir", response_model=ConferirPedidoResposta)
def conferir(
    numero: str,
    db: Session = Depends(get_db),
    funcionario: Funcionario = Depends(get_current_funcionario),
):
    """Confirma no caixa que os itens do pedido foram conferidos. E o evento
    que marca a venda como concretizada -- a camada de metricas usa ele pra
    separar venda de carrinho abandonado."""
    try:
        pedido, estava_expirado = order_service.conferir(db, numero, funcionario.id)
    except PedidoNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido nao encontrado")
    except PedidoJaConferidoError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "codigo": "pedido_ja_conferido",
                "mensagem": "Este pedido ja foi conferido no caixa.",
                "detalhes": {
                    "conferido_em": e.conferido_em.isoformat() if e.conferido_em else None,
                    "conferido_por_nome": e.conferido_por_nome,
                },
            },
        )
    return ConferirPedidoResposta(
        pedido=PedidoDetalheRead.de_model(
            pedido, agora=_agora(), conferido_por_nome=funcionario.nome
        ),
        estava_expirado=estava_expirado,
    )
