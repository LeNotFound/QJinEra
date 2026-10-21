"""
数据库连接管理器 — 集中管理 aiosqlite 异步连接与表结构初始化。

Usage:
    from services.storage.database import get_db

    async with get_db() as db:
        cursor = await db.execute("SELECT ...")
        rows = await cursor.fetchall()
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import aiosqlite

from config import config

_DB_PATH: str = config.storage.database_file


@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """获取异步数据库连接的上下文管理器。自动 commit / rollback / close。"""
    conn = await aiosqlite.connect(_DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
        await conn.close()


async def _migrate_schema(db: aiosqlite.Connection) -> None:
    """检查表结构并平滑升级老数据库字段。"""
    # 检查 users 表列
    cursor = await db.execute("PRAGMA table_info(users)")
    user_rows = await cursor.fetchall()
    user_cols = {row["name"] for row in user_rows}

    if "dynamic_status" not in user_cols:
        await db.execute("ALTER TABLE users ADD COLUMN dynamic_status TEXT DEFAULT ''")
    if "current_mood" not in user_cols:
        await db.execute("ALTER TABLE users ADD COLUMN current_mood TEXT DEFAULT ''")

    # 检查 bot_status 表列
    cursor = await db.execute("PRAGMA table_info(bot_status)")
    bot_rows = await cursor.fetchall()
    bot_cols = {row["name"] for row in bot_rows}

    bot_columns_to_add = [
        ("loneliness", "REAL DEFAULT 0.0"),
        ("dopamine", "REAL DEFAULT 50.0"),
        ("current_activity", "TEXT DEFAULT ''"),
        ("focus_user", "TEXT DEFAULT ''"),
        ("cur_objective", "TEXT DEFAULT ''"),
        ("empathy_mood", "TEXT DEFAULT ''"),
        ("active_concerns", "TEXT DEFAULT '[]'"),
    ]
    for col_name, col_def in bot_columns_to_add:
        if col_name not in bot_cols:
            await db.execute(f"ALTER TABLE bot_status ADD COLUMN {col_name} {col_def}")

    # 检查 world_lore 表列
    cursor = await db.execute("PRAGMA table_info(world_lore)")
    lore_rows = await cursor.fetchall()
    lore_cols = {row["name"] for row in lore_rows}
    if "scope" not in lore_cols:
        await db.execute("ALTER TABLE world_lore ADD COLUMN scope TEXT DEFAULT 'group'")


async def init_db() -> None:
    """初始化所有数据库表，启动时调用一次。"""
    async with get_db() as db:
        await db.executescript("""
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
                dynamic_status    TEXT    DEFAULT '',
                current_mood      TEXT    DEFAULT '',
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
                scope         TEXT    DEFAULT 'group',
                UNIQUE(group_id, entity_name)
            );

            CREATE TABLE IF NOT EXISTS bot_status (
                bot_id           TEXT    PRIMARY KEY,
                energy           REAL    DEFAULT 100.0,
                mood             TEXT    DEFAULT '平静',
                current_state    TEXT    DEFAULT 'active',
                loneliness       REAL    DEFAULT 0.0,
                dopamine         REAL    DEFAULT 50.0,
                current_activity TEXT    DEFAULT '',
                focus_user       TEXT    DEFAULT '',
                cur_objective    TEXT    DEFAULT '',
                empathy_mood     TEXT    DEFAULT '',
                active_concerns  TEXT    DEFAULT '[]',
                last_updated     REAL    NOT NULL
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

            CREATE INDEX IF NOT EXISTS idx_messages_topic   ON messages(topic_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_topics_group     ON topics(group_id, start_time DESC);
            CREATE INDEX IF NOT EXISTS idx_memories_subject ON memories(subject_id, status, created_at);
            CREATE INDEX IF NOT EXISTS idx_decisions_group  ON decision_logs(group_id, timestamp);
        """)

        await db.execute("PRAGMA user_version = 4")
        await _migrate_schema(db)
