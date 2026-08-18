"""Importa todos os modelos para que fiquem registrados no Base.metadata
(necessario para o Alembic detectar as tabelas e para criar todas as
tabelas de uma vez em testes)."""
from app.models.categoria import Categoria
from app.models.produto import Produto
from app.models.produto_codigo import ProdutoCodigo
from app.models.estoque import Estoque
from app.models.movimentacao_estoque import MovimentacaoEstoque

__all__ = ["Categoria", "Produto", "ProdutoCodigo", "Estoque", "MovimentacaoEstoque"]
