"""Regras de negocio do catalogo de produtos.

Fluxo de cadastro (pedido do usuario): quando o funcionario cadastra um
produto, o sistema primeiro verifica se aquele codigo de barras/QR ja tem
um preco registrado no banco -- se tiver, usa esse preco automaticamente;
se nao tiver, exige que o funcionario informe o preco (`preco_normal`)
na hora de criar. Ver `buscar_por_codigo` (usado pelo endpoint de lookup)
e `criar_produto` (usa o mesmo lookup internamente antes de exigir preco).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.estoque import Estoque
from app.models.produto import Produto
from app.models.produto_codigo import ProdutoCodigo
from app.schemas.produto import ProdutoCreate, ProdutoUpdate
from app.services.exceptions import (
    CodigoJaCadastradoError,
    PrecoNaoInformadoError,
    ProdutoNaoEncontradoError,
)

_PRODUTO_OPTIONS = (joinedload(Produto.codigos), joinedload(Produto.estoque))


def listar_produtos(
    db: Session,
    *,
    categoria_id: int | None = None,
    busca: str | None = None,
    somente_ativos: bool = True,
) -> list[Produto]:
    stmt = select(Produto).options(*_PRODUTO_OPTIONS).order_by(Produto.nome)
    if somente_ativos:
        stmt = stmt.where(Produto.ativo.is_(True))
    if categoria_id is not None:
        stmt = stmt.where(Produto.categoria_id == categoria_id)
    if busca:
        stmt = stmt.where(Produto.nome.ilike(f"%{busca}%"))
    return list(db.execute(stmt).unique().scalars())


def obter_produto(db: Session, produto_id: int) -> Produto:
    produto = db.execute(
        select(Produto).options(*_PRODUTO_OPTIONS).where(Produto.id == produto_id)
    ).unique().scalar_one_or_none()
    if produto is None:
        raise ProdutoNaoEncontradoError(str(produto_id))
    return produto


def buscar_por_codigo(db: Session, codigo: str) -> Produto | None:
    """Usado tanto pelo endpoint de lookup (pre-preenchimento no cadastro)
    quanto pelo scanner do cliente (Fase 3) para resolver um produto a
    partir do codigo escaneado."""
    stmt = (
        select(Produto)
        .join(ProdutoCodigo)
        .options(*_PRODUTO_OPTIONS)
        .where(ProdutoCodigo.codigo == codigo)
    )
    return db.execute(stmt).unique().scalar_one_or_none()


def criar_produto(db: Session, dados: ProdutoCreate) -> Produto:
    codigo_existente = db.execute(
        select(ProdutoCodigo).where(ProdutoCodigo.codigo == dados.codigo)
    ).scalar_one_or_none()
    if codigo_existente is not None:
        raise CodigoJaCadastradoError(dados.codigo, codigo_existente.produto_id)

    preco_normal = dados.preco_normal
    if preco_normal is None:
        # Nao veio preco explicito: tenta reaproveitar de um cadastro
        # anterior com o mesmo nome+marca+tamanho (mesmo produto, codigo
        # de barras diferente -- ex.: fornecedor trocou o lote).
        produto_conhecido = db.execute(
            select(Produto).where(
                Produto.nome == dados.nome,
                Produto.marca == dados.marca,
                Produto.tamanho == dados.tamanho,
            )
        ).scalar_one_or_none()
        if produto_conhecido is not None:
            preco_normal = produto_conhecido.preco_normal
        else:
            raise PrecoNaoInformadoError()

    produto = Produto(
        categoria_id=dados.categoria_id,
        nome=dados.nome,
        marca=dados.marca,
        tamanho=dados.tamanho,
        custo=dados.custo,
        preco_normal=preco_normal,
    )
    db.add(produto)
    db.flush()

    db.add(
        ProdutoCodigo(
            produto_id=produto.id,
            tipo=dados.tipo_codigo,
            codigo=dados.codigo,
            principal=True,
        )
    )
    db.add(Estoque(produto_id=produto.id, quantidade=dados.quantidade_inicial))

    db.commit()
    return obter_produto(db, produto.id)


def atualizar_produto(db: Session, produto_id: int, dados: ProdutoUpdate) -> Produto:
    produto = obter_produto(db, produto_id)
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(produto, campo, valor)
    db.commit()
    return obter_produto(db, produto_id)


def desativar_produto(db: Session, produto_id: int) -> Produto:
    produto = obter_produto(db, produto_id)
    produto.ativo = False
    db.commit()
    return obter_produto(db, produto_id)


def adicionar_codigo(db: Session, produto_id: int, codigo: str, tipo, principal: bool = False) -> Produto:
    obter_produto(db, produto_id)  # valida que existe (levanta 404 senao)
    existente = db.execute(
        select(ProdutoCodigo).where(ProdutoCodigo.codigo == codigo)
    ).scalar_one_or_none()
    if existente is not None:
        raise CodigoJaCadastradoError(codigo, existente.produto_id)

    db.add(ProdutoCodigo(produto_id=produto_id, tipo=tipo, codigo=codigo, principal=principal))
    db.commit()
    return obter_produto(db, produto_id)
