"""Simulacao do dia a dia da loja: vendas em cestas de compra e compras de
reposicao de mercadoria.

Diferente de `daily_sales_service` (uma venda por produto, ritmo constante e
nenhuma compra), aqui cada dia e diferente e o estoque tem vida propria:

* Vendas -- o ritmo de cada produto parte do historico real do banco (media
  dos ultimos 60 dias misturada com a media de sempre, o que impede o ritmo
  de derivar para zero ou explodir) e e multiplicado por:
    - dia da semana, dia de pagamento e uma onda lenta de ~5 semanas
      (periodos de alta e de baixa da loja inteira);
    - sorteio do dia: dias fracos (chuva, feriado) e fortes (evento);
    - "momento" de cada produto: ondas proprias e blocos de ~3 semanas em que
      o produto encalha (fica ~25% do normal) ou bomba (~2x). Os encalhados
      sao exatamente as oportunidades de promocao que a IA deve enxergar;
    - desconto, quando o produto esta em promocao;
    - ruido gama-Poisson (dois dias iguais nunca vendem o mesmo numero).
  As unidades viram cestas de 1 a 6 produtos com horario realista (picos
  no almoco e no fim da tarde).
* Compras -- o comprador usa so o historico (nao sabe que um produto vai
  encalhar). Compra em dias de visita de fornecedor (terca e quinta quase
  sempre), repoe quando a cobertura de estoque cai abaixo de 6-14 dias, as
  vezes esquece ou o fornecedor falha (ruptura) e as vezes compra demais
  (capital parado). O custo varia a cada compra e o custo medio do produto
  e reancorado pela media ponderada, como na entrada real.

Tudo fica marcado como simulacao (`observacao` das entradas, `origem` da
execucao) e cada dia e executado uma unica vez (`simulacao_venda_execucao`).
"""
from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.estoque import Estoque
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.pedido import Pedido, StatusPedido
from app.models.pedido_item import PedidoItem
from app.models.produto import Produto
from app.models.sessao_carrinho import SessaoCarrinho, StatusSessaoCarrinho
from app.models.simulacao_venda import SimulacaoVendaExecucao
from app.services import price_service, stock_service

FUSO_LOJA = ZoneInfo("America/Sao_Paulo")
ORIGEM = "simulacao_loja"

JANELA_RITMO_DIAS = 60
BLOCO_MOMENTO_DIAS = 21

# Segunda=0 ... domingo=6.
FATOR_SEMANA = {0: 0.85, 1: 0.90, 2: 0.95, 3: 1.00, 4: 1.20, 5: 1.45, 6: 1.10}
PROB_VISITA_FORNECEDOR = {0: 0.40, 1: 0.95, 2: 0.40, 3: 0.95, 4: 0.50, 5: 0.10, 6: 0.0}
HORAS_VENDA = list(range(8, 21))
PESOS_HORA = [4, 6, 8, 10, 12, 10, 7, 8, 10, 12, 11, 8, 4]


def _agora() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass
class ResumoCompras:
    houve_compra: bool = False
    linhas: int = 0
    unidades: int = 0
    valor: Decimal = Decimal("0.00")


@dataclass
class ResultadoDia:
    dia: date
    ja_executado: bool = False
    clima: str | None = None
    fator_movimento: float | None = None
    pedidos_criados: int = 0
    unidades_vendidas: int = 0
    receita: Decimal | None = None
    compras: ResumoCompras | None = None
    produtos_em_ruptura: int | None = None
    produtos_em_alta: list[tuple[Produto, float]] = field(default_factory=list)
    produtos_em_baixa: list[tuple[Produto, float]] = field(default_factory=list)


# --- Fatores de demanda ---------------------------------------------------


def _fator_loja(dia: date, rng: random.Random, semente: int) -> tuple[float, str]:
    """Quanto a loja inteira vende hoje em relacao ao normal, e um rotulo."""
    base = FATOR_SEMANA[dia.weekday()]
    fator = base
    if 5 <= dia.day <= 10 or dia.day in (20, 21):
        fator *= 1.12  # dias de pagamento
    # Onda lenta (~5 semanas): periodos de alta e de baixa que duram dias.
    fase = (semente % 97) / 97 * 2 * math.pi
    fator *= 1 + 0.22 * math.sin(2 * math.pi * dia.toordinal() / 37 + fase)
    fator *= rng.lognormvariate(0, 0.18)
    sorteio = rng.random()
    if sorteio < 0.08:
        fator *= rng.uniform(0.55, 0.75)  # dia ruim (chuva, feriado, rua vazia)
    elif sorteio > 0.95:
        fator *= rng.uniform(1.35, 1.70)  # evento, movimento fora do comum
    relativo = fator / base
    if relativo < 0.80:
        rotulo = "movimento fraco"
    elif relativo > 1.25:
        rotulo = "movimento forte"
    else:
        rotulo = "movimento normal"
    return fator, rotulo


