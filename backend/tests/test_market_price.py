"""Preco de mercado (app/ai/market_price.py) e sua entrada no pipeline.
Nunca bate em rede real: o HTTP e simulado com `httpx.MockTransport`."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.ai import llm_provider, market_price
from app.core.config import Settings, get_settings
from app.models.estoque import Estoque
from app.models.preco_mercado import PrecoMercado, StatusPrecoMercado
from app.models.produto import Produto

COM_SERPER = {"serper_api_key": "k"}
COM_ML = {"ml_client_id": "id", "ml_client_secret": "segredo"}


def _settings(**kwargs) -> Settings:
    base = {"ml_client_id": "", "ml_client_secret": "", "serper_api_key": ""}
    return Settings(_env_file=None, **(base | kwargs))


def _buscador(handler, **config) -> market_price.BuscadorMercado:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return market_price.BuscadorMercado(client, _settings(**config))


def _shopping(*precos):
    return httpx.Response(200, json={"shopping": [{"title": "x", "price": p} for p in precos]})


def _produto(db, *, preco="20.00", custo=None, marca=None, nome="Cola Branca"):
    produto = Produto(
        nome=nome, marca=marca, preco_normal=Decimal(preco), custo=Decimal(custo) if custo else None
    )
    db.add(produto)
    db.flush()
    db.add(Estoque(produto_id=produto.id, quantidade=10))
    db.commit()
    return produto


def _anuncios(*precos):
    return [market_price.Anuncio(Decimal(p)) for p in precos]


# --- faixa e parsing ---------------------------------------------------


def test_faixa_descarta_outliers_extremos_e_usa_mediana():
    faixa = market_price.calcular_faixa(
        _anuncios("0.50", "10", "11", "12", "14", "500"), min_amostras=3
    )
    assert (faixa.minimo, faixa.mediana, faixa.maximo, faixa.n_amostras) == (
        Decimal("10.00"),
        Decimal("11.50"),
        Decimal("14.00"),
        4,
    )


def test_faixa_com_poucas_amostras_nao_serve_de_referencia():
    assert market_price.calcular_faixa(_anuncios("10", "11"), min_amostras=3) is None
    assert market_price.calcular_faixa(_anuncios("10"), min_amostras=1) is None
    assert market_price.calcular_faixa([], min_amostras=1) is None


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("R$ 12,90", Decimal("12.90")),
        ("R$\xa01.234,56", Decimal("1234.56")),
        ("R$ 15 agora", Decimal("15.00")),
        ("US$ 3.50", None),
        ("R$ 12.90", None),
        (None, None),
    ],
)
def test_preco_em_reais(texto, esperado):
    assert market_price._preco_em_reais(texto) == esperado


def test_lojas_so_dos_precos_usados_e_sem_repetir():
    anuncios = [
        market_price.Anuncio(Decimal(preco), loja)
        for preco, loja in (("10", "Loja A"), ("11", "Loja B"), ("12", "Loja A"), ("13", None), ("500", "Fora"))
    ]
    assert market_price.calcular_faixa(anuncios, min_amostras=3).lojas == ("Loja A", "Loja B")


def test_lojas_do_serper_vao_pro_registro_e_pros_sinais(db_session):
    itens = [{"price": f"R$ {p},00", "source": loja} for p, loja in ((8, "Kalunga"), (9, " Shopee "), (10, ""))]
    registro = market_price.obter_preco_mercado(
        db_session,
        _produto(db_session),
        _buscador(lambda r: httpx.Response(200, json={"shopping": itens}), **COM_SERPER),
    )
    db_session.commit()

    sinais, _ = market_price.para_sinais(registro, Decimal("20"))
    assert sinais["lojas"] == ["Kalunga", "Shopee"]


def test_anuncios_usados_guardam_titulo_preco_e_so_link_http(db_session):
    itens = [
        {"price": "R$ 8,00", "source": "A", "title": "Cola 90g", "link": "https://loja.example/a"},
        {"price": "R$ 9,00", "source": "B", "title": "Cola", "link": "javascript:alert(1)"},
        {"price": "R$ 10,00", "source": "C"},
        {"price": "R$ 900,00", "source": "D", "title": "Outlier", "link": "https://loja.example/d"},
    ]
    registro = market_price.obter_preco_mercado(
        db_session,
        _produto(db_session),
        _buscador(lambda r: httpx.Response(200, json={"shopping": itens}), **COM_SERPER),
    )
    db_session.commit()

    anuncios = market_price.para_sinais(registro, Decimal("20"))[0]["anuncios"]
    assert anuncios == [
        {"preco": 8.0, "loja": "A", "titulo": "Cola 90g", "link": "https://loja.example/a"},
        {"preco": 9.0, "loja": "B", "titulo": "Cola", "link": None},
        {"preco": 10.0, "loja": "C", "titulo": None, "link": None},
    ]


# --- fontes ------------------------------------------------------------


def test_considera_apenas_os_primeiros_n_resultados():
    buscador = _buscador(
        lambda r: _shopping("R$ 10,00", "R$ 11,00", "R$ 12,00", "R$ 30,00"),
        **COM_SERPER,
        preco_mercado_n_resultados=3,
    )
    faixa, fonte = buscador.buscar("cola")
    assert (faixa.maximo, faixa.n_amostras, fonte) == (Decimal("12.00"), 3, "google_shopping")


def test_mercado_livre_com_token_e_a_fonte_principal():
    def handler(request):
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "abc"})
        assert request.url.path == "/sites/MLB/search"
        assert request.headers["Authorization"] == "Bearer abc"
        return httpx.Response(200, json={"results": [{"price": p, "currency_id": "BRL"} for p in (8, 9, 10)]})

    faixa, fonte = _buscador(handler, **COM_ML, **COM_SERPER).buscar("cola")
    assert (faixa.mediana, fonte) == (Decimal("9.00"), "mercado_livre")


def test_ml_com_403_cai_no_serper_e_nao_e_tentado_de_novo():
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "abc"})
        if request.url.host == "api.mercadolibre.com":
            return httpx.Response(403)
        return _shopping("R$ 8,00", "R$ 9,00", "R$ 10,00")

    buscador = _buscador(handler, **COM_ML, **COM_SERPER)
    assert buscador.buscar("cola")[1] == "google_shopping"
    hosts.clear()
    assert buscador.buscar("fita")[1] == "google_shopping"
    assert hosts == ["google.serper.dev"]


@pytest.mark.parametrize(
    "resposta",
    [
        httpx.Response(500),
        httpx.Response(200, text="nao e json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"shopping": []}),
    ],
)
def test_falha_da_fonte_vira_nao_encontrado(db_session, monkeypatch, resposta):
    produto = _produto(db_session)
    registro = market_price.obter_preco_mercado(
        db_session, produto, _buscador(lambda r: resposta, **COM_SERPER)
    )
    assert registro.status == StatusPrecoMercado.NAO_ENCONTRADO
    assert registro.preco_mediana is None
    assert registro.n_amostras == 0


def test_timeout_nao_sobe_excecao(db_session):
    def handler(request):
        raise httpx.ConnectTimeout("estourou", request=request)

    registro = market_price.obter_preco_mercado(
        db_session, _produto(db_session), _buscador(handler, **COM_SERPER)
    )
    assert registro.status == StatusPrecoMercado.NAO_ENCONTRADO


def test_sem_credencial_nao_busca_nem_grava(db_session):
    def handler(request):
        raise AssertionError("nao deveria chamar a rede")

    assert market_price.obter_preco_mercado(db_session, _produto(db_session), _buscador(handler)) is None
    db_session.commit()
    assert db_session.query(PrecoMercado).count() == 0


def test_consulta_usa_marca_e_nome(db_session):
    produto = _produto(db_session, marca="Acrilex")
    assert market_price.montar_consulta(produto) == "Acrilex Cola Branca"


# --- validade do registro no banco -------------------------------------


@pytest.mark.parametrize(
    "status,idade_dias,deve_buscar",
    [
        (StatusPrecoMercado.OK, 6, False),
        (StatusPrecoMercado.OK, 8, True),
        (StatusPrecoMercado.NAO_ENCONTRADO, 1, False),
        (StatusPrecoMercado.NAO_ENCONTRADO, 3, True),
    ],
)
def test_validade_do_registro(db_session, status, idade_dias, deve_buscar):
    produto = _produto(db_session)
    db_session.add(
        PrecoMercado(
            produto_id=produto.id,
            status=status,
            n_amostras=0,
            fonte="google_shopping",
            consultado_em=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=idade_dias),
        )
    )
    db_session.commit()
    chamadas = []

    def handler(request):
        chamadas.append(request)
        return _shopping("R$ 8,00", "R$ 9,00", "R$ 10,00")

    market_price.obter_preco_mercado(db_session, produto, _buscador(handler, **COM_SERPER))
    db_session.commit()

    assert bool(chamadas) is deve_buscar
    assert db_session.query(PrecoMercado).count() == 1  # atualiza a mesma linha


# --- pipeline ----------------------------------------------------------


def _registro_ok(db, produto, mediana="16.00"):
    db.add(
        PrecoMercado(
            produto_id=produto.id,
            status=StatusPrecoMercado.OK,
            preco_mediana=Decimal(mediana),
            preco_min=Decimal(mediana) - 1,
            preco_max=Decimal(mediana) + 1,
            n_amostras=7,
            fonte="mercado_livre",
            consultado_em=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    db.commit()


def _mockar_llm(monkeypatch, preco_sugerido="17.00"):
    recebidos = []

    def fake(sinais, *, client=None):
        recebidos.append(sinais)
        return llm_provider.SugestaoLLM(
            percentual_desconto=Decimal("15"),
            preco_sugerido=Decimal(preco_sugerido),
            justificativa="Preco acima do mercado.",
            prioridade="media",
            modelo_usado="groq/teste-mock",
        )

    monkeypatch.setattr("app.services.promotion_service.gerar_sugestao_llm", fake)
    return recebidos


def test_pipeline_entrega_faixa_e_posicao_ao_llm(auth_client, db_session, monkeypatch):
    _registro_ok(db_session, _produto(db_session))
    recebidos = _mockar_llm(monkeypatch)

    sugestao = auth_client.post("/promocoes/gerar-agora").json()["sugestoes_criadas"][0]

    assert recebidos[0].posicao_mercado == 1.25
    prompt = llm_provider._montar_prompt_usuario(recebidos[0])
    assert "mediana R$ 16.00, faixa de R$ 15.00 a R$ 17.00" in prompt
    assert "25% acima da mediana do mercado" in prompt
    assert sugestao["sem_referencia_mercado"] is False
    assert sugestao["sinais_detectados"]["preco_mercado"]["n_amostras"] == 7


def test_pipeline_sem_referencia_gera_sugestao_marcada(auth_client, db_session, monkeypatch):
    _produto(db_session)
    recebidos = _mockar_llm(monkeypatch)

    sugestao = auth_client.post("/promocoes/gerar-agora").json()["sugestoes_criadas"][0]

    assert sugestao["sem_referencia_mercado"] is True
    assert "mercado" not in llm_provider._montar_prompt_usuario(recebidos[0]).lower()


def test_pipeline_desligado_nao_marca_sugestao(auth_client, db_session, monkeypatch):
    _registro_ok(db_session, _produto(db_session))
    recebidos = _mockar_llm(monkeypatch)
    monkeypatch.setattr(get_settings(), "preco_mercado_habilitado", False)

    sugestao = auth_client.post("/promocoes/gerar-agora").json()["sugestoes_criadas"][0]

    assert recebidos[0].preco_mercado is None
    assert sugestao["sem_referencia_mercado"] is False


def test_mercado_abaixo_do_custo_nao_rebaixa_o_piso(auth_client, db_session, monkeypatch):
    """Custo 15 + margem minima de 10% = piso 16,50. Mercado a 10,00 nao
    autoriza o LLM a sugerir 12,00."""
    _registro_ok(db_session, _produto(db_session, custo="15.00"), mediana="10.00")
    _mockar_llm(monkeypatch, preco_sugerido="12.00")

    corpo = auth_client.post("/promocoes/gerar-agora").json()

    assert corpo["sugestoes_criadas"] == []
    assert corpo["falhas"][0]["categoria"] == "guard_rail"
