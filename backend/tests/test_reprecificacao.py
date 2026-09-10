"""Preco de tabela: auditoria da alteracao manual e alerta de margem
defasada.

Separado de `test_price_guardrails.py`, que e sobre os guard-rails do preco
*promocional*. Aqui o assunto e o preco estrutural do produto.

Cuidado com a base do percentual, que e a pegadinha deste dominio: a margem
exibida e sobre o PRECO ((preco-custo)/preco, ver `ai/rules.calcular_sinais`),
enquanto `piso_de_preco` e markup sobre o CUSTO (custo * 1,10).
"""
from decimal import Decimal

import pytest

from app.models.historico_preco import HistoricoPreco, TipoAlteracaoPreco
from app.models.produto import Produto
from app.services import price_service
from app.services.exceptions import PrecoNaoPositivoError, PromocaoJaAtivaError


def _produto(db_session, *, custo="10.00", preco="12.00", promocao_ativa=False):
    produto = Produto(
        nome="Cola Pano",
        preco_normal=Decimal(preco),
        custo=Decimal(custo) if custo is not None else None,
        promocao_ativa=promocao_ativa,
        preco_promocional=Decimal("9.90") if promocao_ativa else None,
    )
    db_session.add(produto)
    db_session.commit()
    db_session.refresh(produto)
    return produto


def _criar_produto_api(auth_client, *, custo=None, preco="19.95"):
    corpo = {
        "nome": "Cola Pano",
        "codigo": "7896576331634",
        "preco_normal": preco,
        "quantidade_inicial": 5,
    }
    if custo is not None:
        corpo["custo"] = custo
    return auth_client.post("/produtos", json=corpo).json()


# --- arredondamento psicologico -------------------------------------------


@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("15.38", "15.90"),
        ("15.95", "16.90"),
        ("16.90", "16.90"),  # ja esta na terminacao: nao mexe
        ("13.00", "13.90"),
        ("12.34", "12.90"),
        ("10.00", "10.90"),
        # Item barato: subir pro proximo ,90 encareceria 81%, entao desce.
        ("1.05", "0.90"),
        # Nao ha ,90 abaixo de 0,90 que seja positivo: sobe mesmo assim.
        ("0.50", "0.90"),
    ],
)
def test_arredondar_preco_psicologico(valor, esperado):
    assert price_service.arredondar_preco_psicologico(valor) == Decimal(esperado)


# --- preco para a margem-alvo ----------------------------------------------


def test_preco_para_margem_alvo_usa_margem_sobre_o_preco(db_session):
    """custo / (1 - alvo), nao custo * (1 + alvo).

    Com custo 10 e alvo 35%: 10/0,65 = 15,38 -> arredonda 15,90 -> margem
    real (15,90-10)/15,90 = 37,1%. O markup daria 13,50, que e margem de
    25,9% -- a tela anunciaria um alvo que nao cumpre.
    """
    produto = _produto(db_session, custo="10.00", preco="12.00")

    preco, margem = price_service.preco_para_margem_alvo(
        produto, margem_alvo=Decimal("0.35")
    )

    assert preco == Decimal("15.90")
    assert margem >= Decimal("0.35")


def test_margem_resultante_e_recalculada_do_preco_arredondado(db_session):
    produto = _produto(db_session, custo="10.00", preco="12.00")

    preco, margem = price_service.preco_para_margem_alvo(
        produto, margem_alvo=Decimal("0.35")
    )

    assert margem == (preco - produto.custo) / preco


def test_preco_para_margem_alvo_sem_custo(db_session):
    produto = _produto(db_session, custo=None, preco="12.00")
    assert price_service.preco_para_margem_alvo(produto) is None


def test_margem_atual_bate_com_a_formula_das_regras_de_ia(db_session):
    """Se estas duas divergirem, a tela de precificacao e a de promocoes
    mostram margens diferentes pro mesmo produto."""
    from app.ai.rules import calcular_sinais
    from app.models.estoque import Estoque

    produto = _produto(db_session, custo="10.00", preco="16.00")
    db_session.add(Estoque(produto_id=produto.id, quantidade=5))
    db_session.commit()

    sinais = calcular_sinais(db_session, produto)
    assert float(price_service.margem_atual(produto)) == pytest.approx(sinais.margem, abs=1e-4)


# --- alterar_preco_normal --------------------------------------------------


def test_alterar_preco_normal_grava_historico(db_session):
    produto = _produto(db_session, preco="12.00")

    price_service.alterar_preco_normal(db_session, produto.id, Decimal("15.90"), alterado_por=7)

    historico = db_session.query(HistoricoPreco).all()
    assert len(historico) == 1
    assert historico[0].tipo_alteracao == TipoAlteracaoPreco.MANUAL
    assert historico[0].preco_anterior == Decimal("12.00")
    assert historico[0].preco_novo == Decimal("15.90")
    assert historico[0].alterado_por == 7
    assert produto.preco_normal == Decimal("15.90")


def test_preco_igual_nao_gera_evento_de_historico(db_session):
    """Sem esta guarda, todo PUT /produtos que edita so o nome poluiria o
    historico com um evento de preco que nunca aconteceu."""
    produto = _produto(db_session, preco="12.00")

    price_service.alterar_preco_normal(db_session, produto.id, Decimal("12.00"))

    assert db_session.query(HistoricoPreco).count() == 0


