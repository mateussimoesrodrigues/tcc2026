from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import criar_access_token, hash_senha, verificar_senha
from app.models.funcionario import Funcionario
from app.schemas.funcionario import FuncionarioCreate
from app.services.exceptions import CredenciaisInvalidasError, EmailJaCadastradoError


def criar_funcionario(db: Session, dados: FuncionarioCreate) -> Funcionario:
    existente = db.execute(
        select(Funcionario).where(Funcionario.email == dados.email)
    ).scalar_one_or_none()
    if existente is not None:
        raise EmailJaCadastradoError(dados.email)

    funcionario = Funcionario(
        nome=dados.nome,
        email=dados.email,
        senha_hash=hash_senha(dados.senha),
        papel=dados.papel,
    )
    db.add(funcionario)
    db.commit()
    db.refresh(funcionario)
    return funcionario


def autenticar(db: Session, email: str, senha: str) -> tuple[Funcionario, str]:
    funcionario = db.execute(
        select(Funcionario).where(Funcionario.email == email)
    ).scalar_one_or_none()
    if funcionario is None or not funcionario.ativo or not verificar_senha(senha, funcionario.senha_hash):
        raise CredenciaisInvalidasError()

    funcionario.ultimo_login_em = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    db.refresh(funcionario)

    token = criar_access_token(funcionario.id)
    return funcionario, token