def _nivel_bloco(produto_id: int, bloco: int, semente: int) -> float:
    """Momento do produto num bloco de ~3 semanas: normal, encalhado ou em alta.
    Deterministico (mesma semente, mesmo bloco, mesmo resultado) pra o
    encalhe durar semanas em vez de piscar de um dia pro outro."""
    r = random.Random(f"{semente}:{produto_id}:{bloco}")
    sorteio = r.random()
    if sorteio < 0.12:
        return r.uniform(0.15, 0.35)
    if sorteio > 0.92:
        return r.uniform(1.8, 2.6)
    return 1.0


def _fator_produto(produto_id: int, dia: date, semente: int) -> float:
    ordinal = dia.toordinal()
    bloco, posicao = divmod(ordinal, BLOCO_MOMENTO_DIAS)
    # Interpolacao suave entre blocos: o encalhe chega e sai gradualmente.
    t = posicao / BLOCO_MOMENTO_DIAS
    t = t * t * (3 - 2 * t)
    nivel = (1 - t) * _nivel_bloco(produto_id, bloco, semente) + t * _nivel_bloco(
        produto_id, bloco + 1, semente
    )
    periodo = 12 + (produto_id * 7) % 34
    fase = (produto_id * 13 % 100) / 100 * 2 * math.pi
    onda = math.exp(0.35 * math.sin(2 * math.pi * ordinal / periodo + fase))
    return nivel * onda


def _poisson(rng: random.Random, media: float) -> int:
    if media <= 0:
        return 0
    if media > 40:  # aproximacao normal: evita laco longo e underflow
        return max(0, round(rng.gauss(media, math.sqrt(media))))
    limite = math.exp(-media)
    p, k = 1.0, 0
    while p > limite:
        k += 1
        p *= rng.random()
    return k - 1


def _ritmo_historico(db: Session, ate: datetime) -> dict[int, float]:
    """Unidades vendidas por dia de cada produto, lidas do razao de estoque."""
    inicio = ate - timedelta(days=JANELA_RITMO_DIAS)
    recentes = {
        pid: float(total or 0)
        for pid, total in db.execute(
            select(MovimentacaoEstoque.produto_id, func.sum(MovimentacaoEstoque.quantidade))
            .where(
                MovimentacaoEstoque.tipo == TipoMovimentacao.SAIDA_VENDA,
                MovimentacaoEstoque.criado_em >= inicio,
                MovimentacaoEstoque.criado_em < ate,
            )
            .group_by(MovimentacaoEstoque.produto_id)
        ).all()
    }
    vida: dict[int, float] = {}
    for pid, total, primeira, ultima in db.execute(
        select(
            MovimentacaoEstoque.produto_id,
            func.sum(MovimentacaoEstoque.quantidade),
            func.min(MovimentacaoEstoque.criado_em),
            func.max(MovimentacaoEstoque.criado_em),
        )
        .where(
            MovimentacaoEstoque.tipo == TipoMovimentacao.SAIDA_VENDA,
            MovimentacaoEstoque.criado_em < ate,
        )
        .group_by(MovimentacaoEstoque.produto_id)
    ).all():
        dias = max((ultima - primeira).days + 1, 30)
        vida[pid] = float(total or 0) / dias

    ritmo: dict[int, float] = {}
    for pid in set(recentes) | set(vida):
        recente = recentes.get(pid, 0.0) / JANELA_RITMO_DIAS
        # Mistura com a media de sempre: o ritmo volta pro normal do produto
        # em vez de se auto-reforcar a cada dia simulado.
        ritmo[pid] = min(0.5 * recente + 0.5 * vida.get(pid, recente), 300.0)
    return ritmo