def test_preco_nao_positivo_e_recusado(db_session):
    produto = _produto(db_session, preco="12.00")

    with pytest.raises(PrecoNaoPositivoError):
        price_service.alterar_preco_normal(db_session, produto.id, Decimal("0"))

    assert produto.preco_normal == Decimal("12.00")
    assert db_session.query(HistoricoPreco).count() == 0


def test_recusa_reprecificar_produto_em_promocao(db_session):
    """Uma linha `manual` no meio da promocao viraria o fim dela para o
    LEAD de `analytics_service.janelas_promocoes`, truncando a janela e
    corrompendo o efeito medido -- sem quebrar teste nenhum."""
    produto = _produto(db_session, preco="12.00", promocao_ativa=True)

    with pytest.raises(PromocaoJaAtivaError) as erro:
        price_service.alterar_preco_normal(db_session, produto.id, Decimal("15.90"))

    assert erro.value.codigo == "promocao_ja_ativa"
    assert produto.preco_normal == Decimal("12.00")
    assert db_session.query(HistoricoPreco).count() == 0


# --- listagem de margem defasada ------------------------------------------


def test_lista_so_quem_esta_abaixo_do_alvo(db_session):
    abaixo = _produto(db_session, custo="10.00", preco="12.00")  # margem 16,7%
    db_session.add(Produto(nome="Acima", preco_normal=Decimal("20.00"), custo=Decimal("10.00")))
    db_session.commit()

    resultado = price_service.produtos_com_margem_defasada(
        db_session, margem_alvo=Decimal("0.35")
    )

    assert [i["produto_id"] for i in resultado["itens"]] == [abaixo.id]
    assert resultado["total_abaixo_do_alvo"] == 1


def test_conta_produtos_sem_custo_em_vez_de_ignorar(db_session):
    _produto(db_session, custo=None, preco="12.00")

    resultado = price_service.produtos_com_margem_defasada(db_session)

    assert resultado["itens"] == []
    assert resultado["produtos_sem_custo"] == 1


def test_margem_negativa_vem_primeiro(db_session):
    """Produto vendido abaixo do custo e o caso que precisa de decisao
    hoje, nao o que esta 2 pontos abaixo do alvo."""
    _produto(db_session, custo="10.00", preco="14.00")  # margem 28,6%
    prejuizo = _produto(db_session, custo="10.00", preco="8.00")  # margem -25%

    resultado = price_service.produtos_com_margem_defasada(
        db_session, margem_alvo=Decimal("0.35")
    )

    assert resultado["itens"][0]["produto_id"] == prejuizo.id
    assert resultado["itens"][0]["margem_atual"] < 0


def test_produto_inativo_fica_de_fora(db_session):
    produto = _produto(db_session, custo="10.00", preco="12.00")
    produto.ativo = False
    db_session.commit()

    assert price_service.produtos_com_margem_defasada(db_session)["itens"] == []


# --- API -------------------------------------------------------------------


def test_endpoint_margem_defasada(auth_client):
    _criar_produto_api(auth_client, custo="18.00", preco="19.95")

    corpo = auth_client.get("/precos/margem-defasada", params={"margem_alvo": 35}).json()

    assert corpo["margem_alvo"] == pytest.approx(0.35)
    assert len(corpo["itens"]) == 1
    assert corpo["itens"][0]["preco_sugerido"] == "27.90"


def test_endpoint_reprecificar(auth_client):
    produto = _criar_produto_api(auth_client, custo="18.00")

    resposta = auth_client.post(
        f"/precos/{produto['id']}/reprecificar", json={"preco_novo": "27.90"}
    )
    assert resposta.status_code == 200
    assert resposta.json()["preco_normal"] == "27.90"

    historico = auth_client.get("/historico-precos").json()
    assert len(historico) == 1
    assert historico[0]["tipo_alteracao"] == "manual"


def test_endpoint_reprecificar_produto_inexistente(auth_client):
    assert auth_client.post("/precos/999/reprecificar", json={"preco_novo": "10.00"}).status_code == 404


def test_endpoint_reprecificar_exige_autenticacao(client):
    assert client.post("/precos/1/reprecificar", json={"preco_novo": "10.00"}).status_code == 401


# --- regressao: o ponto cego que existia antes ------------------------------


def test_put_produtos_alterando_preco_agora_aparece_no_historico(auth_client):
    """Antes desta mudanca, `PUT /produtos` gravava `preco_normal` com um
    `setattr` cego: a alteracao manual de preco -- justamente a que um humano
    decidiu -- era a unica que nao deixava rastro."""
    produto = _criar_produto_api(auth_client, preco="19.95")

    auth_client.put(f"/produtos/{produto['id']}", json={"preco_normal": "24.90"})

    historico = auth_client.get("/historico-precos").json()
    assert len(historico) == 1
    assert historico[0]["tipo_alteracao"] == "manual"
    assert historico[0]["preco_anterior"] == "19.95"
    assert historico[0]["preco_novo"] == "24.90"


def test_put_produtos_sem_mexer_no_preco_nao_gera_historico(auth_client):
    produto = _criar_produto_api(auth_client, preco="19.95")

    auth_client.put(f"/produtos/{produto['id']}", json={"nome": "Cola Pano Extra"})

    assert auth_client.get("/historico-precos").json() == []
