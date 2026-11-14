"""Recria somente o historico explicitamente simulado de vendas/promocoes.

Uso:
    python -m scripts.recriar_historico_simulado --dias 15
"""
from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta

from sqlalchemy import delete, func, select

from app.core.database import SessionLocal
from app.models.historico_preco import HistoricoPreco
from app.models.movimentacao_estoque import MovimentacaoEstoque
from app.models.pedido import Pedido
from app.models.pedido_item import PedidoItem
from app.models.produto import Produto
from app.models.promocao_sugestao import PromocaoSugestao
from app.models.simulacao_venda import SimulacaoVendaExecucao
from app.models.sessao_carrinho import SessaoCarrinho
from app.models.estoque import Estoque
from app.services.daily_sales_service import FUSO_LOJA, simular_vendas_historicas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dias", type=int, default=15)
    args = parser.parse_args()
    if args.dias <= 0:
        raise SystemExit("--dias deve ser maior que zero")

    hoje = datetime.now(FUSO_LOJA).date()
    inicio = datetime.combine(hoje - timedelta(days=args.dias - 1), time.min)
    fim = datetime.combine(hoje + timedelta(days=1), time.min)

    db = SessionLocal()
    try:
        sugestoes = list(
            db.execute(
                select(PromocaoSugestao).where(
                    PromocaoSugestao.modelo_ia_usado == "simulacao_demanda"
                )
            ).scalars()
        )
        produto_ids = {sugestao.produto_id for sugestao in sugestoes}
        sugestao_ids = [sugestao.id for sugestao in sugestoes]

        if sugestao_ids:
            db.execute(
                delete(HistoricoPreco).where(
                    HistoricoPreco.sugestao_id.in_(sugestao_ids)
                )
            )
            db.execute(
                delete(PromocaoSugestao).where(
                    PromocaoSugestao.id.in_(sugestao_ids)
                )
            )

        pedidos = list(
            db.execute(
                select(Pedido).where(
                    Pedido.numero_pedido.like("S%"),
                    Pedido.criado_em >= inicio,
                    Pedido.criado_em < fim,
                )
            ).scalars()
        )
        pedido_ids = [pedido.id for pedido in pedidos]
        sessao_ids = [pedido.sessao_carrinho_id for pedido in pedidos]
        if pedido_ids:
            unidades_por_produto = dict(
                db.execute(
                    select(PedidoItem.produto_id, func.sum(PedidoItem.quantidade))
                    .where(PedidoItem.pedido_id.in_(pedido_ids))
                    .group_by(PedidoItem.produto_id)
                ).all()
            )
            for produto_id, unidades in unidades_por_produto.items():
                estoque = db.get(Estoque, produto_id)
                if estoque is not None:
                    estoque.quantidade += int(unidades)
            db.execute(delete(MovimentacaoEstoque).where(MovimentacaoEstoque.pedido_id.in_(pedido_ids)))
            db.execute(delete(PedidoItem).where(PedidoItem.pedido_id.in_(pedido_ids)))
            db.execute(delete(Pedido).where(Pedido.id.in_(pedido_ids)))
            db.execute(delete(SessaoCarrinho).where(SessaoCarrinho.id.in_(sessao_ids)))

        db.execute(
            delete(SimulacaoVendaExecucao).where(
                SimulacaoVendaExecucao.dia >= inicio.date(),
                SimulacaoVendaExecucao.dia < fim.date(),
            )
        )
        if produto_ids:
            for produto in db.execute(
                select(Produto).where(Produto.id.in_(produto_ids))
            ).scalars():
                produto.promocao_ativa = False
                produto.preco_promocional = None
                produto.promocao_expira_em = None
        db.commit()
        execucoes = simular_vendas_historicas(
            db, dias=args.dias, incluir_hoje=True
        )
        print(
            f"Periodo recriado: {execucoes[0].dia} a {execucoes[-1].dia} | "
            f"Pedidos: {sum(e.pedidos_criados for e in execucoes)} | "
            f"Unidades: {sum(e.unidades_vendidas for e in execucoes)}"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
