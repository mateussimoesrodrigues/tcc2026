"""Camada de chamada aos LLMs gratuitos que viram a sugestao de desconto
em texto/numero legivel. Chamada HTTP direta via `httpx` (ja e dependencia
do projeto) em vez de instalar os SDKs oficiais -- menos dependencia, e
mais facil de auditar/explicar na banca (e so uma chamada REST com um
prompt e validacao de schema, sem "caixa preta" de biblioteca).

Fluxo: tenta Groq (Llama 3.3 70B, free tier generoso) primeiro; se falhar
por qualquer motivo (key ausente, timeout, erro HTTP, resposta fora do
formato esperado), tenta Gemini 2.5 Flash como fallback. Se os dois
falharem, `LLMIndisponivelError` sobe pro `promotion_service`, que pula
esse produto e segue pros demais candidatos (uma falha de IA num produto
nao trava a geracao de sugestoes dos outros).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from app.ai.rules import SinaisProduto
from app.core.config import get_settings
from app.services.exceptions import LLMIndisponivelError, RespostaLLMInvalidaError

# Fallback historico do teto de desconto. O valor efetivo vem de
# `Settings.desconto_maximo_percentual` (mesmo default), pra ficar
# ajustavel por ambiente junto com os demais guard-rails de preco.
DESCONTO_MAXIMO_PERMITIDO = Decimal("70")
TIMEOUT_SEGUNDOS = 10
PRIORIDADES_VALIDAS = {"baixa", "media", "alta"}

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Llama 3.3 70B (escolha original do plano) foi descontinuado no catalogo
# da Groq. openai/gpt-oss-120b e o substituto atual mais proximo no free
# tier: modelo grande, aberto, com suporte a json_mode/structured_outputs
# (ver `GET /openai/v1/models` da propria Groq pra conferir o catalogo
# vigente se isso mudar de novo).
GROQ_MODELO = "openai/gpt-oss-120b"

GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
GEMINI_MODELO = "gemini-2.5-flash"

PROMPT_SISTEMA = (
    "Voce e um assistente de precificacao de uma loja fisica de armarinho/papelaria/artesanato. "
    "Analise os sinais de um produto (dias sem venda, giro, estoque, margem, proximidade de data "
    "comemorativa) e sugira um desconto promocional razoavel para acelerar a venda sem prejudicar "
    "a loja financeiramente. Responda ESTRITAMENTE em JSON, sem nenhum texto fora do JSON, com "
    'exatamente as chaves: "percentual_desconto_sugerido" (numero de 0 a 70), "preco_sugerido" '
    '(numero: preco normal com o desconto aplicado), "justificativa" (string curta em portugues '
    'explicando o motivo com base nos sinais recebidos), "prioridade" (uma destas tres strings: '
    '"baixa", "media" ou "alta").'
)


@dataclass
class SugestaoLLM:
    percentual_desconto: Decimal
    preco_sugerido: Decimal
    justificativa: str
    prioridade: str
    modelo_usado: str


def _linhas_mercado(sinais: SinaisProduto) -> list[str]:
    """Bloco do prompt com a referencia de mercado. Vazio quando nao ha
    referencia, deixando o prompt igual ao de sem busca. As instrucoes vao
    aqui, e nao no prompt de sistema, pelo mesmo motivo."""
    mercado = sinais.preco_mercado
    if not mercado or mercado.get("status") != "ok" or sinais.posicao_mercado is None:
        return []

    diferenca = (sinais.posicao_mercado - 1) * 100
    if abs(diferenca) < 0.5:
        comparacao = "em linha com a mediana do mercado"
    else:
        comparacao = f"{abs(diferenca):.0f}% {'acima' if diferenca > 0 else 'abaixo'} da mediana do mercado"

    return [
        f"Preco de mercado ({mercado['n_amostras']} anuncios): mediana R$ {mercado['mediana']:.2f}, "
        f"faixa de R$ {mercado['min']:.2f} a R$ {mercado['max']:.2f}",
        f"Posicao do preco atual: {comparacao}",
        "Use a mediana do mercado como ancora do desconto e cite essa comparacao na justificativa. "
        "Se o preco ja esta abaixo do mercado, prefira um desconto menor. A referencia de mercado "
        "nunca autoriza passar do desconto maximo da loja: se igualar o mercado exigir mais que "
        "isso, nao acompanhe o mercado.",
    ]


def _montar_prompt_usuario(sinais: SinaisProduto) -> str:
    linhas = [
        f"Produto: {sinais.nome}"
        + (f" ({sinais.marca})" if sinais.marca else "")
        + (f", tamanho {sinais.tamanho}" if sinais.tamanho else ""),
        f"Preco normal: R$ {sinais.preco_normal:.2f}",
        f"Estoque atual: {sinais.estoque_atual} unidades",
    ]
    if sinais.dias_sem_venda is not None:
        linhas.append(f"Dias sem venda: {sinais.dias_sem_venda}")
    else:
        linhas.append(f"Nenhuma venda registrada nos ultimos {sinais.janela_dias} dias")
    linhas.append(f"Unidades vendidas nos ultimos {sinais.janela_dias} dias: {sinais.unidades_vendidas_periodo}")
    linhas.append(f"Giro medio: {sinais.giro_diario:.3f} unidades/dia")
    if sinais.dias_de_estoque_restante is not None:
        linhas.append(
            f"No ritmo atual de vendas, o estoque dura aproximadamente {sinais.dias_de_estoque_restante:.0f} dias"
        )
    else:
        linhas.append("Sem vendas recentes para estimar quanto tempo o estoque atual duraria")
    if sinais.margem is not None:
        linhas.append(f"Margem estimada sobre o preco normal: {sinais.margem * 100:.1f}%")
    else:
        linhas.append("Custo do produto nao informado -- estimativa de margem indisponivel")
    linhas.append(f"Proxima data comemorativa: {sinais.proxima_data_sazonal}, em {sinais.dias_ate_data_sazonal} dias")
    linhas.extend(_linhas_mercado(sinais))
    # Informar o teto no proprio prompt tende a reduzir resposta invalida,
    # mas isso e uma hipotese -- por isso fica atras de uma flag, pro
    # harness (scripts/avaliar_llm.py) conseguir medir os dois bracos.
    if get_settings().informar_piso_no_prompt and sinais.desconto_maximo_permitido is not None:
        linhas.append(
            f"Desconto maximo permitido pela politica da loja para este produto: "
            f"{sinais.desconto_maximo_permitido:.0f}% (acima disso a venda fica abaixo do custo)"
        )
    return "\n".join(linhas)


def _extrair_json(texto: str) -> dict:
    try:
        return json.loads(texto)
    except (json.JSONDecodeError, TypeError) as e:
        raise RespostaLLMInvalidaError(f"Resposta do LLM nao e JSON valido: {e}") from e


def _validar_resposta(dados: dict, modelo: str, *, preco_normal: Decimal | None = None) -> SugestaoLLM:
    """Valida a resposta do LLM contra o schema esperado e as faixas de
    negocio. `preco_normal`, quando informado, habilita a checagem de
    coerencia entre `percentual_desconto_sugerido` e `preco_sugerido` -- o
    modelo as vezes devolve o par inconsistente (ex.: anuncia "30% off" e
    manda um preco que e 10% off). Keyword-only com default `None` pra nao
    exigir o parametro de quem so quer validar o schema."""
    try:
        percentual = Decimal(str(dados["percentual_desconto_sugerido"]))
        preco_sugerido = Decimal(str(dados["preco_sugerido"]))
        justificativa = str(dados["justificativa"]).strip()
        prioridade = str(dados["prioridade"]).strip().lower()
    except (KeyError, TypeError, ValueError, InvalidOperation) as e:
        raise RespostaLLMInvalidaError(f"Campo ausente ou invalido na resposta do LLM: {e}") from e

    desconto_maximo = Decimal(str(get_settings().desconto_maximo_percentual))
    if not (0 <= percentual <= desconto_maximo):
        raise RespostaLLMInvalidaError(
            f"Desconto sugerido fora da faixa permitida (0-{desconto_maximo}%): {percentual}"
        )
    if preco_sugerido <= 0:
        raise RespostaLLMInvalidaError(f"Preco sugerido invalido: {preco_sugerido}")
    if not justificativa:
        raise RespostaLLMInvalidaError("Justificativa vazia na resposta do LLM")
    if prioridade not in PRIORIDADES_VALIDAS:
        prioridade = "media"  # tolera variacao/sinonimo sem descartar a sugestao inteira

    if preco_normal is not None and preco_normal > 0:
        esperado = preco_normal * (1 - percentual / Decimal("100"))
        # Divergencia medida em pontos percentuais do preco normal (nao
        # relativa ao esperado): nao explode em produtos baratos e e
        # diretamente interpretavel ("errou por 3 p.p. do preco").
        divergencia_pp = abs(preco_sugerido - esperado) / preco_normal * Decimal("100")
        tolerancia = Decimal(str(get_settings().tolerancia_coerencia_pp))
        if divergencia_pp > tolerancia:
            raise RespostaLLMInvalidaError(
                f"Incoerencia entre desconto ({percentual}%) e preco sugerido "
                f"(R$ {preco_sugerido}); esperado ~R$ {esperado:.2f} "
                f"(divergencia de {divergencia_pp:.1f} p.p., tolerancia {tolerancia} p.p.)"
            )

    return SugestaoLLM(
        percentual_desconto=percentual,
        preco_sugerido=preco_sugerido,
        justificativa=justificativa,
        prioridade=prioridade,
        modelo_usado=modelo,
    )


def _chamar_groq(client: httpx.Client, sinais: SinaisProduto, api_key: str) -> dict:
    if not api_key:
        raise LLMIndisponivelError("GROQ_API_KEY nao configurada")
    resposta = client.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": GROQ_MODELO,
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": PROMPT_SISTEMA},
                {"role": "user", "content": _montar_prompt_usuario(sinais)},
            ],
        },
    )
    resposta.raise_for_status()
    corpo = resposta.json()
    return _extrair_json(corpo["choices"][0]["message"]["content"])


def _chamar_gemini(client: httpx.Client, sinais: SinaisProduto, api_key: str) -> dict:
    if not api_key:
        raise LLMIndisponivelError("GEMINI_API_KEY nao configurada")
    resposta = client.post(
        GEMINI_URL_TEMPLATE.format(modelo=GEMINI_MODELO),
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": _montar_prompt_usuario(sinais)}]}],
            "systemInstruction": {"parts": [{"text": PROMPT_SISTEMA}]},
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
        },
    )
    resposta.raise_for_status()
    corpo = resposta.json()
    return _extrair_json(corpo["candidates"][0]["content"]["parts"][0]["text"])


def gerar_sugestao_llm(sinais: SinaisProduto, *, client: httpx.Client | None = None) -> SugestaoLLM:
    """Tenta Groq; se falhar de qualquer forma (key ausente, timeout, erro
    HTTP, JSON malformado, campo fora da faixa), tenta Gemini. Se os dois
    falharem, levanta `LLMIndisponivelError` com o motivo de cada um."""
    settings = get_settings()
    fechar_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SEGUNDOS)

    preco_normal = Decimal(str(sinais.preco_normal))

    erros: list[str] = []
    try:
        try:
            dados = _chamar_groq(client, sinais, settings.groq_api_key)
            return _validar_resposta(dados, f"groq/{GROQ_MODELO}", preco_normal=preco_normal)
        except (httpx.HTTPError, LLMIndisponivelError, RespostaLLMInvalidaError) as e:
            erros.append(f"groq: {e}")

        try:
            dados = _chamar_gemini(client, sinais, settings.gemini_api_key)
            return _validar_resposta(dados, f"gemini/{GEMINI_MODELO}", preco_normal=preco_normal)
        except (httpx.HTTPError, LLMIndisponivelError, RespostaLLMInvalidaError) as e:
            erros.append(f"gemini: {e}")
    finally:
        if fechar_client:
            client.close()

    raise LLMIndisponivelError("; ".join(erros))
