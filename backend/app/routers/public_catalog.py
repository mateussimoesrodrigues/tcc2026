from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.catalogo import CodigoPublicoLookupResult, ProdutoPublicoRead
from app.services import product_service

router = APIRouter(prefix="/catalogo", tags=["catalogo-publico"])
# Area publica (sem login) usada pelo scanner do cliente. Reaproveita
# `product_service.buscar_por_codigo` (mesma usada no cadastro pelo
# funcionario), mas responde com um schema restrito -- sem estoque/custo,
# que sao dados de gestao interna.


@router.get("/codigo/{codigo}", response_model=CodigoPublicoLookupResult)
def buscar_produto_por_codigo(codigo: str, db: Session = Depends(get_db)):
    produto = product_service.buscar_por_codigo(db, codigo)
    if produto is None or not produto.ativo:
        return CodigoPublicoLookupResult(encontrado=False)

    return CodigoPublicoLookupResult(
        encontrado=True,
        produto=ProdutoPublicoRead(
            produto_id=produto.id,
            nome=produto.nome,
            marca=produto.marca,
            tamanho=produto.tamanho,
            preco_vigente=produto.preco_vigente,
        ),
    )
