def test_criar_produto_sem_preco_e_sem_historico_falha(client):
    resposta = client.post(
        "/produtos",
        json={"nome": "Cola Nova", "codigo": "7890000000001"},
    )
    assert resposta.status_code == 422


def test_criar_e_listar_produto(client):
    resposta = client.post(
        "/produtos",
        json={
            "nome": "Cola Pano",
            "marca": "Gliart",
            "tamanho": "100g",
            "codigo": "7896576331634",
            "preco_normal": "19.95",
            "quantidade_inicial": 20,
        },
    )
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["nome"] == "Cola Pano"
    assert corpo["preco_vigente"] == "19.95"
    assert corpo["estoque"]["quantidade"] == 20
    assert len(corpo["codigos"]) == 1

    listagem = client.get("/produtos").json()
    assert len(listagem) == 1


def test_criar_produto_com_codigo_duplicado_retorna_409(client):
    dados = {"nome": "Cola Pano", "codigo": "7896576331634", "preco_normal": "19.95"}
    assert client.post("/produtos", json=dados).status_code == 201

    resposta = client.post(
        "/produtos", json={"nome": "Outro Produto", "codigo": "7896576331634", "preco_normal": "10.00"}
    )
    assert resposta.status_code == 409


def test_criar_produto_reaproveita_preco_de_cadastro_anterior(client):
    client.post(
        "/produtos",
        json={"nome": "Cola Pano", "marca": "Gliart", "tamanho": "100g", "codigo": "7896576331634", "preco_normal": "19.95"},
    )
    # mesmo nome/marca/tamanho, codigo diferente (novo lote), sem informar preco
    resposta = client.post(
        "/produtos",
        json={"nome": "Cola Pano", "marca": "Gliart", "tamanho": "100g", "codigo": "7896576331999"},
    )
    assert resposta.status_code == 201
    assert resposta.json()["preco_normal"] == "19.95"


def test_lookup_por_codigo(client):
    client.post("/produtos", json={"nome": "Cola Pano", "codigo": "7896576331634", "preco_normal": "19.95"})

    encontrado = client.get("/produtos/codigo/7896576331634").json()
    assert encontrado["encontrado"] is True
    assert encontrado["produto"]["nome"] == "Cola Pano"

    nao_encontrado = client.get("/produtos/codigo/0000000000000").json()
    assert nao_encontrado["encontrado"] is False
    assert nao_encontrado["produto"] is None


def test_desativar_produto_some_da_listagem_padrao(client):
    criado = client.post(
        "/produtos", json={"nome": "Cola Pano", "codigo": "7896576331634", "preco_normal": "19.95"}
    ).json()

    resposta = client.delete(f"/produtos/{criado['id']}")
    assert resposta.status_code == 200
    assert resposta.json()["ativo"] is False

    assert client.get("/produtos").json() == []
    assert len(client.get("/produtos", params={"somente_ativos": False}).json()) == 1