def _ritmo_padrao(produto: Produto) -> float:
    """Produto sem historico nenhum: ritmo modesto, maior se for barato."""
    if produto.preco_normal <= Decimal("10"):
        return 0.6
    if produto.preco_normal <= Decimal("30"):
        return 0.4
    return 0.25


def _preco_no_dia(produto: Produto, inicio_dia: datetime) -> Decimal:
    """Preco vigente, ignorando promocao que ja tinha vencido na data simulada."""
    if (
        produto.promocao_ativa
        and produto.preco_promocional is not None
        and (produto.promocao_expira_em is None or produto.promocao_expira_em >= inicio_dia)
    ):
        return produto.preco_promocional
    return produto.preco_normal


# --- Compras --------------------------------------------------------------


def _tamanho_lote(produto: Produto) -> int:
    """Itens baratos vem em caixa fechada; os caros, avulsos."""
    if produto.preco_normal <= Decimal("15"):
        return 6
    if produto.preco_normal <= Decimal("40"):
        return 3
    return 1


def _comprar(
    db: Session,
    rng: random.Random,
    dia: date,
    itens: list[tuple[Produto, Estoque]],
    ritmo: dict[int, float],
) -> ResumoCompras:
    resumo = ResumoCompras()
    visita = rng.random() < PROB_VISITA_FORNECEDOR[dia.weekday()]
    nota = rng.randint(10000, 99999)
    inicio = datetime.combine(dia, time(hour=8))

    for produto, estoque in itens:
        giro = ritmo.get(produto.id) or _ritmo_padrao(produto)
        # Compra de emergencia: produto zerado que vende, mesmo fora de visita.
        urgente = estoque.quantidade <= 0 and giro >= 1 and dia.weekday() != 6 and rng.random() < 0.5
        if not (visita or urgente):
            continue

        cobertura = estoque.quantidade / max(giro, 0.05)
        if cobertura >= rng.uniform(6, 14):
            continue
        if not urgente and rng.random() < 0.12:
            continue  # esqueceu o item no pedido, ou o fornecedor nao tinha

        quantidade = giro * rng.uniform(14, 32) - max(estoque.quantidade, 0)
        if rng.random() < 0.06:
            quantidade *= rng.uniform(2.2, 4.0)  # compra exagerada: capital parado
        lote = _tamanho_lote(produto)
        quantidade = min(math.ceil(quantidade / lote) * lote, 6000)
        if quantidade <= 0:
            continue

        custo_ref = produto.custo if produto.custo is not None else produto.preco_normal * Decimal("0.55")
        custo_unitario = max(
            price_service.quantizar_preco(custo_ref * Decimal(str(round(rng.uniform(0.95, 1.06), 4)))),
            Decimal("0.01"),
        )
        quando = inicio + timedelta(minutes=rng.randint(0, 150), seconds=rng.randint(0, 59))

        produto.custo = stock_service.custo_medio_ponderado(
            produto.custo, max(estoque.quantidade, 0), custo_unitario, quantidade
        )
        estoque.quantidade += quantidade
        db.add(
            MovimentacaoEstoque(
                produto_id=produto.id,
                tipo=TipoMovimentacao.ENTRADA,
                quantidade=quantidade,
                custo_unitario=custo_unitario,
                observacao=f"[simulacao] Recebimento de fornecedor NF {nota}"
                + (" (reposicao urgente)" if urgente and not visita else ""),
                criado_em=quando,
            )
        )
        resumo.houve_compra = True
        resumo.linhas += 1
        resumo.unidades += quantidade
        resumo.valor += price_service.quantizar_preco(Decimal(quantidade) * custo_unitario)
    return resumo


# --- Vendas ---------------------------------------------------------------


def _linhas_de_venda(rng: random.Random, produto: Produto, unidades: int) -> list[tuple[Produto, int]]:
    """Quebra as unidades vendidas em compras de clientes diferentes."""
    if produto.preco_normal > Decimal("60"):
        maximo = 1
    elif produto.preco_normal > Decimal("25"):
        maximo = 2
    elif produto.preco_normal > Decimal("10"):
        maximo = 4
    else:
        maximo = 6
    linhas, restante = [], unidades
    while restante > 0:
        q = min(rng.randint(1, maximo), restante)
        linhas.append((produto, q))
        restante -= q
    return linhas


