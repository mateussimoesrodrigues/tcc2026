"""Fluxo completo do motor de promocoes via API: gerar-agora -> listar ->
aprovar/rejeitar. O LLM e sempre mockado (monkeypatch em
`promotion_service.gerar_sugestao_llm`) -- nunca bate em rede real."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.ai import llm_provider
from app.models.estoque import Estoque
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.produto import Produto
from app.models.promocao_sugestao import PromocaoSugestao


def _produto_parado(db_session, *, preco_normal="20.00", quantidade=10):
    produto = Produto(nome="Produto Parado", preco_normal=Decimal(preco_normal))
    db_session.add(produto)
    db_session.flush()
    db_session.add(Estoque(produto_id=produto.id, quantidade=quantidade))
    db_session.add(
        MovimentacaoEstoque(
            produto_id=produto.id,
            tipo=TipoMovimentacao.SAIDA_VENDA,
            quantidade=1,
            criado_em=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=60),
        )
    )
    db_session.commit()
    db_session.refresh(produto)
    return produto


def _mockar_llm_sucesso(monkeypatch, *, percentual="15", preco_sugerido="17.00", prioridade="alta"):
    def fake(sinais, *, client=None):
        return llm_provider.SugestaoLLM(
            percentual_desconto=Decimal(percentual),
            preco_sugerido=Decimal(preco_sugerido),
            justificativa="Produto parado ha bastante tempo sem vender.",
            prioridade=prioridade,
            modelo_usado="groq/teste-mock",
        )

    monkeypatch.setattr("app.services.promotion_service.gerar_sugestao_llm", fake)


def test_promocoes_sem_token_retorna_401(client):
    assert client.get("/promocoes").status_code == 401


def test_historico_precos_sem_token_retorna_401(client):
    assert client.get("/historico-precos").status_code == 401


def test_gerar_agora_sem_candidatos_retorna_vazio(auth_client):
    resposta = auth_client.post("/promocoes/gerar-agora")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["candidatos_avaliados"] == 0
    assert corpo["sugestoes_criadas"] == []


def test_gerar_agora_cria_sugestao_para_produto_parado(auth_client, db_session, monkeypatch):
    produto = _produto_parado(db_session)
    _mockar_llm_sucesso(monkeypatch)

    resposta = auth_client.post("/promocoes/gerar-agora")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["candidatos_avaliados"] == 1
    assert len(corpo["sugestoes_criadas"]) == 1
    assert corpo["avaliacoes"] == [{
        "produto_id": produto.id,
        "nome": produto.nome,
        "status": "criada",
        "motivo": None,
        "categoria": None,
    }]

    sugestao = corpo["sugestoes_criadas"][0]
    assert sugestao["produto_id"] == produto.id
    assert sugestao["status"] == "pendente"
    assert Decimal(sugestao["percentual_desconto_sugerido"]) == Decimal("15.00")
    assert sugestao["modelo_ia_usado"] == "groq/teste-mock"


def test_gerar_agora_nao_duplica_sugestao_pendente(auth_client, db_session, monkeypatch):
    _produto_parado(db_session)
    _mockar_llm_sucesso(monkeypatch)

    auth_client.post("/promocoes/gerar-agora")
    resposta2 = auth_client.post("/promocoes/gerar-agora")

    assert resposta2.json()["sugestoes_criadas"] == []
    assert resposta2.json()["avaliacoes"][0]["status"] == "ja_pendente"


def test_gerar_agora_ignora_sugestao_pendente_com_mais_de_24_horas(auth_client, db_session, monkeypatch):
    _produto_parado(db_session)
    _mockar_llm_sucesso(monkeypatch)
    auth_client.post("/promocoes/gerar-agora")

    sugestao = db_session.query(PromocaoSugestao).one()
    sugestao.criado_em = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=25)
    db_session.commit()

    resposta = auth_client.post("/promocoes/gerar-agora")

    assert resposta.status_code == 200
    assert len(resposta.json()["sugestoes_criadas"]) == 1
    assert resposta.json()["avaliacoes"][0]["status"] == "criada"


def test_gerar_agora_registra_falha_sem_travar(auth_client, db_session, monkeypatch):
    _produto_parado(db_session)

    def fake_falha(sinais, *, client=None):
        raise llm_provider.LLMIndisponivelError("groq: sem key; gemini: sem key")

    monkeypatch.setattr("app.services.promotion_service.gerar_sugestao_llm", fake_falha)

    resposta = auth_client.post("/promocoes/gerar-agora")
    corpo = resposta.json()
    assert corpo["sugestoes_criadas"] == []
    assert len(corpo["falhas"]) == 1
    assert corpo["falhas"][0]["motivo"]


def test_listar_sugestoes_filtra_por_status(auth_client, db_session, monkeypatch):
    _produto_parado(db_session)
    _mockar_llm_sucesso(monkeypatch)
    auth_client.post("/promocoes/gerar-agora")

    resposta = auth_client.get("/promocoes", params={"status_filtro": "pendente"})
    assert resposta.status_code == 200
    assert len(resposta.json()) == 1

    resposta_aprovadas = auth_client.get("/promocoes", params={"status_filtro": "aprovada"})
    assert resposta_aprovadas.json() == []


def test_listar_sugestoes_exibe_apenas_ultimas_24_horas(auth_client, db_session, monkeypatch):
    _produto_parado(db_session)
    _produto_parado(db_session)
    _mockar_llm_sucesso(monkeypatch)
    auth_client.post("/promocoes/gerar-agora")

    sugestoes = db_session.query(PromocaoSugestao).order_by(PromocaoSugestao.id).all()
    sugestoes[0].criado_em = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=25)
    db_session.commit()

    resposta = auth_client.get("/promocoes", params={"status_filtro": "pendente"})

    assert resposta.status_code == 200
    assert [sugestao["id"] for sugestao in resposta.json()] == [sugestoes[1].id]


def test_aprovar_sugestao_aplica_preco_e_grava_historico(auth_client, db_session, monkeypatch):
    produto = _produto_parado(db_session)
    _mockar_llm_sucesso(monkeypatch, percentual="15", preco_sugerido="17.00")
    auth_client.post("/promocoes/gerar-agora")
    sugestao_id = auth_client.get("/promocoes").json()[0]["id"]

    resposta = auth_client.post(f"/promocoes/{sugestao_id}/aprovar", json={})
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "aprovada"

    db_session.refresh(produto)
    assert produto.promocao_ativa is True
    assert produto.preco_promocional == Decimal("17.00")
    assert produto.promocao_expira_em is not None

    historico = auth_client.get("/historico-precos", params={"produto_id": produto.id})
    assert len(historico.json()) == 1
    assert historico.json()[0]["tipo_alteracao"] == "promocao_ia_aprovada"
    assert historico.json()[0]["preco_novo"] == "17.00"


def test_rejeitar_sugestao_nao_altera_produto(auth_client, db_session, monkeypatch):
    produto = _produto_parado(db_session)
    _mockar_llm_sucesso(monkeypatch)
    auth_client.post("/promocoes/gerar-agora")
    sugestao_id = auth_client.get("/promocoes").json()[0]["id"]

    resposta = auth_client.post(f"/promocoes/{sugestao_id}/rejeitar", json={"observacao": "desconto muito alto"})
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "rejeitada"

    db_session.refresh(produto)
    assert produto.promocao_ativa is False
    assert produto.preco_promocional is None


def test_avaliar_sugestao_ja_avaliada_retorna_409(auth_client, db_session, monkeypatch):
    _produto_parado(db_session)
    _mockar_llm_sucesso(monkeypatch)
    auth_client.post("/promocoes/gerar-agora")
    sugestao_id = auth_client.get("/promocoes").json()[0]["id"]
    auth_client.post(f"/promocoes/{sugestao_id}/aprovar", json={})

    resposta = auth_client.post(f"/promocoes/{sugestao_id}/rejeitar", json={})
    assert resposta.status_code == 409


def test_avaliar_sugestao_inexistente_retorna_404(auth_client):
    resposta = auth_client.post("/promocoes/999/aprovar", json={})
    assert resposta.status_code == 404


def test_expirar_promocoes_vencidas_reverte_preco(db_session):
    from app.services import price_service, promotion_service

    produto = Produto(nome="Produto Promo Vencida", preco_normal=Decimal("30.00"))
    db_session.add(produto)
    db_session.flush()
    db_session.add(Estoque(produto_id=produto.id, quantidade=5))
    db_session.commit()

    price_service.aplicar_promocao(db_session, produto.id, Decimal("24.00"), dias_validade=-1)

    total = promotion_service.expirar_promocoes_vencidas(db_session)
    assert total == 1

    db_session.refresh(produto)
    assert produto.promocao_ativa is False
    assert produto.preco_vigente == Decimal("30.00")


def test_finalizar_promocao_volta_ao_preco_normal(auth_client, db_session):
    from app.services import price_service

    produto = Produto(nome="Produto Em Promo", preco_normal=Decimal("30.00"))
    db_session.add(produto)
    db_session.flush()
    db_session.add(Estoque(produto_id=produto.id, quantidade=5))
    db_session.commit()
    price_service.aplicar_promocao(db_session, produto.id, Decimal("24.00"))

    resposta = auth_client.post(f"/promocoes/produtos/{produto.id}/finalizar")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["promocao_ativa"] is False
    assert Decimal(corpo["preco_vigente"]) == Decimal("30.00")

    # segunda chamada: ja nao ha promocao
    assert auth_client.post(f"/promocoes/produtos/{produto.id}/finalizar").status_code == 409


def test_finalizar_promocao_produto_inexistente_retorna_404(auth_client):
    assert auth_client.post("/promocoes/produtos/999/finalizar").status_code == 404


def test_validade_padrao_da_promocao_e_um_dia(db_session):
    from app.services import price_service

    produto = Produto(nome="Produto Validade", preco_normal=Decimal("30.00"))
    db_session.add(produto)
    db_session.flush()
    db_session.add(Estoque(produto_id=produto.id, quantidade=5))
    db_session.commit()
    price_service.aplicar_promocao(db_session, produto.id, Decimal("24.00"))
    db_session.refresh(produto)

    restante = produto.promocao_expira_em - datetime.now(UTC).replace(tzinfo=None)
    assert timedelta(hours=23) < restante <= timedelta(days=1)
