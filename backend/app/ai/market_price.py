"""Preco de mercado de referencia pros candidatos a promocao.

Antes de buscar na web, consulta o registro do produto na tabela
`preco_mercado`: se ainda estiver na validade (`ok`: 7 dias;
`nao_encontrado`: 2 dias, configuraveis), usa o que esta no banco. Senao
busca, e grava o resultado -- inclusive a falha.

Fontes, na ordem:

1. Mercado Livre (`/sites/MLB/search`). Exige token OAuth: sem ele a API
   responde 403, entao so e tentada com `ML_CLIENT_ID`/`ML_CLIENT_SECRET`
   configurados (grant `client_credentials`). Ha relatos de 403 mesmo com
   token valido, por isso existe a segunda fonte.
2. Serper (resultados do Google Shopping Brasil), com `SERPER_API_KEY`.

O retorno e sempre uma faixa (min, mediana, max, numero de amostras),
nunca um preco unico. Nada aqui altera preco nem guard-rail: e so insumo
pro prompt do LLM. E uma dependencia externa best-effort -- nenhuma falha
de rede ou de formato sobe pra quem chama.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from statistics import median

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.preco_mercado import PrecoMercado, StatusPrecoMercado
from app.models.produto import Produto
from app.services.price_service import quantizar_preco

logger = logging.getLogger(__name__)

TIMEOUT_SEGUNDOS = 8

ML_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
ML_BUSCA_URL = "https://api.mercadolibre.com/sites/MLB/search"
SERPER_URL = "https://google.serper.dev/shopping"

FONTE_ML = "mercado_livre"
FONTE_SERPER = "google_shopping"

# Outlier extremo: preco mais de N vezes acima ou abaixo da mediana bruta
# (kit com dezenas de unidades, acessorio avulso, anuncio com preco
# simbolico). Corte relativo a mediana porque, com ~10 amostras, um unico
# valor absurdo distorce quartis e desvio padrao o bastante pra se esconder.
FATOR_OUTLIER = Decimal("3")


@dataclass(frozen=True)
class FaixaMercado:
    mediana: Decimal
    minimo: Decimal
    maximo: Decimal
    n_amostras: int
    # Lojas dos precos que entraram na conta, sem repetir, na ordem da busca.
    lojas: tuple[str, ...] = ()
    # Os anuncios que entraram na conta, pra conferir de onde ela saiu.
    anuncios: tuple[Anuncio, ...] = ()


@dataclass(frozen=True)
class Anuncio:
    preco: Decimal
    loja: str | None = None
    titulo: str | None = None
    link: str | None = None

    def to_dict(self) -> dict:
        return {"preco": float(self.preco), "loja": self.loja, "titulo": self.titulo, "link": self.link}


def calcular_faixa(anuncios: list[Anuncio], *, min_amostras: int) -> FaixaMercado | None:
    """Descarta outliers extremos e resume o resto. `None` quando sobram
    menos de `min_amostras` -- pouca amostra nao e referencia de mercado."""
    validos = [a for a in anuncios if a.preco > 0]
    if not validos:
        return None

    centro = median(a.preco for a in validos)
    usados = [a for a in validos if centro / FATOR_OUTLIER <= a.preco <= centro * FATOR_OUTLIER]
    filtrados = [a.preco for a in usados]
    # Nunca menos de 2, mesmo que a configuracao peca: preco unico nao e faixa.
    if len(filtrados) < max(min_amostras, 2):
        return None

    return FaixaMercado(
        mediana=quantizar_preco(median(filtrados)),
        minimo=quantizar_preco(min(filtrados)),
        maximo=quantizar_preco(max(filtrados)),
        n_amostras=len(filtrados),
        lojas=tuple(dict.fromkeys(a.loja for a in usados if a.loja)),
        anuncios=tuple(usados),
    )


def _preco_em_reais(texto: object) -> Decimal | None:
    """Converte "R$ 1.234,56" (formato do Google Shopping BR). Outra moeda
    ou formato desconhecido vira `None`."""
    if not isinstance(texto, str):
        return None
    achado = re.match(r"\s*R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{2}))?(?![\d.,])", texto)
    if not achado:
        return None
    inteiro, centavos = achado.groups()
    return Decimal(f"{inteiro.replace('.', '')}.{centavos or '00'}")


class BuscadorMercado:
    """Busca na web durante uma rodada de geracao. Guarda o token do
    Mercado Livre e lembra quais fontes recusaram a credencial (401/403),
    pra nao repetir uma chamada fadada a falhar em cada produto."""

    def __init__(self, client: httpx.Client, settings: Settings | None = None):
        self._client = client
        self._settings = settings or get_settings()
        self._token_ml: str | None = None
        self._recusadas: set[str] = set()

    def fontes_disponiveis(self) -> list[str]:
        fontes = []
        if self._settings.ml_client_id and self._settings.ml_client_secret:
            fontes.append(FONTE_ML)
        if self._settings.serper_api_key:
            fontes.append(FONTE_SERPER)
        return [f for f in fontes if f not in self._recusadas]

    def buscar(self, consulta: str) -> tuple[FaixaMercado | None, str]:
        """`(faixa, fonte)`. Tenta cada fonte disponivel ate uma devolver
        amostras suficientes; sem nenhuma, devolve `None` e a ultima
        fonte consultada."""
        ultima = ""
        for fonte in self.fontes_disponiveis():
            ultima = fonte
            try:
                anuncios = self._buscar_ml(consulta) if fonte == FONTE_ML else self._buscar_serper(consulta)
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403):
                    self._recusadas.add(fonte)
                logger.warning("Preco de mercado: %s respondeu HTTP %s", fonte, e.response.status_code)
                continue
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, InvalidOperation) as e:
                logger.warning("Preco de mercado: falha em %s: %s", fonte, type(e).__name__)
                continue

            faixa = calcular_faixa(
                anuncios[: self._settings.preco_mercado_n_resultados],
                min_amostras=self._settings.preco_mercado_min_amostras,
            )
            if faixa is not None:
                return faixa, fonte
        return None, ultima

    def _obter_token_ml(self) -> str:
        if self._token_ml is None:
            resposta = self._client.post(
                ML_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._settings.ml_client_id,
                    "client_secret": self._settings.ml_client_secret,
                },
            )
            # Credencial errada volta como 400: sem isto, cada produto da
            # rodada pediria um token de novo.
            if resposta.status_code == 400:
                self._recusadas.add(FONTE_ML)
            resposta.raise_for_status()
            self._token_ml = resposta.json()["access_token"]
        return self._token_ml

    def _buscar_ml(self, consulta: str) -> list[Anuncio]:
        resposta = self._client.get(
            ML_BUSCA_URL,
            headers={"Authorization": f"Bearer {self._obter_token_ml()}"},
            params={"q": consulta, "limit": self._settings.preco_mercado_n_resultados},
        )
        resposta.raise_for_status()
        return [
            Anuncio(
                Decimal(str(item["price"])),
                "Mercado Livre",
                _texto(item.get("title")),
                _link(item.get("permalink")),
            )
            for item in resposta.json()["results"]
            if item.get("price") is not None
            and item.get("currency_id", "BRL") == "BRL"
            and item.get("condition") != "used"
        ]

    def _buscar_serper(self, consulta: str) -> list[Anuncio]:
        resposta = self._client.post(
            SERPER_URL,
            headers={"X-API-KEY": self._settings.serper_api_key},
            json={"q": consulta, "gl": "br", "hl": "pt-br"},
        )
        resposta.raise_for_status()
        itens = ((_preco_em_reais(item.get("price")), item) for item in resposta.json().get("shopping", []))
        return [
            Anuncio(preco, _texto(item.get("source")), _texto(item.get("title")), _link(item.get("link")))
            for preco, item in itens
            if preco is not None
        ]


def _texto(valor: object) -> str | None:
    return (valor.strip() or None) if isinstance(valor, str) else None


def _link(valor: object) -> str | None:
    """So http(s): o link vem de terceiro e vira `href` na tela."""
    texto = _texto(valor)
    return texto if texto and texto.lower().startswith(("https://", "http://")) else None


def _agora() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _dentro_da_validade(registro: PrecoMercado, settings: Settings) -> bool:
    dias = (
        settings.preco_mercado_ttl_ok_dias
        if registro.status == StatusPrecoMercado.OK
        else settings.preco_mercado_ttl_falha_dias
    )
    return registro.consultado_em >= _agora() - timedelta(days=dias)


def montar_consulta(produto: Produto) -> str:
    return " ".join(parte for parte in (produto.marca, produto.nome) if parte)


def obter_preco_mercado(db: Session, produto: Produto, buscador: BuscadorMercado) -> PrecoMercado | None:
    """Registro do banco se ainda valido; senao busca na web e grava
    (sem commit -- quem chama fecha a transacao).

    `None` quando precisaria buscar mas nao ha fonte utilizavel (sem
    credencial, ou todas recusaram). Nesse caso nada e gravado: nenhuma
    busca foi feita, e gravar a "falha" seguraria o produto sem referencia
    por dias depois de a credencial ser corrigida."""
    settings = get_settings()
    registro = db.execute(
        select(PrecoMercado).where(PrecoMercado.produto_id == produto.id)
    ).scalar_one_or_none()

    if registro is not None and _dentro_da_validade(registro, settings):
        return registro

    if not buscador.fontes_disponiveis():
        return None

    faixa, fonte = buscador.buscar(montar_consulta(produto))

    if registro is None:
        registro = PrecoMercado(produto_id=produto.id)
        db.add(registro)
    registro.status = StatusPrecoMercado.OK if faixa else StatusPrecoMercado.NAO_ENCONTRADO
    registro.preco_mediana = faixa.mediana if faixa else None
    registro.preco_min = faixa.minimo if faixa else None
    registro.preco_max = faixa.maximo if faixa else None
    registro.n_amostras = faixa.n_amostras if faixa else 0
    registro.fonte = fonte
    registro.lojas = list(faixa.lojas) if faixa else None
    registro.anuncios = [a.to_dict() for a in faixa.anuncios] if faixa else None
    registro.consultado_em = _agora()
    return registro


def para_sinais(registro: PrecoMercado | None, preco_atual: Decimal) -> tuple[dict, float | None]:
    """`(preco_mercado, posicao)` no formato de `SinaisProduto` (so tipos
    primitivos, vai pro JSON de auditoria). `posicao` e
    preco_atual / mediana: 1.2 = 20% acima do mercado."""
    if registro is None or registro.status != StatusPrecoMercado.OK:
        return {"status": StatusPrecoMercado.NAO_ENCONTRADO.value}, None

    dados = {
        "status": StatusPrecoMercado.OK.value,
        "mediana": float(registro.preco_mediana),
        "min": float(registro.preco_min),
        "max": float(registro.preco_max),
        "n_amostras": registro.n_amostras,
        "fonte": registro.fonte,
        "lojas": registro.lojas or [],
        "anuncios": registro.anuncios or [],
        "consultado_em": registro.consultado_em.isoformat(),
    }
    return dados, round(float(preco_atual / registro.preco_mediana), 4)
