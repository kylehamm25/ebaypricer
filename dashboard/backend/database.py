from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from dashboard.backend.config import DATABASE_URL

_pool: ConnectionPool | None = None


def init_pool():
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
        )
        _pool.open()
    return _pool


def close_pool():
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_db(read_only: bool = True):
    if _pool is None:
        init_pool()
    with _pool.connection() as conn:
        if read_only:
            conn.execute("SET TRANSACTION READ ONLY")
        yield conn
