"""Validacao de resposta e orquestracao Groq->Gemini (app/ai/llm_provider.py).
Nunca bate em rede de verdade -- `_chamar_groq`/`_chamar_gemini` sao
monkeypatchados. As chamadas HTTP reais so sao exercitadas manualmente
(curl) quando as API keys estiverem configuradas."""
from decimal import Decimal

import pytest

from app.ai import llm_provider
from app.ai.rules import SinaisProduto
from app.services.exceptions import LLMIndisponivelError, RespostaLLMInvalidaError


def _sinais() -> SinaisProduto:
    return SinaisProduto(
        produto_id=1,
        nome="Produto X",
        marca=None,
        tamanho=None,
        preco_normal=20.0,
        estoque_atual=10,
        dias_sem_venda=45,
        unidades_vendidas_periodo=0,
        janela_dias=90,
        giro_diario=0.0,
        dias_de_estoque_restante=None,
        margem=0.3,
        proxima_data_sazonal="Natal",
        dias_ate_data_sazonal=100,
    )


# --- _validar_resposta ------------------------------------------------


def test_validar_resposta_ok():
    dados = {
        "percentual_desconto_sugerido": 15,
        "preco_sugerido": 17.0,
        "justificativa": "Produto parado ha 45 dias.",
        "prioridade": "Media",
    }
    resultado = llm_provider._validar_resposta(dados, "groq/teste")
    assert resultado.percentual_desconto == Decimal("15")
    assert resultado.preco_sugerido == Decimal("17.0")
    assert resultado.prioridade == "media"  # normalizado pra minusculo
    assert resultado.modelo_usado == "groq/teste"


def test_validar_resposta_desconto_fora_da_faixa():
    dados = {"percentual_desconto_sugerido": 90, "preco_sugerido": 2.0, "justificativa": "x", "prioridade": "alta"}
    with pytest.raises(RespostaLLMInvalidaError):
        llm_provider._validar_resposta(dados, "groq/teste")


def test_validar_resposta_preco_invalido():
    dados = {"percentual_desconto_sugerido": 10, "preco_sugerido": 0, "justificativa": "x", "prioridade": "alta"}
    with pytest.raises(RespostaLLMInvalidaError):
        llm_provider._validar_resposta(dados, "groq/teste")


def test_validar_resposta_campo_faltando():
    with pytest.raises(RespostaLLMInvalidaError):
        llm_provider._validar_resposta({"percentual_desconto_sugerido": 10}, "groq/teste")


def test_validar_resposta_justificativa_vazia():
    dados = {"percentual_desconto_sugerido": 10, "preco_sugerido": 18.0, "justificativa": "  ", "prioridade": "alta"}
    with pytest.raises(RespostaLLMInvalidaError):
        llm_provider._validar_resposta(dados, "groq/teste")


def test_validar_resposta_prioridade_invalida_vira_media():
    dados = {"percentual_desconto_sugerido": 10, "preco_sugerido": 18.0, "justificativa": "x", "prioridade": "urgente"}
    resultado = llm_provider._validar_resposta(dados, "groq/teste")
    assert resultado.prioridade == "media"


# --- gerar_sugestao_llm (orquestracao Groq -> Gemini) ------------------


def test_gerar_sugestao_llm_usa_groq_quando_disponivel(monkeypatch):
    monkeypatch.setattr(
        llm_provider,
        "_chamar_groq",
        lambda client, sinais, key: {
            "percentual_desconto_sugerido": 20,
            "preco_sugerido": 16.0,
            "justificativa": "ok",
            "prioridade": "alta",
        },
    )

    def _gemini_nao_deveria_ser_chamado(*args, **kwargs):
        raise AssertionError("Gemini nao deveria ser chamado se Groq funcionou")

    monkeypatch.setattr(llm_provider, "_chamar_gemini", _gemini_nao_deveria_ser_chamado)

    resultado = llm_provider.gerar_sugestao_llm(_sinais())
    assert resultado.modelo_usado.startswith("groq/")
    assert resultado.percentual_desconto == Decimal("20")


def test_gerar_sugestao_llm_cai_pro_gemini_se_groq_falhar(monkeypatch):
    def _groq_falha(client, sinais, key):
        raise LLMIndisponivelError("groq indisponivel")

    monkeypatch.setattr(llm_provider, "_chamar_groq", _groq_falha)
    monkeypatch.setattr(
        llm_provider,
        "_chamar_gemini",
        lambda client, sinais, key: {
            "percentual_desconto_sugerido": 10,
            "preco_sugerido": 18.0,
            "justificativa": "ok",
            "prioridade": "baixa",
        },
    )

    resultado = llm_provider.gerar_sugestao_llm(_sinais())
    assert resultado.modelo_usado.startswith("gemini/")


def test_gerar_sugestao_llm_cai_pro_gemini_se_groq_responder_invalido(monkeypatch):
    monkeypatch.setattr(
        llm_provider,
        "_chamar_groq",
        lambda client, sinais, key: {"percentual_desconto_sugerido": 999},  # invalido
    )
    monkeypatch.setattr(
        llm_provider,
        "_chamar_gemini",
        lambda client, sinais, key: {
            "percentual_desconto_sugerido": 10,
            "preco_sugerido": 18.0,
            "justificativa": "ok",
            "prioridade": "baixa",
        },
    )

    resultado = llm_provider.gerar_sugestao_llm(_sinais())
    assert resultado.modelo_usado.startswith("gemini/")


def test_gerar_sugestao_llm_levanta_erro_se_ambos_falharem(monkeypatch):
    def _falha(client, sinais, key):
        raise LLMIndisponivelError("sem key")

    monkeypatch.setattr(llm_provider, "_chamar_groq", _falha)
    monkeypatch.setattr(llm_provider, "_chamar_gemini", _falha)

    with pytest.raises(LLMIndisponivelError):
        llm_provider.gerar_sugestao_llm(_sinais())
