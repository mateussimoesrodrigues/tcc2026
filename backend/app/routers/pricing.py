from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_funcionario
from app.models.funcionario import Funcionario
from app.schemas.preco import MargemDefasadaRead, ReprecificarRequest
from app.schemas.produto import ProdutoRead
from app.services import price_service, product_service
from app.services.exceptions import (
    PrecoPromocionalInvalidoError,
    ProdutoNaoEncontradoError,
)

router = APIRouter(prefix="/precos", tags=["precos"], dependencies=[Depends(get_current_funcionario)])
# Precificacao de tabela (preco normal). Promocao e outra coisa e mora em
# `promotions.py`: la o preco e temporario e nasce de uma sugestao; aqui e
# o preco estrutural do produto, decidido pelo gestor.


def _erro_preco(e: PrecoPromocionalInvalidoError) -> dict:
    """Mesmo envelope de `promotions.py` -- o frontend ja sabe ler `codigo`
    e escolher a mensagem a partir dele."""
    return {"codigo": e.codigo, "mensagem": str(e), "detalhes": e.detalhes}


@router.get("/margem-defasada", response_model=MargemDefasadaRead)
def margem_defasada(
    margem_alvo: float | None = Query(
        default=None,
        gt=0,
        lt=100,
        description="Margem-alvo em percentual sobre o preco. Omitido usa a configurada.",
    ),
    limite: int = 100,
    db: Session = Depends(get_db),
):
    """Produtos cuja margem caiu abaixo do alvo -- normalmente porque o
    custo subiu (entrada de mercadoria) e o preco nao acompanhou."""
    alvo = Decimal(str(margem_alvo)) / Decimal("100") if margem_alvo is not None else None
    return price_service.produtos_com_margem_defasada(db, margem_alvo=alvo, limite=limite)


@router.post("/{produto_id}/reprecificar", response_model=ProdutoRead)
def reprecificar(
    produto_id: int,
    dados: ReprecificarRequest,
    db: Session = Depends(get_db),
    funcionario: Funcionario = Depends(get_current_funcionario),
):
    """Aplica um novo preco de tabela, gravando `historico_preco` com o
    autor. Recusa produto em promocao ativa (409, codigo
    `promocao_ja_ativa`): ver a docstring de `alterar_preco_normal`."""
    try:
        price_service.alterar_preco_normal(
            db, produto_id, dados.preco_novo, alterado_por=funcionario.id
        )
    except ProdutoNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produto nao encontrado")
    except PrecoPromocionalInvalidoError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, _erro_preco(e))

    return product_service.obter_produto(db, produto_id)
