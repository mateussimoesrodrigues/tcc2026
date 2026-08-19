"""Fluxo do cliente: sessao de carrinho, itens, checkout. Cliente e area
publica -- usa `client` (sem token de funcionario), so com o header
X-Cart-Session."""
import pytest

from app.models.categoria import Categoria
from app.models.estoque import Estoque
from app.models.produto import Produto
from app.models.produto_codigo import ProdutoCodigo, TipoCodigo


def _criar_produto(db_session, nome="Cola Pano", preco="10.00", quantidade=5, codigo="1111111111111"):
    produto = Produto(nome=nome, preco_normal=preco)
    db_session.add(produto)
    db_session.flush()
    db_session.add(ProdutoCodigo(produto_id=produto.id, tipo=TipoCodigo.EAN13, codigo=codigo, principal=True))
    db_session.add(Estoque(produto_id=produto.id, quantidade=quantidade))
    db_session.commit()
    db_session.refresh(produto)
    return produto


def _abrir_sessao(client) -> str:
    resposta = client.post("/carrinho/sessoes")
    assert resposta.status_code == 201
    return resposta.json()["sessao_id"]


def test_criar_sessao_e_carrinho_vazio(client):
    sessao_id = _abrir_sessao(client)
    resposta = client.get("/carrinho", headers={"X-Cart-Session": sessao_id})
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["itens"] == []
    assert corpo["total"] == "0.00" or float(corpo["total"]) == 0


def test_carrinho_sem_header_retorna_422(client):
    assert client.get("/carrinho").status_code == 422


def test_sessao_inexistente_retorna_404(client):
    resposta = client.get("/carrinho", headers={"X-Cart-Session": "sessao-que-nao-existe"})
    assert resposta.status_code == 404


def test_adicionar_item_e_somar_quantidade_em_duplicata(client, db_session):
    produto = _criar_produto(db_session)
    sessao_id = _abrir_sessao(client)
    headers = {"X-Cart-Session": sessao_id}

    r1 = client.post("/carrinho/itens", json={"produto_id": produto.id, "quantidade": 2}, headers=headers)
    assert r1.status_code == 201
    assert len(r1.json()["itens"]) == 1
    assert r1.json()["itens"][0]["quantidade"] == 2

    r2 = client.post("/carrinho/itens", json={"produto_id": produto.id, "quantidade": 3}, headers=headers)
    assert r2.status_code == 201
    assert len(r2.json()["itens"]) == 1  # upsert, nao duplica linha
    assert r2.json()["itens"][0]["quantidade"] == 5
    assert float(r2.json()["total"]) == pytest.approx(50.0)


def test_atualizar_quantidade_para_zero_remove_item(client, db_session):
    produto = _criar_produto(db_session)
    sessao_id = _abrir_sessao(client)
    headers = {"X-Cart-Session": sessao_id}

    client.post("/carrinho/itens", json={"produto_id": produto.id, "quantidade": 1}, headers=headers)
    resposta = client.put(f"/carrinho/itens/{produto.id}", json={"quantidade": 0}, headers=headers)
    assert resposta.status_code == 200
    assert resposta.json()["itens"] == []


def test_checkout_sem_header_retorna_422(client):
    assert client.post("/checkout").status_code == 422


def test_checkout_carrinho_vazio_retorna_400(client):
    sessao_id = _abrir_sessao(client)
    resposta = client.post("/checkout", headers={"X-Cart-Session": sessao_id})
    assert resposta.status_code == 400


def test_checkout_estoque_insuficiente_nao_altera_nada(client, db_session):
    produto = _criar_produto(db_session, quantidade=2)
    sessao_id = _abrir_sessao(client)
    headers = {"X-Cart-Session": sessao_id}

    client.post("/carrinho/itens", json={"produto_id": produto.id, "quantidade": 5}, headers=headers)
    resposta = client.post("/checkout", headers=headers)
    assert resposta.status_code == 409
    assert resposta.json()["detail"]["itens"][0]["produto_id"] == produto.id

    db_session.refresh(produto)
    assert produto.estoque.quantidade == 2  # nao decrementou nada

    # carrinho continua intacto (checkout falhou, item nao some)
    carrinho = client.get("/carrinho", headers=headers).json()
    assert len(carrinho["itens"]) == 1


def test_checkout_com_sucesso_decrementa_estoque_e_finaliza_sessao(client, db_session):
    produto = _criar_produto(db_session, preco="20.00", quantidade=10)
    sessao_id = _abrir_sessao(client)
    headers = {"X-Cart-Session": sessao_id}

    client.post("/carrinho/itens", json={"produto_id": produto.id, "quantidade": 3}, headers=headers)
    resposta = client.post("/checkout", headers=headers)
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert len(corpo["numero_pedido"]) == 6
    assert float(corpo["valor_total"]) == pytest.approx(60.0)

    db_session.refresh(produto)
    assert produto.estoque.quantidade == 7

    # a rota /estoque/{id}/movimentacoes e do funcionario (exige login);
    # aqui confirmamos a movimentacao gravada direto no banco de teste
    from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
    from sqlalchemy import select

    mov = db_session.execute(
        select(MovimentacaoEstoque).where(MovimentacaoEstoque.produto_id == produto.id)
    ).scalar_one()
    assert mov.tipo == TipoMovimentacao.SAIDA_VENDA
    assert mov.quantidade == 3
    assert mov.pedido_id is not None

    # sessao finalizada -> checkout de novo falha
    resposta2 = client.post("/checkout", headers=headers)
    assert resposta2.status_code == 404


def test_catalogo_publico_por_codigo_sem_auth_e_sem_estoque_custo(client, db_session):
    produto = _criar_produto(db_session, nome="Verniz Vitral", preco="79.95", codigo="7891153006154")

    resposta = client.get(f"/catalogo/codigo/{produto.codigos[0].codigo}")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["encontrado"] is True
    assert corpo["produto"]["nome"] == "Verniz Vitral"
    assert "estoque" not in corpo["produto"]
    assert "custo" not in corpo["produto"]


def test_catalogo_publico_codigo_nao_encontrado(client):
    resposta = client.get("/catalogo/codigo/codigo-inexistente")
    assert resposta.status_code == 200
    assert resposta.json() == {"encontrado": False, "produto": None}
