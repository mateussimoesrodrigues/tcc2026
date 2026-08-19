from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.checkout import EstoqueInsuficienteRead, PedidoRead
from app.services import checkout_service
from app.services.exceptions import (
    CarrinhoVazioError,
    EstoqueInsuficienteError,
    SessaoCarrinhoInvalidaError,
)

router = APIRouter(prefix="/checkout", tags=["checkout"])


def _sessao_id(x_cart_session: str = Header(..., alias="X-Cart-Session")) -> str:
    return x_cart_session


@router.post(
    "",
    response_model=PedidoRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": EstoqueInsuficienteRead}},
)
def finalizar_checkout(sessao_id: str = Depends(_sessao_id), db: Session = Depends(get_db)):
    """Finaliza o pedido sem pagamento: decrementa o estoque, grava o
    historico e devolve o numero curto de conferencia para o caixa fisico."""
    try:
        pedido = checkout_service.finalizar(db, sessao_id)
    except SessaoCarrinhoInvalidaError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Sessao de carrinho invalida, expirada ou ja finalizada"
        )
    except CarrinhoVazioError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Carrinho vazio")
    except EstoqueInsuficienteError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            EstoqueInsuficienteRead(itens=e.itens).model_dump(mode="json"),
        )

    return PedidoRead(
        numero_pedido=pedido.numero_pedido,
        valor_total=pedido.valor_total,
        expira_em=pedido.expira_em,
    )
