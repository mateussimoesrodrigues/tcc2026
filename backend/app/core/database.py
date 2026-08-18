"""Engine e sessao do SQLAlchemy.

connect_args so se aplica para SQLite (fallback local de desenvolvimento);
contra o Postgres (Neon) esse dict fica vazio e o driver psycopg assume o
padrao (a exigencia de SSL ja vem embutida na propria DATABASE_URL).
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.using_sqlite_fallback else {}

engine = create_engine(
    settings.sqlalchemy_database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Classe base declarativa compartilhada por todos os modelos SQLAlchemy."""


def get_db() -> Generator[Session, None, None]:
    """Dependency do FastAPI: entrega uma sessao de banco por requisicao."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
