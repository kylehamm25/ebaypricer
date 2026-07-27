import sqlite3
from contextlib import contextmanager
from dashboard.backend.config import DB_PATH_STR


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH_STR)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    try:
        yield conn
    finally:
        conn.close()
