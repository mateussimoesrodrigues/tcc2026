"""Push de preco pros displays de prateleira via MQTT.

Existe pra atender a variante de firmware **OLED + MQTT** (demonstracao),
em que o ESP32 fica sempre ligado e inscrito no topico do proprio display:
aprovou a promocao no painel, a etiqueta muda na hora. A variante e-paper
(producao) nao usa nada disto -- ela continua em polling com deep sleep, e
pega o preco novo no ciclo seguinte. Ver `docs/displays-fisicos.md`.

Tres garantias que este modulo precisa dar, nessa ordem:

1. **Nunca derrubar a operacao.** A mudanca de preco no banco e a fonte da
   verdade; o push e um aviso best-effort por cima. Qualquer erro de
   broker (host errado, TLS, credencial, rede caida) e capturado e
   logado -- jamais sobe pro `promotion_service` e jamais reverte uma
   aprovacao ja commitada.
2. **Ser um no-op quando desligado.** Com `MQTT_ENABLED=false` (o padrao)
   nada e importado do paho em tempo de conexao, nenhum socket e aberto e
   nenhum teste/CI precisa de broker.
3. **Nao segurar a requisicao HTTP.** O cliente e persistente, com
   `loop_start()` numa thread propria e reconexao automatica do paho;
   `publish()` so enfileira. Sem isso, cada aprovacao pagaria um handshake
   TLS novo (~centenas de ms) dentro do request do funcionario.

Mensagens vao com `retain=True` de proposito: um display que ligar depois
recebe o ultimo preco publicado assim que se inscreve, sem esperar a
proxima aprovacao. Isso complementa (nao substitui) a chamada HTTP que o
firmware faz no boot -- o HTTP e a fonte autoritativa, o retido e rede de
seguranca caso o display reinicie entre duas aprovacoes.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.config import get_settings
from app.models.display import Display

logger = logging.getLogger(__name__)

# QoS 1 (at least once): uma etiqueta de preco nao pode perder a mensagem
# de "entrou em promocao". Duplicata e inofensiva -- o firmware so
# redesenha a tela com o mesmo conteudo.
QOS = 1
TIMEOUT_CONEXAO_SEGUNDOS = 5

_cliente: Any | None = None
_lock = threading.Lock()


def _serializar(valor: Any) -> Any:
    """Decimal e datetime nao sao serializaveis por padrao. Decimal vira
    **string** (nao float) pra o preco nao pegar erro de ponto flutuante no
    caminho -- e o firmware trata preco como texto de qualquer forma."""
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    raise TypeError(f"Nao sei serializar {type(valor)!r} pro payload MQTT")


def topico_do_display(display: Display) -> str:
    """`{MQTT_TOPIC_PREFIX}/{display_id}/preco`.

    Usa o `id` do display como identificador do topico: ja e unico, ja e
    estavel e o firmware ja o recebe como `display_id` na resposta do sync
    HTTP do boot -- entao o dispositivo consegue montar o proprio topico
    sem nenhum campo novo. Quem autentica o dispositivo continua sendo o
    token; o id no topico e so endereco.
    """
    return f"{get_settings().mqtt_topic_prefix}/{display.id}/preco"


def _criar_cliente():
    """Cria e conecta o cliente. Import do paho fica aqui dentro pra o
    modulo continuar importavel (e testavel) sem a dependencia instalada."""
    from paho.mqtt import client as mqtt

    settings = get_settings()
    cliente = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"precificacao-backend-{threading.get_ident()}",
        protocol=mqtt.MQTTv311,
    )

    if settings.mqtt_username:
        cliente.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    if settings.mqtt_use_tls:
        cliente.tls_set()  # usa o truststore do SO (ver core/config.py)

    # Backoff de reconexao: o paho cuida sozinho de voltar depois de uma
    # queda de rede, sem precisar de supervisao nossa.
    cliente.reconnect_delay_set(min_delay=1, max_delay=60)
    cliente.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=60)
    cliente.loop_start()
    return cliente


def obter_cliente():
    """Cliente unico do processo, criado sob demanda. `None` se o MQTT
    estiver desligado ou se a conexao inicial falhar."""
    global _cliente
    if not get_settings().mqtt_enabled:
        return None
    if _cliente is not None:
        return _cliente

    with _lock:
        if _cliente is not None:  # outra thread criou enquanto esperavamos
            return _cliente
        try:
            _cliente = _criar_cliente()
            logger.info(
                "MQTT: cliente iniciado para %s:%s",
                get_settings().mqtt_host,
                get_settings().mqtt_port,
            )
        except Exception as e:  # noqa: BLE001 -- push e best-effort
            logger.warning("MQTT: nao foi possivel iniciar o cliente (%s). Push desativado.", e)
            _cliente = None
    return _cliente


def publicar_preco_display(display: Display, payload: dict) -> bool:
    """Publica o estado do display no topico dele. Devolve True se a
    mensagem foi entregue ao cliente MQTT (nao garante que o broker ou o
    dispositivo receberam -- isso e por conta do QoS).

    Nunca levanta: o chamador (aprovacao de promocao) ja commitou a
    mudanca de preco e nao pode ser revertido por um problema de broker.
    """
    cliente = obter_cliente()
    if cliente is None:
        return False

    topico = topico_do_display(display)
    try:
        corpo = json.dumps(payload, default=_serializar, ensure_ascii=False)
        info = cliente.publish(topico, corpo, qos=QOS, retain=True)
        if info.rc != 0:
            logger.warning("MQTT: publish em %s devolveu rc=%s", topico, info.rc)
            return False
        logger.info("MQTT: publicado em %s (%d bytes)", topico, len(corpo))
        return True
    except Exception as e:  # noqa: BLE001 -- ver docstring do modulo
        logger.warning("MQTT: falha ao publicar em %s: %s", topico, e)
        return False


def publicar_estado_dos_displays(db, produto_id: int) -> int:
    """Publica o preco atual pra todos os displays ativos vinculados a este
    produto. Devolve quantos foram publicados com sucesso.

    Chamar **depois** do commit da mudanca de preco: so anunciamos o que ja
    esta persistido, senao um rollback deixaria a etiqueta mostrando um
    preco que nao existe no banco.
    """
    if not get_settings().mqtt_enabled:
        return 0

    # Import local: display_service nao depende deste modulo, entao manter
    # a dependencia numa direcao so evita ciclo de import.
    from app.services import display_service

    publicados = 0
    try:
        displays = display_service.displays_ativos_do_produto(db, produto_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("MQTT: falha ao buscar displays do produto %s: %s", produto_id, e)
        return 0

    for display in displays:
        if publicar_preco_display(display, display_service.montar_estado(display)):
            publicados += 1
    return publicados


def fechar_cliente() -> None:
    """Encerra o loop de rede do cliente (chamado no shutdown da app)."""
    global _cliente
    with _lock:
        if _cliente is None:
            return
        try:
            _cliente.loop_stop()
            _cliente.disconnect()
        except Exception as e:  # noqa: BLE001
            logger.warning("MQTT: erro ao encerrar o cliente: %s", e)
        finally:
            _cliente = None
