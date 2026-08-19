"""Fixtures compartilhadas: banco SQLite em memoria isolado por teste (nao
toca no Neon), com o dependency override do get_db do FastAPI."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session):
    """Client SEM autenticacao -- usado pra testar os proprios endpoints
    de auth (login, etc) e os casos de 401/403."""
    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_client(client, db_session):
    """Client autenticado como um funcionario admin de teste -- usado nos
    testes de produtos/estoque, que agora exigem login.

    O funcionario e inserido direto no banco de teste (nao via
    POST /auth/funcionarios, que exige um admin ja logado -- problema do
    "ovo e a galinha" que no sistema real e resolvido pelo funcionario
    admin criado no seed)."""
    from app.core.security import hash_senha
    from app.models.funcionario import Funcionario, PapelFuncionario

    db_session.add(
        Funcionario(
            nome="Admin Teste",
            email="admin@teste.com",
            senha_hash=hash_senha("senha123"),
            papel=PapelFuncionario.ADMIN,
        )
    )
    db_session.commit()

    login = client.post(
        "/auth/login",
        data={"username": "admin@teste.com", "password": "senha123"},
    )
    token = login.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
