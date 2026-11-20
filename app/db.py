# Назначение файла: sync engine/session и транзакционный UnitOfWork.
from functools import lru_cache
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import settings


class Base(DeclarativeBase):
    pass


@lru_cache
def engine():
    url = settings().database_url
    result = create_engine(url, pool_pre_ping=True, **({'connect_args': {'check_same_thread': False}} if url.startswith('sqlite') else {}))
    if url.startswith('sqlite'):
        @event.listens_for(result, 'connect')
        def foreign_keys(conn, record):
            conn.execute('PRAGMA foreign_keys=ON')
    return result


class Uow:
    def __enter__(self):
        from app.repositories.data import Repo
        self.session = sessionmaker(engine(), expire_on_commit=False)()
        self.repo = Repo(self.session)
        return self

    def commit(self):
        self.session.commit()

    def __exit__(self, *args):
        self.session.rollback()
        self.session.close()
