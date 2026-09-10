from decimal import Decimal

from pydantic import BaseModel, Field


class MargemDefasadaItemRead(BaseModel):
    """Uma linha da tela de reprecificacao.

    `margem_atual` e `margem_resultante` sao fracoes (0.28 = 28%) sobre o
    **preco**, nao markup sobre o custo -- mesma base de
    `ai/rules.SinaisProduto.margem`, para o numero bater com o que a tela de
    promocoes ja mostra.
    """

    produto_id: int
    nome: str
    marca: str | None
    tamanho: str | None
    custo: Decimal
    preco_normal: Decimal
    margem_atual: float
    preco_sugerido: Decimal
    margem_resultante: float
    promocao_ativa: bool


class MargemDefasadaRead(BaseModel):
    margem_alvo: float
    itens: list[MargemDefasadaItemRead]
    # Produtos ativos sem custo cadastrado: ficam fora da lista porque a
    # margem e incalculavel. Contados aqui para a tela poder avisar que o
    # diagnostico esta incompleto -- e o que a entrada de mercadoria resolve.
    produtos_sem_custo: int
    total_abaixo_do_alvo: int


class ReprecificarRequest(BaseModel):
    preco_novo: Decimal = Field(gt=0)
