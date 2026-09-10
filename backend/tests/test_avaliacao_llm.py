"""Harness de avaliacao do LLM (scripts/avaliar_llm.py).

Nenhum teste aqui toca a rede: as funcoes de estatistica e o baseline sao
puros, e o fluxo completo roda em `--dry-run` (provedor sintetico). O
proprio harness e um script justamente pra a suite nunca gastar quota do
free tier -- estes testes cobrem a mecanica dele, nao os provedores.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx

from app.ai import rules
from app.models.estoque import Estoque
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.produto import Produto
from app.services.exceptions import (
    LLMIndisponivelError,
    PrecoAbaixoDoPisoError,
    RespostaLLMInvalidaError,
)
from scripts import avaliar_llm


def _sinais(**overrides) -> rules.SinaisProduto:
    base = dict(
        produto_id=1,
        nome="Cola Pano",
        marca="Gliart",
        tamanho="100g",
        preco_normal=20.0,
        estoque_atual=10,
        dias_sem_venda=60,
        unidades_vendidas_periodo=2,
        janela_dias=90,
        giro_diario=0.02,
        dias_de_estoque_restante=450.0,
        margem=0.5,
        proxima_data_sazonal="Natal",
        dias_ate_data_sazonal=40,
        desconto_maximo_permitido=45.0,
    )
    base.update(overrides)
    return rules.SinaisProduto(**base)


def _produto(preco="20.00", custo="10.00") -> Produto:
    return Produto(
        nome="Cola Pano",
        preco_normal=Decimal(preco),
        custo=Decimal(custo) if custo is not None else None,
    )


# --- baseline deterministico ------------------------------------------------


def test_baseline_e_deterministico():
    sinais, produto = _sinais(), _produto()
    valores = {avaliar_llm.baseline_deterministico(sinais, produto) for _ in range(10)}
    assert len(valores) == 1


def test_baseline_cresce_com_dias_sem_venda():
    produto = _produto(custo=None)  # sem piso, pra isolar a regra
    d20 = avaliar_llm.baseline_deterministico(_sinais(dias_sem_venda=20, dias_ate_data_sazonal=90,
                                                      dias_de_estoque_restante=10.0), produto)
    d50 = avaliar_llm.baseline_deterministico(_sinais(dias_sem_venda=50, dias_ate_data_sazonal=90,
                                                      dias_de_estoque_restante=10.0), produto)
    d90 = avaliar_llm.baseline_deterministico(_sinais(dias_sem_venda=90, dias_ate_data_sazonal=90,
                                                      dias_de_estoque_restante=10.0), produto)
    assert d20 < d50 < d90


def test_baseline_respeita_piso_de_custo():
    """Custo alto => teto baixo: o baseline nao pode sugerir prejuizo, do
    mesmo jeito que o LLM nao pode."""
    produto = _produto(preco="20.00", custo="16.00")  # piso 17.60 => teto 12%
    valor = avaliar_llm.baseline_deterministico(_sinais(dias_sem_venda=90), produto)
    assert valor == Decimal("12.00")


def test_baseline_nunca_vendeu_usa_faixa_maxima():
    produto = _produto(custo=None)
    nunca = avaliar_llm.baseline_deterministico(
        _sinais(dias_sem_venda=None, dias_ate_data_sazonal=90, dias_de_estoque_restante=None), produto
    )
    assert nunca == Decimal("25")


# --- estatistica ------------------------------------------------------------


def test_spearman_correlacao_perfeita_e_invertida():
    assert avaliar_llm.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert avaliar_llm.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0


def test_spearman_com_amostra_insuficiente_devolve_none():
    assert avaliar_llm.spearman([1], [2]) is None
    assert avaliar_llm.spearman([], []) is None


def test_spearman_trata_empates():
    # todos iguais de um lado: sem variacao, correlacao indefinida
    assert avaliar_llm.spearman([1, 1, 1], [1, 2, 3]) is None


def test_percentil():
    valores = [10.0, 20.0, 30.0, 40.0, 100.0]
    assert avaliar_llm._percentil(valores, 0.5) == 30.0
    assert avaliar_llm._percentil(valores, 0.95) == 100.0
    assert avaliar_llm._percentil([], 0.5) is None


def _execucao(**kw) -> avaliar_llm.ExecucaoLLM:
    base = dict(
        timestamp="2026-08-28T00:00:00+00:00",
        produto_id=1,
        produto_nome="Cola Pano",
        provedor="groq",
        modelo="groq/teste",
        temperatura=0.3,
        repeticao=1,
        informar_piso=True,
        sucesso=True,
        percentual=20.0,
        preco=16.0,
        prioridade="alta",
        latencia_ms=100.0,
        respeita_piso=True,
        desconto_baseline=25.0,
    )
    base.update(kw)
    return avaliar_llm.ExecucaoLLM(**base)


def test_resumir_por_produto_calcula_desvio_e_coeficiente_de_variacao():
    execucoes = [
        _execucao(percentual=10.0, repeticao=1),
        _execucao(percentual=20.0, repeticao=2),
        _execucao(percentual=30.0, repeticao=3),
    ]
    linha = avaliar_llm.resumir_por_produto(execucoes)[0]

    assert linha["execucoes"] == 3
    assert linha["desconto_medio"] == 20.0
    # desvio populacional de (10, 20, 30) = sqrt(200/3) ~= 8.16
    assert linha["desconto_desvio"] == 8.16
    assert linha["coef_variacao"] == 0.4082
    assert linha["amplitude"] == 20.0


def test_resumir_por_produto_com_resposta_estavel_tem_variacao_zero():
    execucoes = [_execucao(percentual=15.0, repeticao=i) for i in range(1, 4)]
    linha = avaliar_llm.resumir_por_produto(execucoes)[0]
    assert linha["desconto_desvio"] == 0.0
    assert linha["coef_variacao"] == 0.0
    assert linha["amplitude"] == 0.0


def test_resumir_por_provedor_calcula_taxa_de_invalida_e_classes():
    execucoes = [
        _execucao(percentual=20.0),
        _execucao(sucesso=False, percentual=None, preco=None, prioridade=None,
                  classe_erro="json_malformado"),
        _execucao(sucesso=False, percentual=None, preco=None, prioridade=None,
                  classe_erro="json_malformado"),
        _execucao(sucesso=False, percentual=None, preco=None, prioridade=None,
                  classe_erro="faixa_invalida"),
    ]
    por_produto = avaliar_llm.resumir_por_produto(execucoes)
    linha = avaliar_llm.resumir_por_provedor(execucoes, por_produto)[0]

    assert linha["taxa_sucesso_pct"] == 25.0
    assert linha["taxa_invalida_pct"] == 75.0
    assert '"json_malformado": 2' in linha["erros_por_classe"]
    assert '"faixa_invalida": 1' in linha["erros_por_classe"]


def test_resumir_por_provedor_mede_distancia_do_baseline():
    execucoes = [
        _execucao(percentual=30.0, desconto_baseline=25.0),  # 5 p.p. acima
        _execucao(percentual=20.0, desconto_baseline=25.0),  # 5 p.p. abaixo
    ]
    linha = avaliar_llm.resumir_por_provedor(execucoes, avaliar_llm.resumir_por_produto(execucoes))[0]
    assert linha["erro_medio_vs_baseline_pp"] == 5.0
    assert linha["mais_agressivo_que_baseline_pct"] == 50.0


# --- classificacao de erro --------------------------------------------------


def test_classificar_erro_por_tipo():
    assert avaliar_llm._classificar_erro(httpx.TimeoutException("t")) == "timeout"
    assert avaliar_llm._classificar_erro(httpx.ConnectError("c")) == "http"
    assert avaliar_llm._classificar_erro(LLMIndisponivelError("sem key")) == "sem_chave"
    assert avaliar_llm._classificar_erro(PrecoAbaixoDoPisoError("piso")) == "abaixo_do_piso"


def test_classificar_erro_de_resposta_invalida():
    def classe(mensagem: str) -> str:
        return avaliar_llm._classificar_erro(RespostaLLMInvalidaError(mensagem))

    assert classe("Resposta do LLM nao e JSON valido: x") == "json_malformado"
    assert classe("Campo ausente ou invalido na resposta do LLM: y") == "campo_ausente"
    assert classe("Desconto sugerido fora da faixa permitida (0-70%): 90") == "faixa_invalida"
    assert classe("Incoerencia entre desconto (50%) e preco sugerido") == "incoerencia_pct_preco"


# --- fluxo completo em dry-run ----------------------------------------------


def _produto_candidato(db_session):
    produto = Produto(nome="Produto Parado", preco_normal=Decimal("20.00"), custo=Decimal("8.00"))
    db_session.add(produto)
    db_session.flush()
    db_session.add(Estoque(produto_id=produto.id, quantidade=10))
    db_session.add(
        MovimentacaoEstoque(
            produto_id=produto.id,
            tipo=TipoMovimentacao.SAIDA_VENDA,
            quantidade=1,
            criado_em=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=60),
        )
    )
    db_session.commit()
    return produto


def test_dry_run_executa_sem_rede_e_gera_csv(db_session, tmp_path):
    _produto_candidato(db_session)
    cfg = avaliar_llm.Config(
        produtos=1, repeticoes=3, provedores=("groq",), saida=tmp_path, dry_run=True
    )

    execucoes = avaliar_llm.rodar_avaliacao(db_session, cfg)
    assert len(execucoes) == 3
    assert all(e.sucesso for e in execucoes)
    assert all(e.origem == "stub" for e in execucoes)
    # a validacao real rodou por cima da resposta sintetica
    assert all(e.coerente is True for e in execucoes)

    por_produto = avaliar_llm.resumir_por_produto(execucoes)
    por_provedor = avaliar_llm.resumir_por_provedor(execucoes, por_produto)
    caminhos = avaliar_llm.salvar(execucoes, por_produto, por_provedor, cfg)

    linhas = caminhos["execucoes"].read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 4  # cabecalho + 3 execucoes
    assert "produto_id" in linhas[0] and "coef_variacao" in caminhos["por_produto"].read_text(encoding="utf-8")


def test_metadados_nao_vazam_chaves_de_api(db_session, tmp_path):
    _produto_candidato(db_session)
    cfg = avaliar_llm.Config(produtos=1, repeticoes=1, provedores=("groq",), saida=tmp_path, dry_run=True)
    execucoes = avaliar_llm.rodar_avaliacao(db_session, cfg)
    caminhos = avaliar_llm.salvar(execucoes, [], [], cfg)

    metadados = caminhos["metadados"].read_text(encoding="utf-8")
    assert "groq_key_presente" in metadados  # so o booleano
    assert "api_key" not in metadados.lower()
    assert "gsk_" not in metadados  # prefixo das chaves da Groq


def test_limite_de_chamadas_aborta_antes_de_gastar_quota(db_session):
    _produto_candidato(db_session)
    cfg = avaliar_llm.Config(
        produtos=1, repeticoes=50, provedores=("groq", "gemini"), limite_chamadas=10, dry_run=True
    )
    assert avaliar_llm.rodar_avaliacao(db_session, cfg) == []


def test_amostragem_e_deterministica(db_session):
    for i in range(5):
        produto = Produto(nome=f"Parado {i}", preco_normal=Decimal("20.00"), custo=Decimal("8.00"))
        db_session.add(produto)
        db_session.flush()
        db_session.add(Estoque(produto_id=produto.id, quantidade=10))
        db_session.add(
            MovimentacaoEstoque(
                produto_id=produto.id,
                tipo=TipoMovimentacao.SAIDA_VENDA,
                quantidade=1,
                criado_em=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=60),
            )
        )
    db_session.commit()

    a = [p.id for p, _ in avaliar_llm.amostrar_produtos(db_session, 3, seed=42)]
    b = [p.id for p, _ in avaliar_llm.amostrar_produtos(db_session, 3, seed=42)]
    c = [p.id for p, _ in avaliar_llm.amostrar_produtos(db_session, 3, seed=7)]

    assert a == b
    assert len(a) == 3
    assert a != c or len(set(a) | set(c)) == 3  # seeds diferentes tendem a amostras diferentes
