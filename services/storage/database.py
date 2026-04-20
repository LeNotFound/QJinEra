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
        #  以下为 V4.0 Schema 自适应升级逻辑 (保障已有数据库兼容)
        # -------------------------------------------------------------
        cursor = db.cursor()
        
        # 1. 检查 users 表是否需要补充 V4.0 字段 (intimacy_score, relationship_stage)
        cursor.execute("PRAGMA table_info(users)")
        users_columns = [col["name"] for col in cursor.fetchall()]
        if "intimacy_score" not in users_columns:
            db.execute("ALTER TABLE users ADD COLUMN intimacy_score INTEGER DEFAULT 0")
        if "relationship_stage" not in users_columns:
            db.execute("ALTER TABLE users ADD COLUMN relationship_stage TEXT DEFAULT 'Stranger'")

        # 2. 检查 memories 表是否是旧版 (有 user_id，没 subject_id)
        cursor.execute("PRAGMA table_info(memories)")
        memories_columns = [col["name"] for col in cursor.fetchall()]
        if "user_id" in memories_columns and "subject_id" not in memories_columns:
            # 这是一个重大结构调整：需要重建表或直接清空旧版表
            # 由于重构较大且测试阶段允许清空：备份 -> 删除 -> 重建
            db.execute("ALTER TABLE memories RENAME TO memories_v3_backup")
            db.executescript("""
                CREATE TABLE memories (
                    memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_id TEXT   NOT NULL,
                    source_id  TEXT   NOT NULL,
                    group_id   TEXT   NOT NULL,
                    content    TEXT   NOT NULL,
                    status     TEXT   DEFAULT 'active',
                    created_at REAL   NOT NULL,
                    UNIQUE(subject_id, content)
                );
            """)
            # V4的数据迁移：从旧版提取记忆到新版中
            db.execute("""
                INSERT OR IGNORE INTO memories (subject_id, source_id, group_id, content, status, created_at)
                SELECT user_id, user_id, group_id, content, status, timestamp
                FROM memories_v3_backup
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
