"""Importa todos os modelos para que fiquem registrados no Base.metadata
(necessario para o Alembic detectar as tabelas e para criar todas as
tabelas de uma vez em testes)."""
from app.models.categoria import Categoria
from app.models.produto import Produto
from app.models.produto_codigo import ProdutoCodigo
from app.models.estoque import Estoque
from app.models.funcionario import Funcionario
from app.models.sessao_carrinho import SessaoCarrinho
from app.models.carrinho_item import CarrinhoItem
from app.models.pedido import Pedido
from app.models.pedido_item import PedidoItem
from app.models.movimentacao_estoque import MovimentacaoEstoque
from app.models.promocao_sugestao import PromocaoSugestao
from app.models.historico_preco import HistoricoPreco
from app.models.display import Display
from app.models.simulacao_venda import SimulacaoVendaExecucao
from app.models.job_atualizacao import JobAtualizacao

__all__ = [
    "Categoria",
    "Produto",
    "ProdutoCodigo",
    "Estoque",
    "Funcionario",
    "SessaoCarrinho",
    "CarrinhoItem",
    "Pedido",
    "PedidoItem",
    "MovimentacaoEstoque",
    "PromocaoSugestao",
    "HistoricoPreco",
    "Display",
    "SimulacaoVendaExecucao",
    "JobAtualizacao",
]
