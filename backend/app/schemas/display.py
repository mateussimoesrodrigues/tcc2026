from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class DisplayCreate(BaseModel):
    nome: str
    produto_id: int | None = None


class DisplayUpdate(BaseModel):
    nome: str | None = None
    produto_id: int | None = None
    ativo: bool | None = None


class DisplayRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    produto_id: int | None
    ativo: bool
    mac_reportado: str | None
    bateria_pct: int | None
    rssi_dbm: int | None
    ultima_sincronizacao_em: datetime | None


class DisplayCriadoResponse(DisplayRead):
    """So a resposta de POST /displays inclui o token -- ele existe pra ser
    copiado uma vez pro firmware do dispositivo na hora de configurar; as
    demais rotas de leitura (GET) nao devolvem o token de volta."""

    token: str


class TokenRegeneradoResponse(BaseModel):
    token: str


class DisplaySincronizarRequest(BaseModel):
    """Telemetria opcional que o firmware manda a cada sync -- tudo
    opcional pra funcionar mesmo com um sketch minimo que so quer o preco."""

    mac: str | None = None
    bateria_pct: int | None = None
    rssi_dbm: int | None = None


class DisplayEstadoResponse(BaseModel):
    """O que o firmware precisa pra desenhar a etiqueta e decidir quando
    dormir ate a proxima sincronizacao."""

    display_id: int
    display_nome: str
    tem_produto: bool

    produto_id: int | None = None
    produto_nome: str | None = None
    marca: str | None = None
    tamanho: str | None = None
    preco_normal: Decimal | None = None
    preco_promocional: Decimal | None = None
    promocao_ativa: bool = False
    preco_vigente: Decimal | None = None
    # Calculado no servidor (nao no firmware) pra o selo "-XX%" bater
    # exatamente com o que o painel mostra. Nulo fora de promocao.
    percentual_desconto: Decimal | None = None
    # Sobe sempre que o preco (ou qualquer outro campo do produto) muda --
    # o firmware pode guardar o ultimo valor visto e so redesenhar a tela
    # (custoso em e-paper) quando ele for diferente.
    produto_atualizado_em: datetime | None = None
    # Quando este payload foi montado. Serve pro firmware descartar uma
    # mensagem MQTT retida que chegue depois de um sync HTTP mais novo.
    gerado_em: datetime | None = None

    proximo_sync_em_segundos: int
