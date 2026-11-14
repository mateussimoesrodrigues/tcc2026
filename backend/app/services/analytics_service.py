"""Agregacoes para medir o motor de promocoes.

Responde a pergunta que o resto do sistema nao respondia: *a IA esta
acertando?* Ate aqui o fluxo terminava na mudanca de preco -- nenhuma
rota lia `pedido`/`pedido_item` e nao havia um unico `group_by` no
backend, entao o dado de venda existia no banco e era inacessivel.

Tres decisoes que valem registro:

1. **A fonte do preco praticado e `pedido_item`, nao
   `movimentacao_estoque`.** A movimentacao so tem quantidade; o preco do
   momento da venda vive em `pedido_item.preco_unitario_snapshot`, com a
   data vindo de `pedido.criado_em`. E `produto.preco_vigente` e property
   Python, nao coluna -- nao da pra usar em SQL.

2. **Venda so conta depois da conferencia no caixa.** Um pedido em
   GERADO e um carrinho a caminho do caixa, nao uma venda; EXPIRADO e um
   carrinho abandonado. Contar tudo inflaria a receita.

3. **A comparacao antes/depois nao e um experimento controlado.** Nao ha
   grupo de controle e nada isola sazonalidade, ruptura de estoque ou
   concorrencia. Toda resposta que usa essa comparacao carrega o aviso em
   `OBSERVACAO_ANTES_DEPOIS` -- e honestidade metodologica, nao rodape.

Portabilidade SQLite (testes) x PostgreSQL (producao): duas diferencas
mordem aqui e estao encapsuladas em `_bucket_periodo` e no `type_` do
`lead()` -- ver os comentarios nos respectivos pontos.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import ceil
from statistics import median

from sqlalchemy import DateTime, Numeric, case, func, select
from sqlalchemy.orm import Session

from app.models.estoque import Estoque
from app.models.historico_preco import HistoricoPreco, TipoAlteracaoPreco
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.pedido import Pedido, StatusPedido
from app.models.pedido_item import PedidoItem
from app.models.produto import Produto
from app.models.promocao_sugestao import PromocaoSugestao, StatusSugestao

JANELA_PADRAO_DIAS = 90
LIMITE_PROMOCOES_PADRAO = 50
LIMITE_PARADOS_PADRAO = 50
DIAS_PARADO_PADRAO = 30
# Teto da janela comparada: promocoes muito longas distorceriam a
# normalizacao por dia e trariam ruido demais de outros fatores.
MAX_DIAS_JANELA_COMPARADA = 30

# Ver decisao 2 no docstring do modulo.
STATUS_VENDA_CONFIRMADA = (StatusPedido.CONFERIDO_NO_CAIXA,)

OBSERVACAO_ANTES_DEPOIS = (
    "Comparacao antes/depois sem grupo de controle: nao isola sazonalidade, "
    "ruptura de estoque nem outros fatores. Indica associacao, nao causalidade."
)

_ZERO = Decimal("0")


def _agora() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _dialeto(db: Session) -> str:
    return db.get_bind().dialect.name


def _bucket_periodo(coluna, granularidade: str, dialeto: str):
    """Agrupador de periodo portavel.

    O Postgres tem `date_trunc`, o SQLite nao -- la o equivalente e
    `strftime` com uma mascara. Os dois devolvem tipos diferentes
    (timestamp x texto), por isso o rotulo e normalizado em
    `_rotulo_periodo`.
    """
    if dialeto == "postgresql":
        unidade = {"dia": "day", "semana": "week", "mes": "month"}[granularidade]
        return func.date_trunc(unidade, coluna)
    mascara = {"dia": "%Y-%m-%d", "semana": "%Y-W%W", "mes": "%Y-%m"}[granularidade]
    return func.strftime(mascara, coluna)


def _rotulo_periodo(valor) -> str:
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    return str(valor)


def _pct(parte: float, total: float) -> float | None:
    return round(parte / total * 100, 2) if total else None


def _variacao_pct(antes: float, depois: float) -> float | None:
    """None quando nao ha base de comparacao -- e diferente de 0%, e a UI
    precisa distinguir ('sem vendas antes' nao e 'nao mudou nada')."""
    if antes <= 0:
        return None
    return round((depois / antes - 1) * 100, 1)


# ---------------------------------------------------------------------------
# 1. Sugestoes: funil de decisao humana
# ---------------------------------------------------------------------------
def metricas_sugestoes(db: Session, *, desde: datetime | None = None) -> dict:
    filtros = [PromocaoSugestao.criado_em >= desde] if desde else []

    por_status = {
        status: (total, desconto)
        for status, total, desconto in db.execute(
            select(
                PromocaoSugestao.status,
                func.count(PromocaoSugestao.id),
                func.avg(PromocaoSugestao.percentual_desconto_sugerido),
            )
            .where(*filtros)
            .group_by(PromocaoSugestao.status)
        ).all()
    }

    def total_de(status: StatusSugestao) -> int:
        return por_status.get(status, (0, None))[0]

    def desconto_de(status: StatusSugestao) -> Decimal | None:
        media = por_status.get(status, (0, None))[1]
        return round(Decimal(str(media)), 2) if media is not None else None

    aprovadas = total_de(StatusSugestao.APROVADA)
    rejeitadas = total_de(StatusSugestao.REJEITADA)
    pendentes = total_de(StatusSugestao.PENDENTE)
    expiradas = total_de(StatusSugestao.EXPIRADA)
    decididas = aprovadas + rejeitadas

    desconto_geral = db.execute(
        select(func.avg(PromocaoSugestao.percentual_desconto_sugerido)).where(*filtros)
    ).scalar_one()

    # Desconto que de fato virou preco -- pode divergir do sugerido se o
    # funcionario aprovou algo diferente, ou se a sugestao foi barrada.
    desconto_aplicado = db.execute(
        select(
            func.avg(
                (HistoricoPreco.preco_anterior - HistoricoPreco.preco_novo)
                / func.nullif(HistoricoPreco.preco_anterior, 0)
                * 100
            )
        ).where(HistoricoPreco.tipo_alteracao == TipoAlteracaoPreco.PROMOCAO_IA_APROVADA)
    ).scalar_one()

    # Tempo ate a decisao: subtracao de datetime nao e portavel entre
    # SQLite e Postgres, e o volume e de centenas de linhas -- calcular em
    # Python sai mais barato que manter dois dialetos de SQL.
    pares = db.execute(
        select(PromocaoSugestao.criado_em, PromocaoSugestao.avaliada_em)
        .where(PromocaoSugestao.avaliada_em.is_not(None), *filtros)
    ).all()
    minutos = sorted((avaliada - criada).total_seconds() / 60 for criada, avaliada in pares)

    por_modelo = []
    linhas_modelo: dict[str, dict] = {}
    for modelo, status, total, desconto in db.execute(
        select(
            PromocaoSugestao.modelo_ia_usado,
            PromocaoSugestao.status,
            func.count(PromocaoSugestao.id),
            func.avg(PromocaoSugestao.percentual_desconto_sugerido),
        )
        .where(*filtros)
        .group_by(PromocaoSugestao.modelo_ia_usado, PromocaoSugestao.status)
    ).all():
        linha = linhas_modelo.setdefault(
            modelo,
            {"modelo": modelo, "total": 0, "aprovadas": 0, "rejeitadas": 0, "pendentes": 0, "_soma": _ZERO},
        )
        linha["total"] += total
        if status == StatusSugestao.APROVADA:
            linha["aprovadas"] += total
        elif status == StatusSugestao.REJEITADA:
            linha["rejeitadas"] += total
        elif status == StatusSugestao.PENDENTE:
            linha["pendentes"] += total
        if desconto is not None:
            linha["_soma"] += Decimal(str(desconto)) * total

    for linha in linhas_modelo.values():
        decididas_modelo = linha["aprovadas"] + linha["rejeitadas"]
        por_modelo.append(
            {
                "modelo": linha["modelo"],
                "total": linha["total"],
                "aprovadas": linha["aprovadas"],
                "rejeitadas": linha["rejeitadas"],
                "pendentes": linha["pendentes"],
                "taxa_aprovacao": _pct(linha["aprovadas"], decididas_modelo),
                "desconto_medio_sugerido": (
                    round(linha["_soma"] / linha["total"], 2) if linha["total"] else None
                ),
            }
        )
    por_modelo.sort(key=lambda linha: linha["total"], reverse=True)

    return {
        "total": aprovadas + rejeitadas + pendentes + expiradas,
        "aprovadas": aprovadas,
        "rejeitadas": rejeitadas,
        "pendentes": pendentes,
        "expiradas": expiradas,
        # Pendentes ficam FORA do denominador: ainda nao foram julgadas.
        "taxa_aprovacao": _pct(aprovadas, decididas),
        "taxa_rejeicao": _pct(rejeitadas, decididas),
        "desconto_medio_sugerido": round(Decimal(str(desconto_geral)), 2)
        if desconto_geral is not None
        else None,
        "desconto_medio_aprovado": desconto_de(StatusSugestao.APROVADA),
        "desconto_medio_rejeitado": desconto_de(StatusSugestao.REJEITADA),
        "desconto_medio_aplicado": round(Decimal(str(desconto_aplicado)), 2)
        if desconto_aplicado is not None
        else None,
        "tempo_medio_decisao_minutos": round(sum(minutos) / len(minutos), 1) if minutos else None,
        "tempo_mediano_decisao_minutos": round(median(minutos), 1) if minutos else None,
        "por_modelo": por_modelo,
    }


# ---------------------------------------------------------------------------
# 2. Janela de cada promocao + efeito nas vendas
# ---------------------------------------------------------------------------
def _vendas_no_intervalo(db: Session, produto_id: int, inicio: datetime, fim: datetime) -> tuple[int, Decimal]:
    unidades, receita = db.execute(
        select(
            func.coalesce(func.sum(PedidoItem.quantidade), 0),
            func.coalesce(func.sum(PedidoItem.subtotal), _ZERO),
        )
        .join(Pedido, Pedido.id == PedidoItem.pedido_id)
        .where(
            PedidoItem.produto_id == produto_id,
            Pedido.status.in_(STATUS_VENDA_CONFIRMADA),
            Pedido.criado_em >= inicio,
            Pedido.criado_em < fim,
        )
    ).one()
    return int(unidades), Decimal(str(receita))


def janelas_promocoes(db: Session, *, limite: int = LIMITE_PROMOCOES_PADRAO) -> list:
    """Inicio e fim de cada promocao, derivados de `historico_preco`.

    Nao existe coluna de fim: a promocao termina na proxima linha do mesmo
    produto (normalmente `fim_promocao`), o que e exatamente um `LEAD`.

    Dois detalhes que custam caro se esquecidos:
    - `type_=DateTime()` no lead. Sem isso o SQLite devolve a coluna como
      **string** (o SQLAlchemy nao aplica o conversor de tipo na saida da
      window function) e qualquer aritmetica de data quebra.
    - O filtro por `tipo_alteracao` vem DEPOIS da window (via subquery).
      Filtrar antes tiraria as linhas de `fim_promocao` do particionamento
      e o LEAD apontaria para a promocao seguinte, nao para o fim desta.
    """
    fim_em = func.lead(HistoricoPreco.criado_em, type_=DateTime()).over(
        partition_by=HistoricoPreco.produto_id, order_by=HistoricoPreco.criado_em
    ).label("fim_em")

    com_janela = select(
        HistoricoPreco.id,
        HistoricoPreco.produto_id,
        HistoricoPreco.sugestao_id,
        HistoricoPreco.preco_anterior,
        HistoricoPreco.preco_novo,
        HistoricoPreco.tipo_alteracao,
        HistoricoPreco.criado_em.label("inicio_em"),
        fim_em,
    ).subquery()

    return db.execute(
        select(
            com_janela,
            Produto.nome,
            Produto.marca,
            Produto.custo,
            Produto.preco_normal,
        )
        .join(Produto, Produto.id == com_janela.c.produto_id)
        .where(com_janela.c.tipo_alteracao == TipoAlteracaoPreco.PROMOCAO_IA_APROVADA)
        .order_by(com_janela.c.inicio_em.desc())
        .limit(limite)
    ).all()


def efeito_promocoes(db: Session, *, limite: int = LIMITE_PROMOCOES_PADRAO) -> list[dict]:
    """Vendas durante cada promocao contra a janela-espelho imediatamente
    anterior, do mesmo tamanho.

    Normaliza por dia porque as janelas variam de duracao (uma promocao de
    3 dias e uma de 25 nao sao comparaveis em total absoluto). Sao N
    consultas com N = numero de promocoes (dezenas) -- o N+1 e aceitavel
    aqui e muito mais legivel que um CTE especifico de dialeto.
    """
    agora = _agora()
    resultado = []

    for linha in janelas_promocoes(db, limite=limite):
        inicio = linha.inicio_em
        em_andamento = linha.fim_em is None
        fim = linha.fim_em or agora

        duracao_dias = max((fim - inicio).total_seconds() / 86400, 1 / 24)
        duracao_comparada = min(duracao_dias, MAX_DIAS_JANELA_COMPARADA)
        fim_comparado = inicio + timedelta(days=duracao_comparada)
        inicio_antes = inicio - timedelta(days=duracao_comparada)

        unidades_antes, receita_antes = _vendas_no_intervalo(db, linha.produto_id, inicio_antes, inicio)
        unidades_depois, receita_depois = _vendas_no_intervalo(db, linha.produto_id, inicio, fim_comparado)

        desconto = (
            (linha.preco_anterior - linha.preco_novo) / linha.preco_anterior * 100
            if linha.preco_anterior
            else _ZERO
        )
        margem_unitaria = (linha.preco_novo - linha.custo) if linha.custo is not None else None

        resultado.append(
            {
                "sugestao_id": linha.sugestao_id,
                "produto_id": linha.produto_id,
                "produto_nome": linha.nome,
                "produto_marca": linha.marca,
                "preco_anterior": linha.preco_anterior,
                "preco_promocional": linha.preco_novo,
                "desconto_percentual": round(desconto, 2),
                "inicio_em": inicio,
                "fim_em": linha.fim_em,
                "em_andamento": em_andamento,
                "duracao_dias": round(duracao_dias, 1),
                "unidades_antes": unidades_antes,
                "unidades_depois": unidades_depois,
                "receita_antes": receita_antes,
                "receita_depois": receita_depois,
                "unidades_dia_antes": round(unidades_antes / duracao_comparada, 2),
                "unidades_dia_depois": round(unidades_depois / duracao_comparada, 2),
                "variacao_unidades_percentual": _variacao_pct(unidades_antes, unidades_depois),
                "variacao_receita_percentual": _variacao_pct(float(receita_antes), float(receita_depois)),
                "margem_unitaria_promocional": margem_unitaria,
                "observacao": OBSERVACAO_ANTES_DEPOIS,
            }
        )

    return resultado


# ---------------------------------------------------------------------------
# 3. Serie de vendas
# ---------------------------------------------------------------------------
def serie_vendas(
    db: Session, *, granularidade: str = "dia", desde: datetime | None = None, ate: datetime | None = None
) -> list[dict]:
    agora = _agora()
    desde = desde or (agora - timedelta(days=JANELA_PADRAO_DIAS))
    ate = ate or agora

    bucket = _bucket_periodo(Pedido.criado_em, granularidade, _dialeto(db)).label("periodo")
    custo_linha = PedidoItem.quantidade * func.coalesce(Produto.custo, 0)

    linhas = db.execute(
        select(
            bucket,
            func.sum(PedidoItem.subtotal).label("receita"),
            func.sum(PedidoItem.quantidade).label("unidades"),
            func.count(func.distinct(Pedido.id)).label("pedidos"),
            func.sum(custo_linha).label("custo_total"),
            # Parte da receita sem custo cadastrado: sem isso a margem
            # apareceria inflada e ninguem saberia por que.
            func.sum(
                case((Produto.custo.is_(None), PedidoItem.subtotal), else_=0)
            ).label("receita_sem_custo"),
        )
        .join(Pedido, Pedido.id == PedidoItem.pedido_id)
        .join(Produto, Produto.id == PedidoItem.produto_id)
        .where(
            Pedido.status.in_(STATUS_VENDA_CONFIRMADA),
            Pedido.criado_em >= desde,
            Pedido.criado_em < ate,
        )
        .group_by(bucket)
        .order_by(bucket)
    ).all()

    serie = []
    for linha in linhas:
        receita = Decimal(str(linha.receita or 0))
        custo_total = Decimal(str(linha.custo_total or 0))
        margem = receita - custo_total
        serie.append(
            {
                "periodo": _rotulo_periodo(linha.periodo),
                "receita": receita,
                "unidades": int(linha.unidades or 0),
                "pedidos": int(linha.pedidos or 0),
                "custo_total": custo_total,
                "margem_bruta": margem,
                "margem_percentual": round(float(margem / receita * 100), 2) if receita else None,
                "receita_sem_custo_cadastrado": Decimal(str(linha.receita_sem_custo or 0)),
            }
        )
    return serie


# ---------------------------------------------------------------------------
# 4. Produtos parados
# ---------------------------------------------------------------------------
def produtos_parados(
    db: Session, *, dias: int = DIAS_PARADO_PADRAO, limite: int = LIMITE_PARADOS_PADRAO
) -> list[dict]:
    """Candidatos naturais a promocao: com estoque e sem giro. Uma consulta
    agregada so (nada de N+1 por produto)."""
    agora = _agora()
    inicio_janela = agora - timedelta(days=JANELA_PADRAO_DIAS)

    ultima_venda = (
        select(
            MovimentacaoEstoque.produto_id,
            func.max(MovimentacaoEstoque.criado_em).label("ultima_venda"),
        )
        .where(MovimentacaoEstoque.tipo == TipoMovimentacao.SAIDA_VENDA)
        .group_by(MovimentacaoEstoque.produto_id)
        .subquery()
    )
    vendidos = (
        select(
            MovimentacaoEstoque.produto_id,
            func.sum(MovimentacaoEstoque.quantidade).label("unidades"),
        )
        .where(
            MovimentacaoEstoque.tipo == TipoMovimentacao.SAIDA_VENDA,
            MovimentacaoEstoque.criado_em >= inicio_janela,
        )
        .group_by(MovimentacaoEstoque.produto_id)
        .subquery()
    )
    pendentes = (
        select(PromocaoSugestao.produto_id)
        .where(PromocaoSugestao.status == StatusSugestao.PENDENTE)
        .subquery()
    )

    linhas = db.execute(
        select(
            Produto.id,
            Produto.nome,
            Produto.marca,
            Produto.tamanho,
            Produto.preco_normal,
            Produto.custo,
            Produto.promocao_ativa,
            Estoque.quantidade,
            ultima_venda.c.ultima_venda,
            func.coalesce(vendidos.c.unidades, 0).label("unidades_janela"),
            pendentes.c.produto_id.label("tem_pendente"),
        )
        .join(Estoque, Estoque.produto_id == Produto.id)
        .outerjoin(ultima_venda, ultima_venda.c.produto_id == Produto.id)
        .outerjoin(vendidos, vendidos.c.produto_id == Produto.id)
        .outerjoin(pendentes, pendentes.c.produto_id == Produto.id)
        .where(Produto.ativo.is_(True), Estoque.quantidade > 0)
        # coalesce com uma data antiga em vez de nulls_first(): portavel
        # sem depender da versao do SQLite. Nunca vendeu = mais parado.
        .order_by(func.coalesce(ultima_venda.c.ultima_venda, datetime(1970, 1, 1)).asc())
        .limit(limite)
    ).all()

    resultado = []
    for linha in linhas:
        dias_sem_venda = (agora - linha.ultima_venda).days if linha.ultima_venda else None
        if dias_sem_venda is not None and dias_sem_venda < dias:
            continue
        # Sem custo cadastrado, estima o capital parado pela metade do preco
        # -- e uma aproximacao grosseira, rotulada como tal na resposta.
        custo_unitario = linha.custo if linha.custo is not None else linha.preco_normal / 2
        resultado.append(
            {
                "produto_id": linha.id,
                "nome": linha.nome,
                "marca": linha.marca,
                "tamanho": linha.tamanho,
                "estoque": linha.quantidade,
                "dias_sem_venda": dias_sem_venda,
                "unidades_vendidas_janela": int(linha.unidades_janela or 0),
                "preco_normal": linha.preco_normal,
                "custo": linha.custo,
                "valor_parado": round(Decimal(str(custo_unitario)) * linha.quantidade, 2),
                "custo_estimado": linha.custo is None,
                "promocao_ativa": bool(linha.promocao_ativa),
                "tem_sugestao_pendente": linha.tem_pendente is not None,
            }
        )
    return resultado


DIAS_ALERTA_REPOSICAO_PADRAO = 15
DIAS_COBERTURA_PADRAO = 30
LIMITE_REPOSICAO_PADRAO = 50


def sugerir_reposicao(
    db: Session,
    *,
    dias_alerta: int = DIAS_ALERTA_REPOSICAO_PADRAO,
    dias_cobertura: int = DIAS_COBERTURA_PADRAO,
    limite: int = LIMITE_REPOSICAO_PADRAO,
) -> dict:
    """Espelho de `produtos_parados`: quem vai **faltar**, nao quem sobra.

    Mesma formula de giro de `ai.rules.calcular_sinais`
    (`unidades_vendidas / janela_dias`, e `estoque / giro` para os dias
    restantes) -- mas numa consulta agregada so, e nao duas por produto como
    la. `calcular_sinais` avalia um produto por vez a pedido do LLM; aqui a
    varredura e do catalogo inteiro, e o N+1 apareceria na latencia da tela.
    `test_analytics` fixa a paridade entre os dois numeros.

    Tres situacoes entram:
    - `risco`: ainda tem estoque, mas acaba dentro de `dias_alerta`.
    - `ruptura`: estoque zerado e vendeu na janela. Este e o caso que
      escapava de tudo: `produtos_parados` exige `quantidade > 0`, e o
      produto sem estoque para de vender e vai zerando o giro -- sumia das
      duas listas justamente quando estava custando venda.

    Fica de fora quem tem giro zero e ainda tem estoque: sem ritmo nao ha
    data de ruptura, e esse produto e assunto de `produtos_parados`.
    """
    agora = _agora()
    inicio_janela = agora - timedelta(days=JANELA_PADRAO_DIAS)

    vendidos = (
        select(
            MovimentacaoEstoque.produto_id,
            func.sum(MovimentacaoEstoque.quantidade).label("unidades"),
        )
        .where(
            MovimentacaoEstoque.tipo == TipoMovimentacao.SAIDA_VENDA,
            MovimentacaoEstoque.criado_em >= inicio_janela,
        )
        .group_by(MovimentacaoEstoque.produto_id)
        .subquery()
    )

    linhas = db.execute(
        select(
            Produto.id,
            Produto.nome,
            Produto.marca,
            Produto.tamanho,
            Produto.preco_normal,
            Produto.custo,
            Produto.promocao_ativa,
            Estoque.quantidade,
            func.coalesce(vendidos.c.unidades, 0).label("unidades_janela"),
        )
        .join(Estoque, Estoque.produto_id == Produto.id)
        .outerjoin(vendidos, vendidos.c.produto_id == Produto.id)
        .where(Produto.ativo.is_(True))
    ).all()

    itens = []
    sem_custo = 0
    custo_total = _ZERO

    for linha in linhas:
        unidades = int(linha.unidades_janela or 0)
        giro_diario = unidades / JANELA_PADRAO_DIAS
        estoque = linha.quantidade

        if estoque <= 0:
            if unidades == 0:
                continue  # sem estoque e sem venda: descontinuado, nao ruptura
            situacao = "ruptura"
            dias_restantes = 0.0
        else:
            if giro_diario <= 0:
                continue
            dias_restantes = estoque / giro_diario
            if dias_restantes > dias_alerta:
                continue
            situacao = "risco"

        alvo = ceil(giro_diario * dias_cobertura)
        quantidade_sugerida = max(1, alvo - estoque)

        custo_unitario = linha.custo if linha.custo is not None else linha.preco_normal / 2
        if linha.custo is None:
            sem_custo += 1
        custo_compra = round(Decimal(str(custo_unitario)) * quantidade_sugerida, 2)
        custo_total += custo_compra

        itens.append(
            {
                "produto_id": linha.id,
                "nome": linha.nome,
                "marca": linha.marca,
                "tamanho": linha.tamanho,
                "estoque": estoque,
                "unidades_vendidas_janela": unidades,
                "giro_diario": round(giro_diario, 4),
                "dias_de_estoque_restante": round(dias_restantes, 1),
                "situacao": situacao,
                "quantidade_sugerida": quantidade_sugerida,
                "custo": linha.custo,
                "custo_estimado_compra": custo_compra,
                "custo_estimado": linha.custo is None,
                # Em promocao o produto vende acima do ritmo normal, entao os
                # dias restantes estao subestimados e a sugestao, inflada.
                # Sinaliza em vez de excluir -- quem decide e o gestor.
                "promocao_ativa": bool(linha.promocao_ativa),
            }
        )

    itens.sort(key=lambda i: i["dias_de_estoque_restante"])
    itens = itens[:limite]

    return {
        "dias_alerta": dias_alerta,
        "dias_cobertura": dias_cobertura,
        "itens": itens,
        "custo_total_estimado": sum((i["custo_estimado_compra"] for i in itens), _ZERO),
        "produtos_sem_custo": sem_custo,
    }


# ---------------------------------------------------------------------------
# 5. Resumo (uma chamada para a pagina inteira)
# ---------------------------------------------------------------------------
def resumo(
    db: Session,
    *,
    janela_dias: int = JANELA_PADRAO_DIAS,
    desde: datetime | None = None,
    ate: datetime | None = None,
) -> dict:
    agora = _agora()
    ate = ate or agora
    desde = desde or (ate - timedelta(days=janela_dias))

    serie = serie_vendas(db, granularidade="dia", desde=desde, ate=ate)
    receita_periodo = sum((p["receita"] for p in serie), _ZERO)
    margem_periodo = sum((p["margem_bruta"] for p in serie), _ZERO)
    unidades_periodo = sum(p["unidades"] for p in serie)
    pedidos_periodo = sum(p["pedidos"] for p in serie)

    # Pedidos ainda nao confirmados no caixa -- ficam de fora da receita
    # (decisao 2 no topo do modulo), mas o painel mostra que existem.
    nao_confirmados = db.execute(
        select(func.count(Pedido.id)).where(
            Pedido.status.notin_(STATUS_VENDA_CONFIRMADA),
            Pedido.criado_em >= desde,
            Pedido.criado_em < ate,
        )
    ).scalar_one()

    return {
        "gerado_em": agora,
        "janela_dias": max((ate - desde).days, 1),
        "receita_periodo": receita_periodo,
        "margem_periodo": margem_periodo,
        "unidades_periodo": unidades_periodo,
        "pedidos_periodo": pedidos_periodo,
        "ticket_medio": round(receita_periodo / pedidos_periodo, 2) if pedidos_periodo else None,
        "pedidos_nao_confirmados": int(nao_confirmados),
        "sugestoes": metricas_sugestoes(db),
        "serie": serie,
        "promocoes": efeito_promocoes(db),
        "produtos_parados": produtos_parados(db),
    }
