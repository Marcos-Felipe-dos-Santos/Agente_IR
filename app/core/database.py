"""
Configuração do SQLAlchemy — engine, session e Base declarativa.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import DATABASE_URL


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},   # necessário para SQLite
    echo=False,
)


# Habilita WAL mode e foreign keys no SQLite para integridade referencial
@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Classe base para todos os modelos ORM."""
    pass


def get_db():
    """Dependency do FastAPI que fornece uma sessão de banco por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Cria todas as tabelas definidas nos modelos."""
    from app.models import entities  # noqa: F401  – importa para registrar os modelos
    Base.metadata.create_all(bind=engine)
