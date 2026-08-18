from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.categoria import Categoria
from app.schemas.categoria import CategoriaCreate, CategoriaRead
from app.schemas.produto import (
    CodigoLookupResult,
    ProdutoCodigoCreate,
    ProdutoCreate,
    ProdutoRead,
    ProdutoUpdate,
)
from app.services import product_service
from app.services.exceptions import (
    CodigoJaCadastradoError,
    PrecoNaoInformadoError,
    ProdutoNaoEncontradoError,
)

router = APIRouter(tags=["produtos"])


@router.get("/categorias", response_model=list[CategoriaRead])
def listar_categorias(db: Session = Depends(get_db)):
    return db.execute(select(Categoria).order_by(Categoria.nome)).scalars().all()


@router.post("/categorias", response_model=CategoriaRead, status_code=status.HTTP_201_CREATED)
def criar_categoria(dados: CategoriaCreate, db: Session = Depends(get_db)):
    categoria = Categoria(**dados.model_dump())
    db.add(categoria)
    db.commit()
    db.refresh(categoria)
    return categoria


@router.get("/produtos", response_model=list[ProdutoRead])
def listar_produtos(
    categoria_id: int | None = None,
    busca: str | None = None,
    somente_ativos: bool = True,
    db: Session = Depends(get_db),
):
    return product_service.listar_produtos(
        db, categoria_id=categoria_id, busca=busca, somente_ativos=somente_ativos
    )


@router.get("/produtos/codigo/{codigo}", response_model=CodigoLookupResult)
def buscar_produto_por_codigo(codigo: str, db: Session = Depends(get_db)):
    """Usado no cadastro: o funcionario escaneia/digita o codigo antes de
    preencher o formulario. Se ja existir produto com esse codigo, devolve
    os dados (inclusive o preco) prontos; senao, `encontrado=false` e o
    frontend deve pedir o preco pra criar um produto novo."""
    produto = product_service.buscar_por_codigo(db, codigo)
    return CodigoLookupResult(encontrado=produto is not None, produto=produto)


@router.get("/produtos/{produto_id}", response_model=ProdutoRead)
def obter_produto(produto_id: int, db: Session = Depends(get_db)):
    try:
        return product_service.obter_produto(db, produto_id)
    except ProdutoNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produto nao encontrado")


@router.post("/produtos", response_model=ProdutoRead, status_code=status.HTTP_201_CREATED)
def criar_produto(dados: ProdutoCreate, db: Session = Depends(get_db)):
    try:
        return product_service.criar_produto(db, dados)
    except CodigoJaCadastradoError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Codigo '{e.codigo}' ja pertence ao produto {e.produto_id}. "
            "Ajuste o estoque do produto existente em vez de cadastrar um novo.",
        )
    except PrecoNaoInformadoError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Codigo novo: informe 'preco_normal' para cadastrar este produto.",
        )


@router.put("/produtos/{produto_id}", response_model=ProdutoRead)
def atualizar_produto(produto_id: int, dados: ProdutoUpdate, db: Session = Depends(get_db)):
    try:
        return product_service.atualizar_produto(db, produto_id, dados)
    except ProdutoNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produto nao encontrado")


@router.delete("/produtos/{produto_id}", response_model=ProdutoRead)
def desativar_produto(produto_id: int, db: Session = Depends(get_db)):
    """Soft delete: marca o produto como inativo em vez de apagar (mantem
    o historico de vendas/precos intacto para auditoria e para a IA)."""
    try:
        return product_service.desativar_produto(db, produto_id)
    except ProdutoNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produto nao encontrado")


@router.post("/produtos/{produto_id}/codigos", response_model=ProdutoRead, status_code=status.HTTP_201_CREATED)
def adicionar_codigo(produto_id: int, dados: ProdutoCodigoCreate, db: Session = Depends(get_db)):
    try:
        return product_service.adicionar_codigo(db, produto_id, dados.codigo, dados.tipo, dados.principal)
    except ProdutoNaoEncontradoError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produto nao encontrado")
    except CodigoJaCadastradoError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Codigo '{e.codigo}' ja pertence ao produto {e.produto_id}"
        )
