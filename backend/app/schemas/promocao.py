from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.promocao_sugestao import OrigemSugestao, PrioridadeSugestao, StatusSugestao


class SugestaoRead(BaseModel):
    id: int
    produto_id: int
    produto_nome: str
    produto_marca: str | None
    produto_tamanho: str | None
    preco_normal: Decimal

    origem: OrigemSugestao
    sinais_detectados: dict
    percentual_desconto_sugerido: Decimal
    preco_sugerido: Decimal
    justificativa_ia: str
    prioridade: PrioridadeSugestao
    modelo_ia_usado: str

    status: StatusSugestao
    criado_em: datetime
    avaliada_em: datetime | None
    avaliada_por: int | None
    observacao_funcionario: str | None

    @classmethod
    def de_model(cls, sugestao) -> "SugestaoRead":
        return cls(
            id=sugestao.id,
            produto_id=sugestao.produto_id,
            produto_nome=sugestao.produto.nome,
            produto_marca=sugestao.produto.marca,
            produto_tamanho=sugestao.produto.tamanho,
            preco_normal=sugestao.produto.preco_normal,
            origem=sugestao.origem,
            sinais_detectados=sugestao.sinais_detectados,
            percentual_desconto_sugerido=sugestao.percentual_desconto_sugerido,
            preco_sugerido=sugestao.preco_sugerido,
            justificativa_ia=sugestao.justificativa_ia,
            prioridade=sugestao.prioridade,
            modelo_ia_usado=sugestao.modelo_ia_usado,
            status=sugestao.status,
            criado_em=sugestao.criado_em,
            avaliada_em=sugestao.avaliada_em,
            avaliada_por=sugestao.avaliada_por,
            observacao_funcionario=sugestao.observacao_funcionario,
        )


class AprovarSugestaoRequest(BaseModel):
    observacao: str | None = None
    dias_validade: int | None = None


class RejeitarSugestaoRequest(BaseModel):
    observacao: str | None = None


class FalhaGeracao(BaseModel):
    produto_id: int
    nome: str
    motivo: str


class GerarSugestoesResposta(BaseModel):
    candidatos_avaliados: int
    sugestoes_criadas: list[SugestaoRead]
    falhas: list[FalhaGeracao]
