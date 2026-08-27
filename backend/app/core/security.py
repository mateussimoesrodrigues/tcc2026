"""Hash de senha, emissao/validacao de JWT e dependency de autenticacao do
funcionario. Usado pelas rotas protegidas (gestao de produtos/estoque e,
mais pra frente, aprovacao de promocoes)."""
from datetime import datetime, timedelta, UTC

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models.display import Display
from app.models.funcionario import Funcionario

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_senha(senha: str) -> str:
    return pwd_context.hash(senha)


def verificar_senha(senha: str, senha_hash: str) -> bool:
    return pwd_context.verify(senha, senha_hash)


def criar_access_token(funcionario_id: int) -> str:
    expira_em = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(funcionario_id), "exp": expira_em}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _credenciais_invalidas() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nao foi possivel validar as credenciais",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_funcionario(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> Funcionario:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        funcionario_id = payload.get("sub")
        if funcionario_id is None:
            raise _credenciais_invalidas()
    except JWTError:
        raise _credenciais_invalidas()

    funcionario = db.execute(
        select(Funcionario).where(Funcionario.id == int(funcionario_id))
    ).scalar_one_or_none()
    if funcionario is None or not funcionario.ativo:
        raise _credenciais_invalidas()
    return funcionario


def exigir_admin(funcionario: Funcionario = Depends(get_current_funcionario)) -> Funcionario:
    if funcionario.papel.value != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requer papel de administrador")
    return funcionario


def get_display_by_token(
    x_display_token: str = Header(..., alias="X-Display-Token"),
    db: Session = Depends(get_db),
) -> Display:
    """Autenticacao dos displays fisicos: nao usam login de funcionario
    (JWT), so um token opaco por dispositivo gravado no firmware na hora
    de configurar (ver `services/display_service.criar_display`). Mandado
    no header `X-Display-Token` em toda chamada a
    `POST /displays/sincronizar`."""
    display = db.execute(select(Display).where(Display.token == x_display_token)).scalar_one_or_none()
    if display is None or not display.ativo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de display invalido ou desativado")
    return display
