from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_funcionario
from app.schemas.historico_preco import HistoricoPrecoRead
from app.services import price_service

router = APIRouter(
    prefix="/historico-precos", tags=["historico-precos"], dependencies=[Depends(get_current_funcionario)]
)


@router.get("", response_model=list[HistoricoPrecoRead])
def listar(produto_id: int | None = None, db: Session = Depends(get_db)):
    registros = price_service.listar_historico(db, produto_id=produto_id)
    return [HistoricoPrecoRead.de_model(r) for r in registros]
