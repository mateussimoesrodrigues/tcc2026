"""Excecoes de dominio dos services. Os routers traduzem para HTTPException
com o status code apropriado -- mantem a camada de service livre de FastAPI."""


class ProdutoNaoEncontradoError(Exception):
    pass


class CodigoJaCadastradoError(Exception):
    """Codigo de barras/QR ja pertence a outro produto."""

    def __init__(self, codigo: str, produto_id: int):
        self.codigo = codigo
        self.produto_id = produto_id
        super().__init__(f"Codigo {codigo} ja cadastrado no produto {produto_id}")


class PrecoNaoInformadoError(Exception):
    """Codigo novo (sem cadastro previo) e nenhum preco foi informado."""


class EmailJaCadastradoError(Exception):
    def __init__(self, email: str):
        self.email = email
        super().__init__(f"Email {email} ja cadastrado")


class CredenciaisInvalidasError(Exception):
    pass


class SessaoCarrinhoInvalidaError(Exception):
    """Sessao de carrinho inexistente, expirada ou ja finalizada/abandonada."""

    def __init__(self, sessao_id: str):
        self.sessao_id = sessao_id
        super().__init__(f"Sessao de carrinho {sessao_id} invalida")


class CarrinhoVazioError(Exception):
    pass


class EstoqueInsuficienteError(Exception):
    """Um ou mais itens do carrinho nao tem estoque suficiente no momento
    do checkout. `itens` traz (produto_id, nome, solicitado, disponivel)."""

    def __init__(self, itens: list[dict]):
        self.itens = itens
        super().__init__("Estoque insuficiente para um ou mais itens do carrinho")


class LLMIndisponivelError(Exception):
    """Nem o provedor primario (Groq) nem o fallback (Gemini) responderam
    -- key ausente, timeout, erro HTTP. O produto fica sem sugestao nessa
    rodada; nao interrompe os demais candidatos."""


class RespostaLLMInvalidaError(Exception):
    """O LLM respondeu, mas fora do formato/faixa esperados (JSON malformado,
    campo faltando, desconto fora de 0-70%, preco <= 0)."""


class SugestaoNaoEncontradaError(Exception):
    pass


class SugestaoJaAvaliadaError(Exception):
    """Sugestao ja aprovada/rejeitada/expirada -- nao pode ser avaliada de novo."""
