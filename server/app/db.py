from collections.abc import Generator

import structlog
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

logger = structlog.get_logger(__name__)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=settings.debug, connect_args=connect_args)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    logger.info("database_initialized", url=settings.database_url)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
