"""Entrada de mercadoria: soma no estoque, registra o custo pago e reancora
`produto.custo` pela media ponderada.

O custo importa alem do estoque: e ele que alimenta
`price_service.piso_de_preco`, o piso que impede a IA de sugerir venda no
prejuizo. Custo errado = piso errado.
"""
from decimal import Decimal

import pytest

from app.services.stock_service import custo_medio_ponderado


def _criar_produto(auth_client, *, codigo="7896576331634", nome="Cola Pano", custo=None, quantidade=0):
    corpo = {
        "nome": nome,
        "codigo": codigo,
        "preco_normal": "19.95",
        "quantidade_inicial": quantidade,
    }
    if custo is not None:
        corpo["custo"] = custo
    return auth_client.post("/produtos", json=corpo).json()


# --- media ponderada (funcao pura) ----------------------------------------


@pytest.mark.parametrize(
    "custo_atual,estoque_atual,custo_unitario,quantidade,esperado",
    [
        # Primeira compra registrada: nao ha com o que ponderar.
        (None, 0, Decimal("5.20"), 28, Decimal("5.20")),
        (None, 40, Decimal("5.20"), 28, Decimal("5.20")),
        # 28 un a 5,20 + 12 un a 6,00 = 217,60 / 40 = 5,44
        (Decimal("5.20"), 28, Decimal("6.00"), 12, Decimal("5.44")),
        # Estoque zerado: idem, nao ha unidade anterior para ponderar.
        (Decimal("5.20"), 0, Decimal("6.00"), 12, Decimal("6.00")),
        # Estoque negativo (possivel via ajuste): ponderar produziria um
        # custo sem sentido, entao cai no custo da entrada.
        (Decimal("5.20"), -3, Decimal("6.00"), 12, Decimal("6.00")),
        # Compra mais barata puxa a media para baixo, sem zerar o historico.
        (Decimal("10.00"), 10, Decimal("8.00"), 10, Decimal("9.00")),
    ],
)
def test_custo_medio_ponderado(custo_atual, estoque_atual, custo_unitario, quantidade, esperado):
    assert custo_medio_ponderado(custo_atual, estoque_atual, custo_unitario, quantidade) == esperado


# --- endpoint --------------------------------------------------------------


def test_entrada_soma_estoque_e_reancora_custo(auth_client):
    produto = _criar_produto(auth_client, custo="5.20", quantidade=28)

    resposta = auth_client.post(
        "/estoque/entradas",
        json={
            "observacao": "NF 1234 - Distribuidora Central",
            "itens": [{"produto_id": produto["id"], "quantidade": 12, "custo_unitario": "6.00"}],
        },
    )
    assert resposta.status_code == 201

    corpo = resposta.json()
    item = corpo["itens"][0]
    assert item["estoque_anterior"] == 28
    assert item["estoque_resultante"] == 40
    assert item["custo_anterior"] == "5.20"
    assert item["custo_resultante"] == "5.44"
    assert item["subtotal"] == "72.00"
    assert corpo["valor_total"] == "72.00"

    atualizado = auth_client.get(f"/produtos/{produto['id']}").json()
    assert atualizado["custo"] == "5.44"
    assert atualizado["estoque"]["quantidade"] == 40


def test_entrada_grava_custo_pago_no_razao(auth_client):
    produto = _criar_produto(auth_client, quantidade=0)

    auth_client.post(
        "/estoque/entradas",
        json={
            "observacao": "NF 77",
            "itens": [{"produto_id": produto["id"], "quantidade": 5, "custo_unitario": "3.50"}],
        },
    )

    movimentacoes = auth_client.get(f"/estoque/{produto['id']}/movimentacoes").json()
    assert movimentacoes[0]["tipo"] == "entrada"
    assert movimentacoes[0]["quantidade"] == 5
    assert movimentacoes[0]["custo_unitario"] == "3.50"
    assert movimentacoes[0]["observacao"] == "NF 77"


def test_entrada_com_varios_itens(auth_client):
    a = _criar_produto(auth_client, codigo="7896576331634", nome="Cola Pano", quantidade=0)
    b = _criar_produto(auth_client, codigo="7891234567895", nome="Tinta PVA", quantidade=0)

    corpo = auth_client.post(
        "/estoque/entradas",
        json={
            "itens": [
                {"produto_id": a["id"], "quantidade": 10, "custo_unitario": "2.00"},
                {"produto_id": b["id"], "quantidade": 3, "custo_unitario": "10.00"},
            ],
        },
    ).json()

    assert len(corpo["itens"]) == 2
    assert corpo["valor_total"] == "50.00"  # 10*2 + 3*10


def test_produto_repetido_na_mesma_entrada_pondera_em_sequencia(auth_client):
    """Nao ha agrupamento previo: as linhas sao aplicadas em ordem e cada uma
    pondera contra o resultado da anterior, o que da a mesma media do
    lancamento agrupado."""
    produto = _criar_produto(auth_client, quantidade=0)

    auth_client.post(
        "/estoque/entradas",
        json={
            "itens": [
                {"produto_id": produto["id"], "quantidade": 10, "custo_unitario": "5.00"},
                {"produto_id": produto["id"], "quantidade": 10, "custo_unitario": "7.00"},
            ],
        },
    )

    atualizado = auth_client.get(f"/produtos/{produto['id']}").json()
    assert atualizado["custo"] == "6.00"
    assert atualizado["estoque"]["quantidade"] == 20


def test_entrada_e_atomica(auth_client):
    """Um produto inexistente no meio da lista nao pode deixar meio caminhao
    lancado."""
    produto = _criar_produto(auth_client, custo="5.00", quantidade=10)

    resposta = auth_client.post(
        "/estoque/entradas",
        json={
            "itens": [
                {"produto_id": produto["id"], "quantidade": 7, "custo_unitario": "9.00"},
                {"produto_id": 9999, "quantidade": 1, "custo_unitario": "1.00"},
            ],
        },
    )
    assert resposta.status_code == 404

    intacto = auth_client.get(f"/produtos/{produto['id']}").json()
    assert intacto["estoque"]["quantidade"] == 10
    assert intacto["custo"] == "5.00"


def test_entrada_sem_itens_e_recusada(auth_client):
    assert auth_client.post("/estoque/entradas", json={"itens": []}).status_code == 422


def test_entrada_com_quantidade_nao_positiva_e_recusada(auth_client):
    produto = _criar_produto(auth_client)

    resposta = auth_client.post(
        "/estoque/entradas",
        json={"itens": [{"produto_id": produto["id"], "quantidade": 0, "custo_unitario": "1.00"}]},
    )
    assert resposta.status_code == 422


def test_listar_entradas(auth_client):
    produto = _criar_produto(auth_client, quantidade=0)
    auth_client.post(
        "/estoque/entradas",
        json={
            "observacao": "NF 500",
            "itens": [{"produto_id": produto["id"], "quantidade": 4, "custo_unitario": "1.25"}],
        },
    )

    entradas = auth_client.get("/estoque/entradas").json()
    assert len(entradas) == 1
    assert entradas[0]["produto_nome"] == "Cola Pano"
    assert entradas[0]["quantidade"] == 4
    assert entradas[0]["custo_unitario"] == "1.25"
    assert entradas[0]["observacao"] == "NF 500"


def test_entradas_exige_autenticacao(client):
    assert client.get("/estoque/entradas").status_code == 401