def _montar_cestas(
    rng: random.Random, linhas: list[tuple[Produto, int]]
) -> list[dict[int, tuple[Produto, int]]]:
    rng.shuffle(linhas)
    cestas: list[dict[int, tuple[Produto, int]]] = []
    i = 0
    while i < len(linhas):
        tamanho = 1
        while tamanho < 6 and rng.random() < 0.55:
            tamanho += 1
        cesta: dict[int, tuple[Produto, int]] = {}
        for produto, q in linhas[i : i + tamanho]:
            anterior = cesta.get(produto.id, (produto, 0))[1]
            cesta[produto.id] = (produto, anterior + q)
        cestas.append(cesta)
        i += tamanho
    return cestas


def _numeros_usados(db: Session, prefixo: str) -> set[str]:
    return set(
        db.execute(select(Pedido.numero_pedido).where(Pedido.numero_pedido.like(f"{prefixo}%"))).scalars()
    )


def _vender(
    db: Session,
    rng: random.Random,
    dia: date,
    itens: list[tuple[Produto, Estoque]],
    ritmo: dict[int, float],
    fator_loja: float,
    semente: int,
) -> tuple[int, int, Decimal, list[tuple[Produto, float]]]:
    inicio_dia = datetime.combine(dia, time.min)
    linhas: list[tuple[Produto, int]] = []
    fatores: list[tuple[Produto, float]] = []

    for produto, estoque in itens:
        giro = ritmo.get(produto.id) or _ritmo_padrao(produto)
        fator = _fator_produto(produto.id, dia, semente)
        fatores.append((produto, fator))
        if estoque.quantidade <= 0:
            continue

        media = giro * fator_loja * fator
        preco_vigente = _preco_no_dia(produto, inicio_dia)
        if preco_vigente < produto.preco_normal:
            desconto = float((produto.preco_normal - preco_vigente) / produto.preco_normal)
            media *= 1 + rng.uniform(1.5, 4.0) * desconto
        media *= rng.gammavariate(3, 1 / 3)  # dias parecidos nao vendem igual
        unidades = min(_poisson(rng, min(media, 600.0)), estoque.quantidade)
        if unidades > 0:
            linhas.extend(_linhas_de_venda(rng, produto, unidades))
            estoque.quantidade -= unidades

    if not linhas:
        return 0, 0, Decimal("0.00"), fatores

    cestas = _montar_cestas(rng, linhas)
    horarios = sorted(
        inicio_dia
        + timedelta(
            hours=rng.choices(HORAS_VENDA, weights=PESOS_HORA)[0],
            minutes=rng.randint(0, 59),
            seconds=rng.randint(0, 59),
        )
        for _ in cestas
    )
    prefixo = f"S{dia:%y}{dia.timetuple().tm_yday:03d}"
    usados = _numeros_usados(db, prefixo)
    if len(cestas) > 9999:
        raise ValueError("Mais de 9999 pedidos simulados num dia: reduza o catalogo ou o ritmo.")

    sessoes, pedidos, pedidos_cestas = [], [], []
    sequencia = 0
    for cesta, quando in zip(cestas, horarios):
        sequencia += 1
        numero = f"{prefixo}{sequencia:04d}"
        while numero in usados:
            sequencia += 1
            numero = f"{prefixo}{sequencia:04d}"
        sessao = SessaoCarrinho(
            id=str(uuid.uuid4()),
            status=StatusSessaoCarrinho.FINALIZADA,
            criado_em=quando,
            atualizado_em=quando,
            expira_em=quando + timedelta(hours=24),
        )
        total = sum(
            (_preco_no_dia(p, inicio_dia) * q for p, q in cesta.values()), Decimal("0.00")
        )
        sessoes.append(sessao)
        pedidos.append(
            Pedido(
                numero_pedido=numero,
                sessao_carrinho_id=sessao.id,
                valor_total=total,
                status=StatusPedido.CONFERIDO_NO_CAIXA,
                criado_em=quando,
                expira_em=quando + timedelta(minutes=20),
                conferido_em=quando,
            )
        )
        pedidos_cestas.append((cesta, quando))

    # Em etapas porque o pedido referencia a sessao, e os itens, o pedido.
    db.add_all(sessoes)
    db.flush()
    db.add_all(pedidos)
    db.flush()

    unidades_total, receita = 0, Decimal("0.00")
    for pedido, (cesta, quando) in zip(pedidos, pedidos_cestas):
        receita += pedido.valor_total
        for produto, q in cesta.values():
            preco = _preco_no_dia(produto, inicio_dia)
            unidades_total += q
            db.add(
                PedidoItem(
                    pedido_id=pedido.id,
                    produto_id=produto.id,
                    nome_produto_snapshot=produto.nome,
                    preco_unitario_snapshot=preco,
                    quantidade=q,
                    subtotal=preco * q,
                )
            )
            db.add(
                MovimentacaoEstoque(
                    produto_id=produto.id,
                    tipo=TipoMovimentacao.SAIDA_VENDA,
                    quantidade=q,
                    pedido_id=pedido.id,
                    criado_em=quando,
                )
            )
    return len(pedidos), unidades_total, receita, fatores


