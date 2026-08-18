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
