"""Simulacao diaria de vendas para alimentar o historico de promocoes.

Esta rotina cria os mesmos registros produzidos pelo checkout real (pedido,
item e movimentacao de estoque), mas marca a execucao como simulada. Ela nao
substitui as vendas reais e e desligada por padrao.
"""
from __future__ import annotations

import math
import random
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.estoque import Estoque
from app.models.historico_preco import HistoricoPreco, TipoAlteracaoPreco
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.pedido import Pedido, StatusPedido
from app.models.pedido_item import PedidoItem
from app.models.produto import Produto
from app.models.promocao_sugestao import (
    OrigemSugestao,
    PrioridadeSugestao,
    PromocaoSugestao,
    StatusSugestao,
)
from app.models.simulacao_venda import SimulacaoVendaExecucao
from app.models.sessao_carrinho import SessaoCarrinho, StatusSessaoCarrinho
from app.services.price_service import piso_de_preco, quantizar_preco

FUSO_LOJA = ZoneInfo("America/Sao_Paulo")


def _agora() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _poisson(rng: random.Random, media: float) -> int:
    if media <= 0:
        return 0
    limite = math.exp(-media)
    probabilidade = 1.0
    eventos = 0
    while probabilidade > limite:
        eventos += 1
        probabilidade *= rng.random()
    return eventos - 1


def _demanda_media(produto: Produto, dia: date) -> float:
    """Taxa conservadora, com sazonalidade e resposta ao desconto."""
    media = 0.35
    if produto.preco_normal <= Decimal("10.00"):
        media += 0.35
    elif produto.preco_normal <= Decimal("30.00"):
        media += 0.15
    if dia.weekday() >= 5:
        media *= 1.35
    if dia.day <= 5 or 15 <= dia.day <= 20:
        media *= 1.20
    if produto.promocao_ativa and produto.preco_promocional is not None:
        desconto = (produto.preco_normal - produto.preco_promocional) / produto.preco_normal
        # A simulacao precisa produzir um sinal visivel no painel, sem
        # garantir uma venda artificial: desconto aumenta bastante a taxa e
        # evita que uma janela curta de Poisson fique zerada por acaso.
        media = max(media * (1 + 3.5 * float(max(Decimal("0"), desconto))), 1.0)
    return media


def _numero_pedido(db: Session, dia: date, produto_id: int) -> str:
    """Gera um identificador legivel sem assumir que o id cabe em dois digitos."""
    base = f"S{dia.strftime('%y%m%d')}{produto_id:04d}"[-10:]
    numero = base
    sufixo = 0
    while db.execute(
        select(Pedido.id).where(Pedido.numero_pedido == numero)
    ).scalar_one_or_none() is not None:
        sufixo += 1
        numero = f"{base[:-2]}{sufixo:02d}"[-10:]
    return numero


def simular_promocoes_do_dia(
    db: Session,
    *,
    dia: date | None = None,
    quantidade: int = 2,
    semente: int = 2026,
    ativar_produtos: bool = False,
) -> list[int]:
    """Cria promocoes aprovadas simuladas para alimentar o painel.

    O job diario usa esta rotina antes das vendas para que o desconto altere a
    demanda simulada. O registro e historico de preco seguem o mesmo formato
    das promocoes reais, mas ficam explicitamente marcados como simulacao.
    """
    dia = dia or datetime.now(FUSO_LOJA).date()
    rng = random.Random(semente + dia.toordinal() + 7919)
    candidatos = list(
        db.execute(
            select(Produto)
            .join(Estoque, Estoque.produto_id == Produto.id)
            .where(
                Produto.ativo.is_(True),
                Estoque.quantidade > 0,
                or_(
                    Produto.promocao_ativa.is_(False),
                    Produto.promocao_expira_em <= datetime.combine(dia, time.min),
                ),
            )
            .order_by(Produto.id)
        ).scalars()
    )
    rng.shuffle(candidatos)
    produtos_promocionais: list[int] = []

    for produto in candidatos:
        if len(produtos_promocionais) >= quantidade:
            break
        desconto = Decimal(str(rng.choice((10, 15, 20))))
        preco = quantizar_preco(produto.preco_normal * (1 - desconto / 100))
        piso = piso_de_preco(produto)
        if piso is not None and preco < piso:
            preco = quantizar_preco(piso)
        if preco >= produto.preco_normal:
            continue

        inicio = datetime.combine(dia, time(hour=8))
        fim = inicio + timedelta(days=5)
        ja_registrada = db.execute(
            select(HistoricoPreco.id).where(
                HistoricoPreco.produto_id == produto.id,
                HistoricoPreco.tipo_alteracao == TipoAlteracaoPreco.PROMOCAO_IA_APROVADA,
                HistoricoPreco.criado_em == inicio,
            )
        ).scalar_one_or_none()
        if ja_registrada is not None:
            continue

        sugestao = PromocaoSugestao(
            produto_id=produto.id,
            origem=OrigemSugestao.REGRA_AUTOMATICA,
            sinais_detectados={
                "origem_dados": "simulacao_diaria",
                "motivo": "estoque e demanda simulados",
                "desconto_testado": float(desconto),
            },
            percentual_desconto_sugerido=desconto,
            preco_sugerido=preco,
            justificativa_ia=(
                "[simulacao diaria] Desconto aplicado para testar a resposta "
                "da demanda e preencher a analise de efeito das promocoes."
            ),
            prioridade=PrioridadeSugestao.MEDIA,
            modelo_ia_usado="simulacao_demanda",
            status=StatusSugestao.APROVADA,
            criado_em=inicio - timedelta(hours=2),
            avaliada_em=inicio,
        )
        db.add(sugestao)
        db.flush()
        db.add(
            HistoricoPreco(
                produto_id=produto.id,
                preco_anterior=produto.preco_normal,
                preco_novo=preco,
                tipo_alteracao=TipoAlteracaoPreco.PROMOCAO_IA_APROVADA,
                sugestao_id=sugestao.id,
                criado_em=inicio,
            )
        )
        db.add(
            HistoricoPreco(
                produto_id=produto.id,
                preco_anterior=preco,
                preco_novo=produto.preco_normal,
                tipo_alteracao=TipoAlteracaoPreco.FIM_PROMOCAO,
                sugestao_id=sugestao.id,
                criado_em=fim,
            )
        )
        if ativar_produtos:
            produto.preco_promocional = preco
            produto.promocao_ativa = True
            produto.promocao_expira_em = fim
        produtos_promocionais.append(produto.id)

    if produtos_promocionais:
        db.commit()
    return produtos_promocionais


