"""Conferencia do pedido no caixa -- fecha o ciclo que o checkout deixava
em aberto.

O checkout e publico (so o header X-Cart-Session); a conferencia e da area
do funcionario. Por isso os testes usam os dois clients: `client` pra
gerar o pedido como cliente e `auth_client` pra conferir como funcionario.
Nota: as duas fixtures compartilham a mesma instancia de TestClient, entao
autenticar depois de gerar o pedido e o caminho natural.
"""
from datetime import UTC, datetime, timedelta

from app.models.estoque import Estoque
from app.models.pedido import Pedido, StatusPedido
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


def _gerar_pedido(client, db_session, *, quantidade=2, preco="10.00", codigo="1111111111111") -> str:
    """Roda o fluxo real do cliente ate o checkout e devolve o numero do
    pedido -- o mesmo numero que o cliente leva ao caixa."""
    produto = _criar_produto(db_session, preco=preco, codigo=codigo)
    sessao_id = client.post("/carrinho/sessoes").json()["sessao_id"]
    headers = {"X-Cart-Session": sessao_id}
    client.post("/carrinho/itens", json={"produto_id": produto.id, "quantidade": quantidade}, headers=headers)
    resposta = client.post("/checkout", headers=headers)
    assert resposta.status_code == 201
    return resposta.json()["numero_pedido"]


def test_pedidos_sem_token_retorna_401(client):
    assert client.get("/pedidos").status_code == 401
    assert client.get("/pedidos/123456").status_code == 401


def test_buscar_pedido_por_numero_retorna_itens(auth_client, db_session):
    numero = _gerar_pedido(auth_client, db_session, quantidade=3, preco="12.50")

    resposta = auth_client.get(f"/pedidos/{numero}")
    assert resposta.status_code == 200
    corpo = resposta.json()

    assert corpo["numero_pedido"] == numero
    assert corpo["status"] == "gerado"
    assert corpo["expirado"] is False
    assert corpo["conferido_em"] is None
    assert len(corpo["itens"]) == 1
    item = corpo["itens"][0]
    assert item["quantidade"] == 3
    assert item["nome_produto_snapshot"] == "Cola Pano"
    assert float(item["subtotal"]) == 37.50
    assert float(corpo["valor_total"]) == 37.50


def test_numero_inexistente_retorna_404(auth_client):
    assert auth_client.get("/pedidos/000000").status_code == 404


def test_conferir_marca_status_e_auditoria(auth_client, db_session):
    numero = _gerar_pedido(auth_client, db_session)

    resposta = auth_client.post(f"/pedidos/{numero}/conferir")
    assert resposta.status_code == 200
    corpo = resposta.json()

    assert corpo["estava_expirado"] is False
    assert corpo["pedido"]["status"] == "conferido_no_caixa"
    assert corpo["pedido"]["conferido_em"] is not None
    assert corpo["pedido"]["conferido_por_nome"] == "Admin Teste"

    db_session.expire_all()
    pedido = db_session.query(Pedido).filter(Pedido.numero_pedido == numero).one()
    assert pedido.status == StatusPedido.CONFERIDO_NO_CAIXA
    assert pedido.conferido_por is not None


def test_conferir_duas_vezes_retorna_409(auth_client, db_session):
    numero = _gerar_pedido(auth_client, db_session)
    auth_client.post(f"/pedidos/{numero}/conferir")

    resposta = auth_client.post(f"/pedidos/{numero}/conferir")
    assert resposta.status_code == 409
    detalhe = resposta.json()["detail"]
    assert detalhe["codigo"] == "pedido_ja_conferido"
    assert detalhe["detalhes"]["conferido_por_nome"] == "Admin Teste"


def test_pedido_expirado_ainda_pode_ser_conferido_com_aviso(auth_client, db_session):
    """Cliente que demorou na fila nao pode perder a compra -- a expiracao
    e um aviso, nao um bloqueio."""
    numero = _gerar_pedido(auth_client, db_session)
    pedido = db_session.query(Pedido).filter(Pedido.numero_pedido == numero).one()
    pedido.expira_em = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
    db_session.commit()

    resposta = auth_client.post(f"/pedidos/{numero}/conferir")
    assert resposta.status_code == 200
    assert resposta.json()["estava_expirado"] is True
    assert resposta.json()["pedido"]["status"] == "conferido_no_caixa"


def test_buscar_pedido_vencido_marca_expirado(auth_client, db_session):
    numero = _gerar_pedido(auth_client, db_session)
    pedido = db_session.query(Pedido).filter(Pedido.numero_pedido == numero).one()
    pedido.expira_em = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
    db_session.commit()

    assert auth_client.get(f"/pedidos/{numero}").json()["expirado"] is True


def test_expirar_agora_marca_pedidos_vencidos(auth_client, db_session):
    numero = _gerar_pedido(auth_client, db_session)
    pedido = db_session.query(Pedido).filter(Pedido.numero_pedido == numero).one()
    pedido.expira_em = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30)
    db_session.commit()

    resposta = auth_client.post("/pedidos/expirar-agora")
    assert resposta.status_code == 200
    assert resposta.json()["pedidos_expirados"] == 1

    db_session.expire_all()
    assert db_session.query(Pedido).filter(Pedido.numero_pedido == numero).one().status == StatusPedido.EXPIRADO


def test_expirar_nao_devolve_estoque(auth_client, db_session):
    """A mercadoria ja saiu da prateleira no checkout: devolver estoque
    automaticamente criaria divergencia com a prateleira real."""
    numero = _gerar_pedido(auth_client, db_session, quantidade=2)
    estoque_apos_checkout = db_session.query(Estoque).one().quantidade

    pedido = db_session.query(Pedido).filter(Pedido.numero_pedido == numero).one()
    pedido.expira_em = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30)
    db_session.commit()
    auth_client.post("/pedidos/expirar-agora")

    db_session.expire_all()
    assert db_session.query(Estoque).one().quantidade == estoque_apos_checkout


def test_conferir_pedido_expirado_pelo_job_ainda_funciona(auth_client, db_session):
    numero = _gerar_pedido(auth_client, db_session)
    pedido = db_session.query(Pedido).filter(Pedido.numero_pedido == numero).one()
    pedido.expira_em = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30)
    db_session.commit()
    auth_client.post("/pedidos/expirar-agora")

    resposta = auth_client.post(f"/pedidos/{numero}/conferir")
    assert resposta.status_code == 200
    assert resposta.json()["pedido"]["status"] == "conferido_no_caixa"


def test_listar_pedidos_filtra_por_status(auth_client, db_session):
    numero_a = _gerar_pedido(auth_client, db_session, preco="10.00", codigo="1111111111111")
    _gerar_pedido(auth_client, db_session, preco="20.00", codigo="2222222222222")
    auth_client.post(f"/pedidos/{numero_a}/conferir")

    todos = auth_client.get("/pedidos").json()
    assert len(todos) == 2

    conferidos = auth_client.get("/pedidos?status_filtro=conferido_no_caixa").json()
    assert len(conferidos) == 1
    assert conferidos[0]["numero_pedido"] == numero_a
    assert conferidos[0]["conferido_em"] is not None

    gerados = auth_client.get("/pedidos?status_filtro=gerado").json()
    assert len(gerados) == 1
