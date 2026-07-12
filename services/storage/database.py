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
                intimacy_score    INTEGER DEFAULT 0,
                relationship_stage TEXT   DEFAULT 'Stranger',
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
                memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id TEXT   NOT NULL,
                source_id  TEXT   NOT NULL,
                group_id   TEXT   NOT NULL,
                content    TEXT   NOT NULL,
                status     TEXT   DEFAULT 'active',
                created_at REAL   NOT NULL,
                UNIQUE(subject_id, content)
            );

            CREATE TABLE IF NOT EXISTS world_lore (
                lore_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id      TEXT    NOT NULL,
                entity_name   TEXT    NOT NULL,
                description   TEXT    NOT NULL,
                source_id     TEXT    NOT NULL,
                created_at    REAL    NOT NULL,
                updated_at    REAL    NOT NULL,
                UNIQUE(group_id, entity_name)
            );

            CREATE TABLE IF NOT EXISTS bot_status (
                bot_id        TEXT    PRIMARY KEY,
                energy        REAL    DEFAULT 100.0,
                mood          TEXT    DEFAULT '平静',
                current_state TEXT    DEFAULT 'active',
                last_updated  REAL    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS groups (
                group_id          TEXT    PRIMARY KEY,
                group_name        TEXT    DEFAULT '',
                intimacy_level    TEXT    DEFAULT 'public',
                behavior_overlay  TEXT    DEFAULT '',
                group_vibe        TEXT    DEFAULT '',
                created_at        REAL    NOT NULL DEFAULT 0,
                updated_at        REAL    NOT NULL DEFAULT 0
            );
        """)

        # -------------------------------------------------------------
        #  设置数据库版本 (V4.0 - 破坏性变更，不再兼容旧版 Schema)
        # -------------------------------------------------------------
        db.execute("PRAGMA user_version = 4")

        # -------------------------------------------------------------
        #  核心索引 — 加速高频查询路径
        # -------------------------------------------------------------
        db.executescript("""
            CREATE INDEX IF NOT EXISTS idx_messages_topic   ON messages(topic_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_topics_group     ON topics(group_id, start_time DESC);
            CREATE INDEX IF NOT EXISTS idx_memories_subject ON memories(subject_id, status, created_at);
            CREATE INDEX IF NOT EXISTS idx_decisions_group  ON decision_logs(group_id, timestamp);
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
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
