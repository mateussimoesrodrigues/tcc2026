def _criar_produto(auth_client, preco_normal="19.95"):
    return auth_client.post(
        "/produtos",
        json={
            "nome": "Cola Pano",
            "codigo": "7896576331634",
            "preco_normal": preco_normal,
            "quantidade_inicial": 10,
        },
    ).json()


def test_criar_display_exige_login(client):
    resposta = client.post("/displays", json={"nome": "Prateleira 1"})
    assert resposta.status_code == 401


def test_criar_display_devolve_token_uma_vez(auth_client):
    resposta = auth_client.post("/displays", json={"nome": "Prateleira 1"})
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["nome"] == "Prateleira 1"
    assert corpo["produto_id"] is None
    assert len(corpo["token"]) >= 32

    # GET nao devolve o token de volta (so existe na resposta de criacao).
    listagem = auth_client.get("/displays").json()
    assert "token" not in listagem[0]


def test_sincronizar_sem_produto_vinculado(auth_client, client):
    token = auth_client.post("/displays", json={"nome": "Prateleira 1"}).json()["token"]

    resposta = client.post("/displays/sincronizar", headers={"X-Display-Token": token})
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["tem_produto"] is False
    assert corpo["produto_id"] is None
    assert corpo["proximo_sync_em_segundos"] > 0


def test_sincronizar_com_produto_vinculado_devolve_preco_vigente(auth_client, client):
    produto = _criar_produto(auth_client)
    display = auth_client.post("/displays", json={"nome": "Prateleira 1", "produto_id": produto["id"]}).json()

    resposta = client.post(
        "/displays/sincronizar",
        headers={"X-Display-Token": display["token"]},
        json={"bateria_pct": 87, "rssi_dbm": -62, "mac": "AA:BB:CC:DD:EE:FF"},
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["tem_produto"] is True
    assert corpo["produto_id"] == produto["id"]
    assert corpo["preco_vigente"] == "19.95"
    assert corpo["promocao_ativa"] is False

    # Telemetria foi gravada no registro do display.
    detalhe = auth_client.get(f"/displays/{display['id']}").json()
    assert detalhe["bateria_pct"] == 87
    assert detalhe["rssi_dbm"] == -62
    assert detalhe["mac_reportado"] == "AA:BB:CC:DD:EE:FF"
    assert detalhe["ultima_sincronizacao_em"] is not None


def test_sincronizar_com_token_invalido_retorna_401(client):
    resposta = client.post("/displays/sincronizar", headers={"X-Display-Token": "token-inexistente"})
    assert resposta.status_code == 401


def test_reatribuir_display_a_outro_produto(auth_client, client):
    produto1 = _criar_produto(auth_client, preco_normal="19.95")
    produto2 = auth_client.post(
        "/produtos",
        json={"nome": "Fita Adesiva", "codigo": "7896576339999", "preco_normal": "9.90", "quantidade_inicial": 5},
    ).json()
    display = auth_client.post("/displays", json={"nome": "Prateleira 1", "produto_id": produto1["id"]}).json()

    auth_client.put(f"/displays/{display['id']}", json={"produto_id": produto2["id"]})

    resposta = client.post("/displays/sincronizar", headers={"X-Display-Token": display["token"]})
    assert resposta.json()["produto_id"] == produto2["id"]
    assert resposta.json()["preco_vigente"] == "9.90"


def test_display_desativado_nao_sincroniza_mais(auth_client, client):
    display = auth_client.post("/displays", json={"nome": "Prateleira 1"}).json()

    auth_client.delete(f"/displays/{display['id']}")

    resposta = client.post("/displays/sincronizar", headers={"X-Display-Token": display["token"]})
    assert resposta.status_code == 401


def test_regenerar_token_invalida_o_anterior(auth_client, client):
    display = auth_client.post("/displays", json={"nome": "Prateleira 1"}).json()
    token_antigo = display["token"]

    novo = auth_client.post(f"/displays/{display['id']}/token").json()["token"]
    assert novo != token_antigo

    assert client.post("/displays/sincronizar", headers={"X-Display-Token": token_antigo}).status_code == 401
    assert client.post("/displays/sincronizar", headers={"X-Display-Token": novo}).status_code == 200


def test_display_inexistente_retorna_404(auth_client):
    assert auth_client.get("/displays/999").status_code == 404
    assert auth_client.put("/displays/999", json={"nome": "X"}).status_code == 404
    assert auth_client.delete("/displays/999").status_code == 404
    assert auth_client.post("/displays/999/token").status_code == 404
