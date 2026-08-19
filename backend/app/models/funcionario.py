import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PapelFuncionario(str, enum.Enum):
    ADMIN = "admin"
    OPERADOR = "operador"


class Funcionario(Base):
    __tablename__ = "funcionario"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    papel: Mapped[PapelFuncionario] = mapped_column(
        Enum(PapelFuncionario), default=PapelFuncionario.OPERADOR, nullable=False
    )
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    ultimo_login_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
