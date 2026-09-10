"""Regras de negocio dos displays fisicos de prateleira (etiquetas
eletronicas). Ver `docs/displays-fisicos.md` para a arquitetura completa
(hardware, protocolo, seguranca).

Fluxo de provisionamento: o funcionario cria o registro do display pelo
painel (`criar_display`), recebe um `token` gerado na hora e grava esse
token no firmware do dispositivo (hardcoded no sketch ou via portal de
config -- decisao de implementacao do firmware). Dali em diante o
dispositivo se autentica sozinho mandando esse token a cada sincronizacao
(`obter_estado_por_token`) -- nao precisa de MAC/serial cadastrado
previamente nem de login de funcionario no device.
"""
import secrets
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.models.display import Display
from app.models.produto import Produto
from app.schemas.display import DisplayCreate, DisplaySincronizarRequest, DisplayUpdate
from app.services.exceptions import DisplayNaoEncontradoError

_DISPLAY_OPTIONS = (joinedload(Display.produto),)


def _gerar_token() -> str:
    return secrets.token_hex(24)  # 48 chars -- espaco suficiente pra nao colidir e cabe folgado em qualquer sketch


def listar_displays(db: Session) -> list[Display]:
    stmt = select(Display).options(*_DISPLAY_OPTIONS).order_by(Display.nome)
    return list(db.execute(stmt).unique().scalars())


def obter_display(db: Session, display_id: int) -> Display:
    display = db.execute(
        select(Display).options(*_DISPLAY_OPTIONS).where(Display.id == display_id)
    ).unique().scalar_one_or_none()
    if display is None:
        raise DisplayNaoEncontradoError(str(display_id))
    return display


def criar_display(db: Session, dados: DisplayCreate) -> Display:
    display = Display(nome=dados.nome, produto_id=dados.produto_id, token=_gerar_token())
    db.add(display)
    db.commit()
    return obter_display(db, display.id)


def atualizar_display(db: Session, display_id: int, dados: DisplayUpdate) -> Display:
    display = obter_display(db, display_id)
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(display, campo, valor)
    db.commit()
    return obter_display(db, display_id)


def desativar_display(db: Session, display_id: int) -> Display:
    """Soft delete -- o token para de funcionar (ver `obter_estado_por_token`)
    mas o registro/historico fica pra referencia."""
    display = obter_display(db, display_id)
    display.ativo = False
    db.commit()
    return obter_display(db, display_id)


def regenerar_token(db: Session, display_id: int) -> Display:
    """Invalida o token atual e gera outro -- usar se o token vazar (ex.:
    dispositivo extraviado) sem precisar recriar o registro (perderia o
    historico/vinculo com o produto)."""
    display = obter_display(db, display_id)
    display.token = _gerar_token()
    db.commit()
    return obter_display(db, display_id)


def montar_estado(display: Display) -> dict:
    """Estado do display pronto pra desenhar -- **fonte unica do payload**.

    E usado nos dois caminhos: na resposta de `POST /displays/sincronizar`
    (HTTP, que a variante e-paper usa em polling e a variante OLED usa uma
    vez no boot) e no push MQTT (`services/mqtt_publisher.py`). Manter um
    construtor so significa que o firmware tem **um unico parser**,
    independente de por onde a mensagem chegou.

    So le -- nao mexe em produto/preco nem commita.
    """
    produto: Produto | None = display.produto
    proximo_sync = get_settings().display_sync_intervalo_segundos
    agora = datetime.now(UTC).replace(tzinfo=None)

    if produto is None:
        return {
            "display_id": display.id,
            "display_nome": display.nome,
            "tem_produto": False,
            "gerado_em": agora,
            "proximo_sync_em_segundos": proximo_sync,
        }

    # Percentual vai calculado aqui, e nao no firmware: microcontrolador
    # nao tem aritmetica decimal confiavel e o selo "-XX%" tem que bater
    # exatamente com o que o painel mostra.
    percentual = None
    if produto.promocao_ativa and produto.preco_normal > 0:
        percentual = (
            (produto.preco_normal - produto.preco_vigente) / produto.preco_normal * 100
        ).quantize(Decimal("0.01"))

    return {
        "display_id": display.id,
        "display_nome": display.nome,
        "tem_produto": True,
        "produto_id": produto.id,
        "produto_nome": produto.nome,
        "marca": produto.marca,
        "tamanho": produto.tamanho,
        "preco_normal": produto.preco_normal,
        "preco_promocional": produto.preco_promocional,
        "promocao_ativa": produto.promocao_ativa,
        "preco_vigente": produto.preco_vigente,
        "percentual_desconto": percentual,
        "produto_atualizado_em": produto.atualizado_em,
        "gerado_em": agora,
        "proximo_sync_em_segundos": proximo_sync,
    }


def sincronizar(db: Session, display: Display, dados: DisplaySincronizarRequest) -> dict:
    """Registra a telemetria reportada (se houver) e devolve o estado atual
    do produto vinculado (ver `montar_estado`)."""
    display.ultima_sincronizacao_em = datetime.now(UTC).replace(tzinfo=None)
    if dados.mac is not None:
        display.mac_reportado = dados.mac
    if dados.bateria_pct is not None:
        display.bateria_pct = dados.bateria_pct
    if dados.rssi_dbm is not None:
        display.rssi_dbm = dados.rssi_dbm
    db.commit()

    return montar_estado(display)


def displays_ativos_do_produto(db: Session, produto_id: int) -> list[Display]:
    """Displays ligados a este produto que devem receber push de preco.
    Display desativado nao recebe -- o token dele ja nao vale mais."""
    stmt = (
        select(Display)
        .options(*_DISPLAY_OPTIONS)
        .where(Display.produto_id == produto_id, Display.ativo.is_(True))
    )
    return list(db.execute(stmt).unique().scalars())
