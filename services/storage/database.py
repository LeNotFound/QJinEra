"""
数据库连接管理器 — 集中管理 SQLite 连接与表结构初始化。

Usage:
    from services.storage.database import get_db

    with get_db() as db:
        db.execute("SELECT ...")
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Generator

from config import config


_DB_PATH: str = config.storage.database_file


def init_db() -> None:
    """初始化所有数据库表，启动时调用一次。"""
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS topics (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id    TEXT    NOT NULL,
                start_time  REAL    NOT NULL,
                end_time    REAL,
                summary     TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id    INTEGER NOT NULL,
                user_id     TEXT    NOT NULL,
                nickname    TEXT    DEFAULT '',
                content     TEXT    NOT NULL,
                timestamp   REAL    NOT NULL,
                FOREIGN KEY (topic_id) REFERENCES topics(id)
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id           TEXT    NOT NULL,
                group_id          TEXT    NOT NULL,
                nickname          TEXT    DEFAULT '',
                description       TEXT    DEFAULT '',
                interaction_count INTEGER DEFAULT 0,
                last_active_time  REAL,
                PRIMARY KEY (user_id, group_id)
            );

            CREATE TABLE IF NOT EXISTS decision_logs (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id          TEXT    NOT NULL,
                timestamp         REAL    NOT NULL,
                judge_model       TEXT,
                should_intervene  BOOLEAN,
                trigger_level     TEXT,
                reason            TEXT,
                context_summary   TEXT
            );

            CREATE TABLE IF NOT EXISTS memories (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   TEXT    NOT NULL,
                group_id  TEXT    NOT NULL,
                content   TEXT    NOT NULL,
                timestamp REAL    NOT NULL,
                status    TEXT    DEFAULT 'active',
                UNIQUE(user_id, content)
            );
        """)


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """获取数据库连接的上下文管理器。自动 commit / rollback / close。

    Usage:
        with get_db() as db:
            row = db.execute("SELECT ...").fetchone()
    """
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row          # 支持 row["column_name"] 访问
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
