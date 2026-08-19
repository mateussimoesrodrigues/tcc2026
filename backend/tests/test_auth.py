def test_produtos_sem_token_retorna_401(client):
    assert client.get("/produtos").status_code == 401


def test_login_com_credenciais_invalidas_retorna_401(client):
    resposta = client.post("/auth/login", data={"username": "nao@existe.com", "password": "x"})
    assert resposta.status_code == 401


def test_login_e_me(auth_client):
    resposta = auth_client.get("/auth/me")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["email"] == "admin@teste.com"
    assert corpo["papel"] == "admin"


def test_produtos_com_token_valido_funciona(auth_client):
    assert auth_client.get("/produtos").status_code == 200


def test_admin_pode_criar_outro_funcionario(auth_client):
    resposta = auth_client.post(
        "/auth/funcionarios",
        json={"nome": "Operador", "email": "operador@teste.com", "senha": "senha123", "papel": "operador"},
    )
    assert resposta.status_code == 201
    assert resposta.json()["papel"] == "operador"


def test_operador_nao_pode_criar_funcionario(client, db_session):
    from app.core.security import hash_senha
    from app.models.funcionario import Funcionario, PapelFuncionario

    db_session.add(
        Funcionario(
            nome="Operador",
            email="operador@teste.com",
            senha_hash=hash_senha("senha123"),
            papel=PapelFuncionario.OPERADOR,
        )
    )
    db_session.commit()

    login = client.post("/auth/login", data={"username": "operador@teste.com", "password": "senha123"})
    client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})

    resposta = client.post(
        "/auth/funcionarios",
        json={"nome": "Outro", "email": "outro@teste.com", "senha": "senha123"},
    )
    assert resposta.status_code == 403