# --- Orquestracao ---------------------------------------------------------


def _resultado_existente(existente: SimulacaoVendaExecucao) -> ResultadoDia:
    return ResultadoDia(
        dia=existente.dia,
        ja_executado=True,
        pedidos_criados=existente.pedidos_criados,
        unidades_vendidas=existente.unidades_vendidas,
    )


def simular_dia(db: Session, dia: date, *, semente: int, deterministico: bool) -> ResultadoDia:
    """Simula compras (manha) e vendas (dia todo) de `dia`, uma vez so.

    `semente` fixa a estrutura (momento dos produtos, onda da loja). O sorteio
    do dia e aleatorio de verdade, a menos que `deterministico` (testes).
    """
    existente = db.execute(
        select(SimulacaoVendaExecucao).where(SimulacaoVendaExecucao.dia == dia)
    ).scalar_one_or_none()
    if existente is not None:
        return _resultado_existente(existente)

    rng = random.Random(semente + dia.toordinal()) if deterministico else random.Random()
    inicio = datetime.combine(dia, time.min)

    itens = list(
        db.execute(
            select(Produto, Estoque)
            .join(Estoque, Estoque.produto_id == Produto.id)
            .where(Produto.ativo.is_(True))
            .order_by(Produto.id)
        ).all()
    )
    ritmo = _ritmo_historico(db, inicio)

    compras = _comprar(db, rng, dia, itens, ritmo)
    fator_loja, clima = _fator_loja(dia, rng, semente)
    pedidos, unidades, receita, fatores = _vender(db, rng, dia, itens, ritmo, fator_loja, semente)

    em_ruptura = sum(
        1 for produto, estoque in itens if estoque.quantidade <= 0 and (ritmo.get(produto.id) or 0) >= 0.5
    )
    db.add(
        SimulacaoVendaExecucao(
            dia=dia,
            pedidos_criados=pedidos,
            unidades_vendidas=unidades,
            executado_em=_agora(),
            origem=ORIGEM,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Duas chamadas simultaneas para o mesmo dia: a outra venceu.
        db.rollback()
        existente = db.execute(
            select(SimulacaoVendaExecucao).where(SimulacaoVendaExecucao.dia == dia)
        ).scalar_one()
        return _resultado_existente(existente)

    ordenados = sorted(fatores, key=lambda x: x[1])
    return ResultadoDia(
        dia=dia,
        clima=clima,
        fator_movimento=round(fator_loja, 2),
        pedidos_criados=pedidos,
        unidades_vendidas=unidades,
        receita=receita,
        compras=compras,
        produtos_em_ruptura=em_ruptura,
        produtos_em_alta=[x for x in reversed(ordenados[-3:]) if x[1] > 1.5],
        produtos_em_baixa=[x for x in ordenados[:3] if x[1] < 0.5],
    )


def simular_periodo(
    db: Session,
    *,
    dia_final: date | None = None,
    dias: int = 1,
    semente: int = 2026,
    deterministico: bool = False,
) -> list[ResultadoDia]:
    """Simula `dias` dias terminando em `dia_final` (padrao: hoje, no fuso da
    loja). Dias ja simulados sao pulados, entao repetir a chamada e seguro."""
    hoje = datetime.now(FUSO_LOJA).date()
    dia_final = dia_final or hoje
    if dia_final > hoje:
        raise ValueError("Nao e possivel simular um dia no futuro.")
    if dias < 1:
        raise ValueError("dias deve ser maior que zero.")
    return [
        simular_dia(db, dia_final - timedelta(days=dias - 1 - i), semente=semente, deterministico=deterministico)
        for i in range(dias)
    ]
