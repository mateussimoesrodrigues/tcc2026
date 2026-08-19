from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import exigir_admin, get_current_funcionario
from app.models.funcionario import Funcionario
from app.schemas.funcionario import FuncionarioCreate, FuncionarioRead, Token
from app.services import auth_service
from app.services.exceptions import CredenciaisInvalidasError, EmailJaCadastradoError

router = APIRouter(prefix="/auth", tags=["autenticacao"])


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # OAuth2PasswordRequestForm usa "username"; aqui o username e o email.
    try:
        funcionario, token = auth_service.autenticar(db, form_data.username, form_data.password)
    except CredenciaisInvalidasError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Email ou senha invalidos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=token, funcionario=funcionario)


@router.get("/me", response_model=FuncionarioRead)
def me(funcionario: Funcionario = Depends(get_current_funcionario)):
    return funcionario


@router.post(
    "/funcionarios",
    response_model=FuncionarioRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exigir_admin)],
)
def criar_funcionario(dados: FuncionarioCreate, db: Session = Depends(get_db)):
    """Cadastro de novos funcionarios -- so um admin logado pode criar
    outros. O primeiro admin do sistema vem do seed (ver app/seed.py)."""
    try:
        return auth_service.criar_funcionario(db, dados)
    except EmailJaCadastradoError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Email '{e.email}' ja cadastrado")
