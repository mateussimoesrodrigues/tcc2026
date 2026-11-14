"""Preenche vendas simuladas historicas uma unica vez.

Uso:
    python -m scripts.simular_historico_vendas
    python -m scripts.simular_historico_vendas --dias 15 --incluir-hoje
"""
from __future__ import annotations

import argparse

from app.core.database import SessionLocal
from app.services.daily_sales_service import simular_vendas_historicas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dias", type=int, default=15)
    parser.add_argument("--incluir-hoje", action="store_true")
    parser.add_argument("--semente", type=int, default=2026)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        execucoes = simular_vendas_historicas(
            db,
            dias=args.dias,
            incluir_hoje=args.incluir_hoje,
            semente=args.semente,
        )
        primeiro_dia = execucoes[0].dia
        ultimo_dia = execucoes[-1].dia
        pedidos = sum(execucao.pedidos_criados for execucao in execucoes)
        unidades = sum(execucao.unidades_vendidas for execucao in execucoes)
    finally:
        db.close()

    print(
        f"Periodo: {primeiro_dia} a {ultimo_dia} | "
        f"Pedidos: {pedidos} | Unidades: {unidades}"
    )


if __name__ == "__main__":
    main()
