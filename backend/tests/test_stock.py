def _criar_produto(auth_client, quantidade_inicial=10):
    return auth_client.post(
        "/produtos",
        json={
            "nome": "Cola Pano",
            "codigo": "7896576331634",
            "preco_normal": "19.95",
            "quantidade_inicial": quantidade_inicial,
        },
    ).json()


def test_listar_estoque(auth_client):
    _criar_produto(auth_client, quantidade_inicial=10)

    linhas = auth_client.get("/estoque").json()
    assert len(linhas) == 1
    assert linhas[0]["quantidade"] == 10
    assert linhas[0]["estoque_baixo"] is False


def test_ajuste_entrada_soma_quantidade(auth_client):
    produto = _criar_produto(auth_client, quantidade_inicial=10)

    resposta = auth_client.post(f"/estoque/{produto['id']}/ajuste", json={"quantidade": 5, "tipo": "entrada"})
    assert resposta.status_code == 200
    assert resposta.json()["quantidade"] == 15

    # A listagem vem da mais recente para a mais antiga, e a primeira linha
    # do razao e o saldo inicial do cadastro -- por isso o ajuste e
    # `movimentacoes[0]` e nao a unica linha.
    movimentacoes = auth_client.get(f"/estoque/{produto['id']}/movimentacoes").json()
    assert movimentacoes[0]["quantidade"] == 5
    assert movimentacoes[0]["tipo"] == "entrada"


def test_saldo_inicial_do_cadastro_entra_no_razao(auth_client):
    """Sem esta movimentacao a soma do razao nao fecharia com
    `estoque.quantidade` para todo produto recem-cadastrado."""
    produto = _criar_produto(auth_client, quantidade_inicial=10)

    movimentacoes = auth_client.get(f"/estoque/{produto['id']}/movimentacoes").json()
    assert len(movimentacoes) == 1
    assert movimentacoes[0]["tipo"] == "entrada"
    assert movimentacoes[0]["quantidade"] == 10
    assert movimentacoes[0]["observacao"] == "Saldo inicial do cadastro"


def test_cadastro_sem_estoque_inicial_nao_gera_movimentacao(auth_client):
    produto = _criar_produto(auth_client, quantidade_inicial=0)

    assert auth_client.get(f"/estoque/{produto['id']}/movimentacoes").json() == []


def test_ajuste_grava_o_motivo_da_baixa(auth_client):
    """Ajuste negativo sem motivo e um numero solto no razao: nao da pra
    distinguir quebra de erro de contagem depois."""
    produto = _criar_produto(auth_client, quantidade_inicial=10)

    auth_client.post(
        f"/estoque/{produto['id']}/ajuste",
        json={"quantidade": -2, "tipo": "ajuste", "observacao": "quebra na prateleira"},
    )

    movimentacoes = auth_client.get(f"/estoque/{produto['id']}/movimentacoes").json()
    assert movimentacoes[0]["quantidade"] == -2
    assert movimentacoes[0]["observacao"] == "quebra na prateleira"


def test_ajuste_negativo_gera_alerta_de_estoque_baixo(auth_client):
    produto = _criar_produto(auth_client, quantidade_inicial=10)

    auth_client.post(f"/estoque/{produto['id']}/ajuste", json={"quantidade": -7, "tipo": "ajuste"})

    linhas = auth_client.get("/estoque", params={"somente_baixo": True}).json()
    assert len(linhas) == 1
    assert linhas[0]["quantidade"] == 3
    assert linhas[0]["estoque_baixo"] is True


def test_ajuste_em_produto_inexistente_retorna_404(auth_client):
    resposta = auth_client.post("/estoque/999/ajuste", json={"quantidade": 1, "tipo": "entrada"})
    assert resposta.status_code == 404
