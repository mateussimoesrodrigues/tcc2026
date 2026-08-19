"""Checagem de seguranca no boot: ambiente de producao com configuracao
insegura (JWT_SECRET_KEY padrao) deve falhar rapido, nao subir silencioso."""
import pytest

from app.core.config import ConfiguracaoProducaoInvalidaError, Settings, validar_configuracao_producao


def test_producao_com_chave_padrao_falha():
    settings = Settings(environment="production", jwt_secret_key=Settings.model_fields["jwt_secret_key"].default)
    with pytest.raises(ConfiguracaoProducaoInvalidaError):
        validar_configuracao_producao(settings)


def test_producao_com_chave_customizada_nao_falha():
    settings = Settings(environment="production", jwt_secret_key="uma-chave-de-verdade-bem-longa")
    validar_configuracao_producao(settings)  # nao deve levantar


def test_desenvolvimento_com_chave_padrao_nao_falha():
    settings = Settings(environment="development")
    validar_configuracao_producao(settings)  # nao deve levantar
