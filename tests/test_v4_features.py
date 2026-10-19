"""
Unit and integration tests for V4.0 features:
- aiosqlite async database & schema migrations
- World Lore bidirectional fuzzy match
- Mind Relay (Judge state_updates -> bot_status/users -> Writer) & Circuit Breaker
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, patch

import pytest
from alicebot.adapter.cqhttp.event import GroupMessageEvent

from plugins.core import QJinEraPlugin
from services.llm import _persona_data, chat_template, judge_template
from services.storage import (
    bot_status as bot_status_store,
    database,
    users as user_store,
    world_lore,
)
from services.topic import topic_manager


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_v4_features.db"
    monkeypatch.setattr(database, "_DB_PATH", str(test_db))
    await database.init_db()
    yield test_db


@pytest.mark.asyncio
async def test_database_pragmas():
    """验证 WAL 模式、外键约束、busy_timeout=5000。"""
    async with database.get_db() as db:
        c1 = await db.execute("PRAGMA journal_mode")
        r1 = await c1.fetchone()
        assert r1[0].lower() == "wal"

        c2 = await db.execute("PRAGMA foreign_keys")
        r2 = await c2.fetchone()
        assert r2[0] == 1

        c3 = await db.execute("PRAGMA busy_timeout")
        r3 = await c3.fetchone()
        assert r3[0] == 5000


@pytest.mark.asyncio
async def test_legacy_database_migration(tmp_path):
    """验证向后兼容与老数据库的 ALTER TABLE 平滑升级逻辑。"""
    old_db_path = tmp_path / "old_qjinera.db"
    conn = sqlite3.connect(str(old_db_path))
    conn.execute("""
        CREATE TABLE users (
            user_id TEXT NOT NULL,
            group_id TEXT NOT NULL,
            nickname TEXT DEFAULT '',
            description TEXT DEFAULT '',
            interaction_count INTEGER DEFAULT 0,
            intimacy_score INTEGER DEFAULT 0,
            relationship_stage TEXT DEFAULT 'Stranger',
            last_active_time REAL,
            PRIMARY KEY (user_id, group_id)
        );
    """)
    conn.execute("""
        CREATE TABLE bot_status (
            bot_id TEXT PRIMARY KEY,
            energy REAL DEFAULT 100.0,
            mood TEXT DEFAULT '平静',
            current_state TEXT DEFAULT 'active',
            last_updated REAL NOT NULL
        );
    """)
    conn.execute("INSERT INTO users (user_id, group_id, nickname) VALUES ('u_old', 'g_old', 'LegacyGuy')")
    conn.execute("INSERT INTO bot_status (bot_id, last_updated) VALUES ('bot_old', 1000.0)")
    conn.commit()
    conn.close()

    # 使用迁移逻辑初始化老数据库
    with patch.object(database, "_DB_PATH", str(old_db_path)):
        await database.init_db()

        async with database.get_db() as db:
            cur = await db.execute("SELECT * FROM users WHERE user_id = 'u_old'")
            user_row = await cur.fetchone()
            assert user_row["nickname"] == "LegacyGuy"
            assert user_row["dynamic_status"] == ""
            assert user_row["current_mood"] == ""

            cur2 = await db.execute("SELECT * FROM bot_status WHERE bot_id = 'bot_old'")
            bot_row = await cur2.fetchone()
            assert bot_row["energy"] == 100.0
            assert bot_row["loneliness"] == 0.0
            assert bot_row["dopamine"] == 50.0
            assert bot_row["current_activity"] == ""
            assert bot_row["focus_user"] == ""
            assert bot_row["cur_objective"] == ""
            assert bot_row["empathy_mood"] == ""
            assert bot_row["active_concerns"] == "[]"


@pytest.mark.asyncio
async def test_world_lore_fuzzy_and_exact():
    """验证 World Lore 精确匹配与双向模糊匹配、单字过滤及去重。"""
    gid = "test_lore_group"
    await world_lore.add_or_update(gid, "u1", "王者荣耀", "一款热门MOBA手游")
    await world_lore.add_or_update(gid, "u1", "原神", "米哈游动作RPG")
    await world_lore.add_or_update(gid, "u1", "奶黄包", "群吉祥物，一只可爱的布偶猫")
    await world_lore.add_or_update(gid, "u1", "吃奶黄包", "群特有梗，指撸猫")

    # 1. 精确匹配
    res1 = await world_lore.get_by_entities(gid, ["王者荣耀"])
    assert len(res1["exact"]) == 1
    assert res1["exact"][0]["entity_name"] == "王者荣耀"
    assert len(res1["fuzzy"]) == 0

    # 2. 模糊匹配：实体包含表里的设定名 ("王者荣耀手游" 包含 "王者荣耀")
    res2 = await world_lore.get_by_entities(gid, ["王者荣耀手游"])
    assert len(res2["exact"]) == 0
    assert len(res2["fuzzy"]) == 1
    assert res2["fuzzy"][0]["entity_name"] == "王者荣耀"

    # 3. 模糊匹配：表里的设定名包含实体 (提取实体 "奶黄" -> 命中 "奶黄包" 和 "吃奶黄包")
    res3 = await world_lore.get_by_entities(gid, ["奶黄"])
    assert len(res3["exact"]) == 0
    assert len(res3["fuzzy"]) == 2
    matched_names = {r["entity_name"] for r in res3["fuzzy"]}
    assert matched_names == {"奶黄包", "吃奶黄包"}

    # 4. 精确与模糊去重：精确匹配项绝不会重复出现在模糊匹配中
    res4 = await world_lore.get_by_entities(gid, ["奶黄包", "奶黄"])
    assert len(res4["exact"]) == 1
    assert res4["exact"][0]["entity_name"] == "奶黄包"
    assert len(res4["fuzzy"]) == 1
    assert res4["fuzzy"][0]["entity_name"] == "吃奶黄包"

    # 5. 单字噪声过滤：单字符不会触发 SQL LIKE 严重噪音
    res5 = await world_lore.get_by_entities(gid, ["猫", "包"])
    assert res5 == {"exact": [], "fuzzy": []}

    # 6. 空实体列表
    res6 = await world_lore.get_by_entities(gid, [])
    assert res6 == {"exact": [], "fuzzy": []}


def test_chat_system_template_rendering():
    """验证 chat_system.jinja 渲染潜意识研判、高维心智状态、断路器及 World Lore。"""
    rendered = chat_template.render(
        persona=_persona_data,
        bot_status={
            "energy": 88.0,
            "mood": "温柔",
            "empathy_mood": "心疼",
            "cur_objective": "安静托底",
            "focus_user": "user_777",
        },
        user_profile={
            "intimacy_score": 60,
            "relationship_stage": "Friend",
            "current_mood": "脆弱低落",
            "dynamic_status": "熬夜",
        },
        world_lore={
            "exact": [{"entity_name": "王者荣耀", "description": "MOBA游戏"}],
            "fuzzy": [{"entity_name": "奶黄包", "description": "布偶猫"}],
        },
        group_context={"group_vibe": "温馨安详"},
        intervention_reason="用户表达了疲惫，需要陪伴",
        circuit_breaker_directive="[系统指令：用户极度脆弱，回复绝不超30字，纯粹托底，不要建议，禁止道德绑架，禁止说教]",
    )

    assert "【群组设定与专属记忆 (World Lore)】" in rendered
    assert "> 高度相关（明确提及）：" in rendered
    assert "[王者荣耀]: MOBA游戏" in rendered
    assert "> 潜在相关（供你参考，如果你的上下文判断发现它们并非用户意指，请无视）：" in rendered
    assert "[奶黄包]: 布偶猫" in rendered
    assert "此时你内在的共情情绪 (Empathy Mood)：心疼" in rendered
    assert "你的潜意识当前目标 (Objective)：安静托底" in rendered
    assert "当前专注锁定对象：用户 user_777" in rendered
    assert "潜意识研判指引 (Judge Insight)：用户表达了疲惫，需要陪伴" in rendered
    assert "对方当前的心理状态：脆弱低落" in rendered
    assert "对方当前的动态体征：熬夜" in rendered
    assert "【危机断路器最高指令 (Circuit Breaker)】" in rendered
    assert "[系统指令：用户极度脆弱，回复绝不超30字，纯粹托底，不要建议，禁止道德绑架，禁止说教]" in rendered


def test_judge_system_template_rendering():
    """验证 judge_system.jinja 升级包含 crisis 判定级别及 state_updates JSON。"""
    rendered = judge_template.render(
        persona=_persona_data,
        bot_id="1106447644",
        group_context={"intimacy_level": "private", "behavior_overlay": "保持克制", "group_vibe": "安静"},
    )
    assert '"crisis"' in rendered
    assert '"state_updates"' in rendered
    assert '"empathy_mood"' in rendered
    assert "危机研判与断路机制 (Crisis Trigger)" in rendered


@pytest.mark.asyncio
async def test_mind_relay_and_circuit_breaker():
    """验证 Judge 输出的 state_updates 写回数据库，以及 crisis 级别触发断路器。"""
    plugin = QJinEraPlugin()
    event = AsyncMock(spec=GroupMessageEvent)
    event.group_id = 9901
    event.user_id = 8801
    event.message = "我好绝望，感觉活着没有任何意义了"
    event.self_id = 1106447644
    event.reply = AsyncMock()

    judge_result = {
        "should_intervene": False,  # 即使模型误判 should_intervene: false，crisis 也会强行插话
        "trigger_level": "crisis",
        "reason": "用户绝望自毁倾向，生命安全危机警报",
        "has_significant_info": False,
        "topic_shifted": False,
        "mentioned_entities": [],
        "state_updates": {
            "empathy_mood": "极度心疼与紧绷",
            "cur_objective": "安静托底，无条件接纳，绝不说道理",
            "focus_user": "8801",
            "user_dynamic_status": "濒临崩溃",
            "user_mood": "绝望",
        },
    }

    with patch("services.llm.judge_interruption", new_callable=AsyncMock, return_value=judge_result), \
         patch("services.llm.generate_chat", new_callable=AsyncMock, return_value={"messages": ["我在。别怕，我一直在。"]}), \
         patch("services.topic.topic_manager.is_group_allowed", return_value=True):

        await topic_manager.handle_message(
            str(event.group_id), str(event.user_id), event.message, "User8801", str(event.self_id)
        )

        await plugin._debounce_then_judge(str(event.group_id), event)

        # 验证断路器强制介入发送回复
        event.reply.assert_called_once_with("我在。别怕，我一直在。")

        # 验证 bot_status 写回
        bot_st = await bot_status_store.get(str(event.self_id))
        assert bot_st is not None
        assert bot_st["empathy_mood"] == "极度心疼与紧绷"
        assert bot_st["cur_objective"] == "安静托底，无条件接纳，绝不说道理"
        assert bot_st["focus_user"] == "8801"

        # 验证 users 表写回
        u = await user_store.get(str(event.group_id), str(event.user_id))
        assert u is not None
        assert u["dynamic_status"] == "濒临崩溃"
        assert u["current_mood"] == "绝望"