def simular_vendas_do_dia(
    db: Session, *, dia: date | None = None, semente: int = 2026
) -> SimulacaoVendaExecucao:
    """Gera vendas do dia uma unica vez e devolve o registro da execucao."""
    dia = dia or datetime.now(FUSO_LOJA).date()
    existente = db.execute(
        select(SimulacaoVendaExecucao).where(SimulacaoVendaExecucao.dia == dia)
    ).scalar_one_or_none()
    if existente is not None:
        return existente

    rng = random.Random(semente + dia.toordinal())
    produtos = list(
        db.execute(
            select(Produto)
            .join(Estoque, Estoque.produto_id == Produto.id)
            .where(Produto.ativo.is_(True), Estoque.quantidade > 0)
            .order_by(Produto.id)
        ).scalars()
    )
    pedidos_criados = 0
    unidades_vendidas = 0
    inicio_dia = datetime.combine(dia, time.min)

    for produto in produtos:
        estoque = db.get(Estoque, produto.id)
        if estoque is None or estoque.quantidade <= 0:
            continue
        quantidade = min(_poisson(rng, _demanda_media(produto, dia)), estoque.quantidade)
        if quantidade <= 0:
            continue

        quando = inicio_dia + timedelta(
            hours=rng.randint(8, 20), minutes=rng.randint(0, 59)
        )
        preco = produto.preco_vigente
        sessao = SessaoCarrinho(
            id=str(uuid.uuid4()),
            status=StatusSessaoCarrinho.FINALIZADA,
            criado_em=quando,
            atualizado_em=quando,
            expira_em=quando + timedelta(hours=24),
        )
        pedido = Pedido(
            numero_pedido=_numero_pedido(db, dia, produto.id),
            sessao_carrinho_id=sessao.id,
            valor_total=preco * quantidade,
            status=StatusPedido.CONFERIDO_NO_CAIXA,
            criado_em=quando,
            expira_em=quando + timedelta(minutes=20),
            conferido_em=quando,
        )
        db.add(sessao)
        # O pedido referencia a sessao por chave estrangeira; garanta que a
        # sessao exista antes de inserir o pedido no PostgreSQL.
        db.flush()
        db.add(pedido)
        db.flush()
        db.add(
            PedidoItem(
                pedido_id=pedido.id,
                produto_id=produto.id,
                nome_produto_snapshot=produto.nome,
                preco_unitario_snapshot=preco,
                quantidade=quantidade,
                subtotal=preco * quantidade,
            )
        )
        db.add(
            MovimentacaoEstoque(
                produto_id=produto.id,
                tipo=TipoMovimentacao.SAIDA_VENDA,
                quantidade=quantidade,
                pedido_id=pedido.id,
                criado_em=quando,
            )
        )
        estoque.quantidade -= quantidade
        pedidos_criados += 1
        unidades_vendidas += quantidade

    execucao = SimulacaoVendaExecucao(
        dia=dia,
        pedidos_criados=pedidos_criados,
        unidades_vendidas=unidades_vendidas,
        executado_em=_agora(),
    )
    db.add(execucao)
    db.commit()
    db.refresh(execucao)
    return execucao


def simular_vendas_historicas(
    db: Session, *, dias: int = 15, incluir_hoje: bool = False, semente: int = 2026
) -> list[SimulacaoVendaExecucao]:
    """Preenche um historico pontual sem criar um job recorrente.

    Cada data e processada pela rotina idempotente, portanto a operacao pode
    ser repetida sem duplicar pedidos ou movimentacoes.
    """
    if dias <= 0:
        raise ValueError("dias deve ser maior que zero")

    hoje = datetime.now(FUSO_LOJA).date()
    ultimo_dia = hoje if incluir_hoje else hoje - timedelta(days=1)
    primeiro_dia = ultimo_dia - timedelta(days=dias - 1)
    ultimo_inicio_promocao = ultimo_dia - timedelta(days=4)

    execucoes = []
    for deslocamento in range(dias):
        data = primeiro_dia + timedelta(days=deslocamento)
        if data <= ultimo_inicio_promocao:
            simular_promocoes_do_dia(
                db, dia=data, quantidade=2, semente=semente, ativar_produtos=True
            )
        execucoes.append(simular_vendas_do_dia(db, dia=data, semente=semente))
    return execucoes
