"""Push MQTT de preco pros displays de prateleira (variante OLED).

Nenhum teste aqui abre socket: o cliente paho e substituido por um duble
que so registra o que seria publicado. O CI nao tem broker, e o push e
justamente a parte que NAO pode ser obrigatoria pro sistema funcionar --
entao a suite roda com `MQTT_ENABLED` desligado por padrao e cada teste
que precisa liga explicitamente.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core import config
from app.models.display import Display
from app.models.estoque import Estoque
from app.models.historico_preco import HistoricoPreco
from app.models.produto import Produto
from app.models.promocao_sugestao import PrioridadeSugestao, PromocaoSugestao, StatusSugestao
from app.services import display_service, mqtt_publisher, promotion_service


class ClienteMqttFalso:
    """Duble do cliente paho: registra publicacoes em vez de mandar pra rede."""

    def __init__(self, falhar=False):
        self.publicacoes = []
        self.falhar = falhar
        self.encerrado = False

    def publish(self, topico, corpo, qos=0, retain=False):
        if self.falhar:
            raise RuntimeError("broker fora do ar")
        self.publicacoes.append({"topico": topico, "corpo": corpo, "qos": qos, "retain": retain})
        return SimpleNamespace(rc=0)

    def loop_stop(self):
        self.encerrado = True

    def disconnect(self):
        self.encerrado = True


@pytest.fixture(autouse=True)
def _resetar_cliente_global():
    """O cliente MQTT e global do processo -- sem zerar entre testes, um
    duble vazaria pro teste seguinte."""
    mqtt_publisher._cliente = None
    yield
    mqtt_publisher._cliente = None


def _ligar_mqtt(monkeypatch, **overrides):
    """Ativa o MQTT com um Settings proprio. `get_settings` e lru_cached,
    entao trocamos a funcao nos modulos que a chamam em vez de mexer no
    cache global (que vazaria pros outros testes)."""
    valores = {
        "mqtt_enabled": True,
        "mqtt_host": "broker.teste",
        "mqtt_port": 8883,
        "mqtt_topic_prefix": "loja/displays",
        **overrides,
    }
    settings = config.Settings(**valores)
    for modulo in ("app.services.mqtt_publisher", "app.services.display_service"):
        monkeypatch.setattr(f"{modulo}.get_settings", lambda: settings)
    return settings


def _instalar_cliente(monkeypatch, cliente):
    monkeypatch.setattr(mqtt_publisher, "_criar_cliente", lambda: cliente)
    return cliente


def _produto_com_sugestao(db, *, preco="20.00", custo="8.00", preco_sugerido="16.00"):
    produto = Produto(nome="Cola Pano", marca="Gliart", preco_normal=Decimal(preco), custo=Decimal(custo))
    db.add(produto)
    db.flush()
    db.add(Estoque(produto_id=produto.id, quantidade=10))
    sugestao = PromocaoSugestao(
        produto_id=produto.id,
        sinais_detectados={},
        percentual_desconto_sugerido=Decimal("20.00"),
        preco_sugerido=Decimal(preco_sugerido),
        justificativa_ia="Produto parado.",
        prioridade=PrioridadeSugestao.ALTA,
        modelo_ia_usado="groq/teste-mock",
    )
    db.add(sugestao)
    db.commit()
    db.refresh(produto)
    db.refresh(sugestao)
    return produto, sugestao


def _display(db, produto_id, nome="Prateleira 1", ativo=True):
    display = Display(nome=nome, produto_id=produto_id, token=f"tok-{nome}", ativo=ativo)
    db.add(display)
    db.commit()
    db.refresh(display)
    return display


# --- topico ----------------------------------------------------------------


def test_topico_usa_prefixo_e_id_do_display(db_session, monkeypatch):
    _ligar_mqtt(monkeypatch)
    produto, _ = _produto_com_sugestao(db_session)
    display = _display(db_session, produto.id)

    assert mqtt_publisher.topico_do_display(display) == f"loja/displays/{display.id}/preco"


def test_topico_respeita_prefixo_customizado(db_session, monkeypatch):
    _ligar_mqtt(monkeypatch, mqtt_topic_prefix="tcc/etiquetas")
    produto, _ = _produto_com_sugestao(db_session)
    display = _display(db_session, produto.id)

    assert mqtt_publisher.topico_do_display(display) == f"tcc/etiquetas/{display.id}/preco"


# --- desligado = no-op ------------------------------------------------------


def test_mqtt_desligado_nao_cria_cliente(db_session, monkeypatch):
    """Padrao do projeto: sem broker configurado, nada acontece -- nem
    tentativa de conexao. E o que deixa dev e CI rodarem sem broker."""
    tentou = []
    monkeypatch.setattr(mqtt_publisher, "_criar_cliente", lambda: tentou.append(1))

    produto, sugestao = _produto_com_sugestao(db_session)
    _display(db_session, produto.id)

    assert mqtt_publisher.obter_cliente() is None
    assert mqtt_publisher.publicar_estado_dos_displays(db_session, produto.id) == 0
    assert tentou == []


def test_aprovacao_com_mqtt_desligado_funciona_normalmente(db_session, monkeypatch):
    tentou = []
    monkeypatch.setattr(mqtt_publisher, "_criar_cliente", lambda: tentou.append(1))

    produto, sugestao = _produto_com_sugestao(db_session)
    _display(db_session, produto.id)

    aprovada = promotion_service.aprovar(db_session, sugestao.id, funcionario_id=None)

    assert aprovada.status == StatusSugestao.APROVADA
    db_session.refresh(produto)
    assert produto.promocao_ativa is True
    assert tentou == []


# --- publicacao na aprovacao ------------------------------------------------


def test_aprovar_publica_para_cada_display_vinculado(db_session, monkeypatch):
    _ligar_mqtt(monkeypatch)
    cliente = _instalar_cliente(monkeypatch, ClienteMqttFalso())

    produto, sugestao = _produto_com_sugestao(db_session)
    d1 = _display(db_session, produto.id, nome="Prateleira 1")
    d2 = _display(db_session, produto.id, nome="Prateleira 2")

    # display de outro produto nao pode receber nada
    outro = Produto(nome="Outro", preco_normal=Decimal("10.00"), custo=Decimal("4.00"))
    db_session.add(outro)
    db_session.flush()
    _display(db_session, outro.id, nome="Prateleira 3")

    promotion_service.aprovar(db_session, sugestao.id, funcionario_id=None)

    topicos = sorted(p["topico"] for p in cliente.publicacoes)
    assert topicos == sorted([f"loja/displays/{d1.id}/preco", f"loja/displays/{d2.id}/preco"])


def test_display_inativo_nao_recebe_push(db_session, monkeypatch):
    _ligar_mqtt(monkeypatch)
    cliente = _instalar_cliente(monkeypatch, ClienteMqttFalso())

    produto, sugestao = _produto_com_sugestao(db_session)
    ativo = _display(db_session, produto.id, nome="Ativa")
    _display(db_session, produto.id, nome="Desativada", ativo=False)

    promotion_service.aprovar(db_session, sugestao.id, funcionario_id=None)

    assert [p["topico"] for p in cliente.publicacoes] == [f"loja/displays/{ativo.id}/preco"]


def test_payload_publicado_traz_o_que_o_firmware_desenha(db_session, monkeypatch):
    """O payload tem que ser o MESMO formato do sync HTTP -- e o que
    permite um unico parser no firmware."""
    import json

    _ligar_mqtt(monkeypatch)
    cliente = _instalar_cliente(monkeypatch, ClienteMqttFalso())

    produto, sugestao = _produto_com_sugestao(db_session, preco="20.00", preco_sugerido="16.00")
    _display(db_session, produto.id)

    promotion_service.aprovar(db_session, sugestao.id, funcionario_id=None)

    payload = json.loads(cliente.publicacoes[0]["corpo"])
    assert payload["tem_produto"] is True
    assert payload["produto_nome"] == "Cola Pano"
    assert payload["marca"] == "Gliart"
    assert payload["promocao_ativa"] is True
    # Decimal vira string, nao float -- preco nao passa por ponto flutuante.
    assert payload["preco_normal"] == "20.00"
    assert payload["preco_vigente"] == "16.00"
    assert payload["percentual_desconto"] == "20.00"
    assert isinstance(payload["gerado_em"], str)

    # e as mesmas chaves que o sync HTTP devolve
    db_session.refresh(produto)
    display = display_service.displays_ativos_do_produto(db_session, produto.id)[0]
    assert set(payload) == set(display_service.montar_estado(display))


def test_publica_com_retain_e_qos1(db_session, monkeypatch):
    """retain: display que ligar depois pega o ultimo preco ao assinar.
    QoS 1: a mensagem de 'entrou em promocao' nao pode se perder."""
    _ligar_mqtt(monkeypatch)
    cliente = _instalar_cliente(monkeypatch, ClienteMqttFalso())

    produto, sugestao = _produto_com_sugestao(db_session)
    _display(db_session, produto.id)

    promotion_service.aprovar(db_session, sugestao.id, funcionario_id=None)

    assert cliente.publicacoes[0]["retain"] is True
    assert cliente.publicacoes[0]["qos"] == 1


def test_produto_sem_display_nao_publica(db_session, monkeypatch):
    _ligar_mqtt(monkeypatch)
    cliente = _instalar_cliente(monkeypatch, ClienteMqttFalso())

    produto, sugestao = _produto_com_sugestao(db_session)
    promotion_service.aprovar(db_session, sugestao.id, funcionario_id=None)

    assert cliente.publicacoes == []


# --- falha no push NAO pode derrubar a aprovacao ----------------------------


def test_falha_no_publish_nao_reverte_aprovacao(db_session, monkeypatch):
    """A mudanca de preco no banco e a fonte da verdade; o push e um aviso
    best-effort por cima. Broker fora do ar nao pode desfazer o trabalho do
    funcionario."""
    _ligar_mqtt(monkeypatch)
    _instalar_cliente(monkeypatch, ClienteMqttFalso(falhar=True))

    produto, sugestao = _produto_com_sugestao(db_session)
    _display(db_session, produto.id)

    aprovada = promotion_service.aprovar(db_session, sugestao.id, funcionario_id=None)

    assert aprovada.status == StatusSugestao.APROVADA
    db_session.refresh(produto)
    assert produto.promocao_ativa is True
    assert produto.preco_promocional == Decimal("16.00")
    assert db_session.query(HistoricoPreco).count() == 1


def test_falha_ao_criar_cliente_nao_derruba_aprovacao(db_session, monkeypatch):
    """Host errado, TLS quebrado, credencial invalida -- tudo isso estoura
    na criacao do cliente, antes de qualquer publish."""
    _ligar_mqtt(monkeypatch)

    def explodir():
        raise OSError("nao resolveu o host do broker")

    monkeypatch.setattr(mqtt_publisher, "_criar_cliente", explodir)

    produto, sugestao = _produto_com_sugestao(db_session)
    _display(db_session, produto.id)

    aprovada = promotion_service.aprovar(db_session, sugestao.id, funcionario_id=None)

    assert aprovada.status == StatusSugestao.APROVADA
    assert mqtt_publisher.obter_cliente() is None


def test_publish_com_rc_de_erro_nao_levanta(db_session, monkeypatch):
    """paho sinaliza falha por codigo de retorno, nao so por excecao."""
    _ligar_mqtt(monkeypatch)

    class ClienteComRcRuim(ClienteMqttFalso):
        def publish(self, topico, corpo, qos=0, retain=False):
            return SimpleNamespace(rc=4)  # MQTT_ERR_NO_CONN

    _instalar_cliente(monkeypatch, ClienteComRcRuim())

    produto, sugestao = _produto_com_sugestao(db_session)
    display = _display(db_session, produto.id)

    assert mqtt_publisher.publicar_preco_display(display, {"teste": 1}) is False
    promotion_service.aprovar(db_session, sugestao.id, funcionario_id=None)  # nao levanta


# --- fim de promocao --------------------------------------------------------


def test_expirar_promocao_publica_preco_normal(db_session, monkeypatch):
    """Etiqueta anunciando promocao que ja acabou e pior que etiqueta sem
    promocao -- o fim tambem precisa ser empurrado."""
    import json

    _ligar_mqtt(monkeypatch)
    cliente = _instalar_cliente(monkeypatch, ClienteMqttFalso())

    produto, sugestao = _produto_com_sugestao(db_session)
    _display(db_session, produto.id)

    # aprova com validade ja vencida, depois roda a expiracao
    promotion_service.aprovar(db_session, sugestao.id, funcionario_id=None, dias_validade=-1)
    cliente.publicacoes.clear()

    assert promotion_service.expirar_promocoes_vencidas(db_session) == 1

    assert len(cliente.publicacoes) == 1
    payload = json.loads(cliente.publicacoes[0]["corpo"])
    assert payload["promocao_ativa"] is False
    assert payload["preco_vigente"] == "20.00"
    assert payload["percentual_desconto"] is None


# --- serializacao -----------------------------------------------------------


def test_serializar_converte_decimal_e_datetime():
    assert mqtt_publisher._serializar(Decimal("19.95")) == "19.95"
    momento = datetime(2026, 9, 1, 10, 30, tzinfo=UTC)
    assert mqtt_publisher._serializar(momento).startswith("2026-09-01T10:30")


def test_serializar_recusa_tipo_desconhecido():
    with pytest.raises(TypeError):
        mqtt_publisher._serializar(object())


def test_fechar_cliente_encerra_o_loop(monkeypatch):
    _ligar_mqtt(monkeypatch)
    cliente = _instalar_cliente(monkeypatch, ClienteMqttFalso())

    assert mqtt_publisher.obter_cliente() is cliente
    mqtt_publisher.fechar_cliente()

    assert cliente.encerrado is True
    assert mqtt_publisher._cliente is None


def test_display_sem_produto_gera_payload_de_placeholder(db_session, monkeypatch):
    """Display cadastrado mas ainda nao vinculado: o firmware precisa saber
    disso pra desenhar 'sem produto' em vez de um preco vazio."""
    _ligar_mqtt(monkeypatch)
    display = _display(db_session, None, nome="Sem vinculo")

    estado = display_service.montar_estado(display)
    assert estado["tem_produto"] is False
    assert "preco_vigente" not in estado
