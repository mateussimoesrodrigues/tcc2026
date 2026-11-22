"""Gatilho externo da simulacao da loja (agendador do Windows, GitHub
Actions, cron...). Nao usa o login de funcionario: um agendador nao tem como
renovar JWT, entao a chamada vai com a chave `SIMULATION_API_KEY` no header
`X-Simulation-Key`. Sem a variavel configurada o endpoint fica desligado.

    curl -X POST "https://SEU-BACKEND/simulacao/executar" -H "X-Simulation-Key: SUA_CHAVE"
"""
import secrets
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.simulacao import ComprasDiaRead, ProdutoDestaqueRead, SimulacaoDiaRead, SimulacaoResposta
from app.services import store_simulation_service as simulacao

router = APIRouter(prefix="/simulacao", tags=["simulacao"])


def exigir_chave_simulacao(
    x_simulation_key: str | None = Header(None, alias="X-Simulation-Key"),
) -> None:
    settings = get_settings()
    if not settings.simulation_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Simulacao desativada: defina SIMULATION_API_KEY no ambiente.",
        )
    if not settings.dados_simulados:
        # Trava de seguranca: com DADOS_SIMULADOS=false o banco guarda a
        # operacao real da loja e nao pode receber vendas inventadas.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Simulacao bloqueada: DADOS_SIMULADOS=false.")
    if x_simulation_key is None or not secrets.compare_digest(
        x_simulation_key.encode(), settings.simulation_api_key.encode()
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chave de simulacao invalida.")


def _destaques(lista) -> list[ProdutoDestaqueRead]:
    return [
        ProdutoDestaqueRead(produto_id=p.id, nome=p.nome, fator_demanda=round(f, 2)) for p, f in lista
    ]


@router.post(
    "/executar",
    response_model=SimulacaoResposta,
    dependencies=[Depends(exigir_chave_simulacao)],
)
def executar(
    dia: date | None = Query(None, description="Ultimo dia a simular (padrao: hoje, fuso de Sao Paulo)."),
    dias: int = Query(1, ge=1, le=31, description="Quantos dias simular, terminando em `dia`."),
    semente: int | None = Query(None, description="Fixa tambem o sorteio do dia (resultado repetivel)."),
    db: Session = Depends(get_db),
):
    """Simula as vendas e as compras de mercadoria do dia.

    Cada dia roda uma unica vez: repetir a chamada nao duplica nada. Agende
    no fim do expediente (ex.: 23h), porque os horarios das vendas se
    espalham pelo dia todo.
    """
    settings = get_settings()
    try:
        resultados = simulacao.simular_periodo(
            db,
            dia_final=dia,
            dias=dias,
            semente=semente if semente is not None else settings.simulation_seed,
            deterministico=semente is not None,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    return SimulacaoResposta(
        resultados=[
            SimulacaoDiaRead(
                dia=r.dia,
                ja_executado=r.ja_executado,
                clima=r.clima,
                fator_movimento=r.fator_movimento,
                pedidos_criados=r.pedidos_criados,
                unidades_vendidas=r.unidades_vendidas,
                receita=r.receita,
                compras=ComprasDiaRead(
                    houve_compra=r.compras.houve_compra,
                    linhas=r.compras.linhas,
                    unidades=r.compras.unidades,
                    valor=r.compras.valor,
                )
                if r.compras
                else None,
                produtos_em_ruptura=r.produtos_em_ruptura,
                produtos_em_alta=_destaques(r.produtos_em_alta),
                produtos_em_baixa=_destaques(r.produtos_em_baixa),
            )
            for r in resultados
        ]
    )
