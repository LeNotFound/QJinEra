"""生命引擎 (Life Engine) 状态机、离线生活系统与省电模式完整测试套件。"""

from __future__ import annotations

import asyncio
import datetime
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from alicebot.adapter.cqhttp.event import GroupMessageEvent

from config import config
from plugins.core import QJinEraPlugin
from services import life_engine
from services.llm import _persona_data, chat_template, judge_template, proactive_template
from services.scheduler import _loop
from services.storage import bot_status as bot_status_store, database
from services.topic import topic_manager


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_life_engine.db"
    monkeypatch.setattr(database, "_DB_PATH", str(test_db))
    await database.init_db()
    yield test_db


# ---------------------------------------------------------------------------
#  1. 纯计算与状态判断辅助函数测试
# ---------------------------------------------------------------------------

def test_compute_energy_cost_and_dopamine():
    """验证能耗（正负数兼容、字符串与极端值）与多巴胺增量转换。"""
    assert life_engine.compute_energy_cost(15) == 15.0
    assert life_engine.compute_energy_cost(-15) == 15.0
    assert life_engine.compute_energy_cost("-12.5") == 12.5
    assert life_engine.compute_energy_cost(None) == 0.0
    assert life_engine.compute_energy_cost("invalid") == 0.0

    assert life_engine.compute_dopamine_delta(5.0) == 5.0
    assert life_engine.compute_dopamine_delta(-8.0) == -8.0
    assert life_engine.compute_dopamine_delta("+10") == 10.0
    assert life_engine.compute_dopamine_delta(None) == 0.0
    assert life_engine.compute_dopamine_delta("invalid") == 0.0


def test_is_sleep_time():
    """验证昼夜作息判定 (23:00 - 07:00 为夜间休眠时段)。"""
    # 夜间
    assert life_engine.is_sleep_time(datetime.datetime(2026, 10, 20, 23, 0, 0)) is True
    assert life_engine.is_sleep_time(datetime.datetime(2026, 10, 20, 23, 59, 59)) is True
    assert life_engine.is_sleep_time(datetime.datetime(2026, 10, 20, 0, 0, 0)) is True
    assert life_engine.is_sleep_time(datetime.datetime(2026, 10, 20, 3, 30, 0)) is True
    assert life_engine.is_sleep_time(datetime.datetime(2026, 10, 20, 6, 59, 59)) is True

    # 白天
    assert life_engine.is_sleep_time(datetime.datetime(2026, 10, 20, 7, 0, 0)) is False
    assert life_engine.is_sleep_time(datetime.datetime(2026, 10, 20, 12, 0, 0)) is False
    assert life_engine.is_sleep_time(datetime.datetime(2026, 10, 20, 18, 30, 0)) is False
    assert life_engine.is_sleep_time(datetime.datetime(2026, 10, 20, 22, 59, 59)) is False


def test_is_low_energy():
    """验证低电量省电模式判定 (阈值 40.0)。"""
    assert life_engine.is_low_energy(None) is False
    assert life_engine.is_low_energy({"energy": 100.0, "current_state": "active"}) is False
    assert life_engine.is_low_energy({"energy": 40.0, "current_state": "active"}) is False
    assert life_engine.is_low_energy({"energy": 39.9, "current_state": "active"}) is True
    assert life_engine.is_low_energy({"energy": 10.0, "current_state": "active"}) is True
    assert life_engine.is_low_energy({"energy": 80.0, "current_state": "power_saving"}) is True


# ---------------------------------------------------------------------------
#  2. 交互驱动测试 (Event-Driven)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_apply_interaction_cost_event_driven():
    """验证交互驱动下思维疲惫、多巴胺流动及省电模式自动切入。"""
    bot_id = "test_bot_1"
    await bot_status_store.upsert(
        bot_id=bot_id,
        energy=60.0,
        mood="平静",
        current_state="active",
        loneliness=20.0,
        dopamine=50.0,
    )

    # 1. 普通闲聊消耗：energy_cost = 5, dopamine_delta = +10
    st1 = await life_engine.apply_interaction_cost(bot_id, energy_cost=5.0, dopamine_delta=10.0)
    assert st1["energy"] == 55.0
    assert st1["dopamine"] == 60.0
    assert st1["loneliness"] == 18.0  # 互动减少孤独感
    assert st1["current_state"] == "active"

    # 2. 深刻探讨大消耗：energy_cost = -25 (跌破 40 阈值)
    st2 = await life_engine.apply_interaction_cost(bot_id, energy_cost="-25", dopamine_delta="-5")
    assert st2["energy"] == 30.0
    assert st2["dopamine"] == 55.0
    assert st2["current_state"] == "power_saving"  # 自动切入低电量省电模式

    # 3. 边界值截断保护：超大消耗不会跌破 0
    st3 = await life_engine.apply_interaction_cost(bot_id, energy_cost=100.0)
    assert st3["energy"] == 0.0
    assert st3["current_state"] == "power_saving"

    # 4. 回血后自动解除省电模式
    await bot_status_store.update_state(bot_id, energy=45.0)
    st4 = await life_engine.apply_interaction_cost(bot_id, energy_cost=2.0)
    assert st4["energy"] == 43.0
    assert st4["current_state"] == "active"


# ---------------------------------------------------------------------------
#  3. 时间驱动测试 (Time-Driven)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_time_driven_sleep_and_recovery():
    """验证夜间休眠作息推进与回血机制 (+15/hr)。"""
    bot_id = "test_bot_sleep"
    t0 = datetime.datetime(2026, 10, 20, 23, 0, 0)
    ts0 = t0.timestamp()

    # 初始状态：精力 20.0，低电量省电模式
    await bot_status_store.upsert(
        bot_id=bot_id,
        energy=20.0,
        mood="疲惫",
        current_state="power_saving",
        loneliness=30.0,
        dopamine=30.0,
        last_updated=ts0,
    )

    # 模拟经过 4 小时夜间休眠 (到 03:00)
    t1 = datetime.datetime(2026, 10, 21, 3, 0, 0)
    ts1 = t1.timestamp()
    st1 = await life_engine.tick(bot_id, current_time=t1, now_ts=ts1)

    assert st1["current_state"] == "sleeping"
    assert st1["current_activity"] == "睡眠休眠中"
    # 回血: 20 + 4 * 15 = 80
    assert st1["energy"] == 80.0
    # 多巴胺向基线 50 缓慢平复 (30 + 4*4 = 46)
    assert st1["dopamine"] == 46.0
    # 孤独感减少 (30 - 4*2 = 22)
    assert st1["loneliness"] == 22.0

    # 再经过 4 小时 (到 07:00，刚好苏醒边界)
    t2 = datetime.datetime(2026, 10, 21, 7, 0, 1)
    ts2 = t2.timestamp()
    st2 = await life_engine.tick(bot_id, current_time=t2, now_ts=ts2)

    # 白天苏醒，精力 80 + 4*15 = 140 -> 封顶 100.0
    assert st2["energy"] == 100.0
    assert st2["current_state"] == "active"
    assert st2["current_activity"] != "睡眠休眠中"


@pytest.mark.asyncio
async def test_time_driven_offline_activity_simulation():
    """验证白天静默期 0 Token 离线生活活动模拟与主动话题沉淀。"""
    bot_id = "test_bot_offline"
    t0 = datetime.datetime(2026, 10, 21, 14, 0, 0)
    ts0 = t0.timestamp()

    await bot_status_store.upsert(
        bot_id=bot_id,
        energy=70.0,
        mood="平静",
        current_state="active",
        loneliness=10.0,
        dopamine=50.0,
        current_activity="",
        last_updated=ts0,
    )

    # tick 触发离线活动抽取
    st = await life_engine.tick(bot_id, current_time=t0, now_ts=ts0, force_activity=True)

    assert st["current_activity"] != ""
    assert st["cur_objective"] != ""  # 沉淀出主动生活话题
    assert len(st["active_concerns"]) == 1
    assert st["active_concerns"][0]["type"] == "offline_activity"
    assert st["active_concerns"][0]["topic"] == st["cur_objective"]


# ---------------------------------------------------------------------------
#  4. 模板渲染测试 (Judge, Chat, Proactive)
# ---------------------------------------------------------------------------

def test_judge_system_template_with_life_engine():
    """验证 Judge 模板中注入 bot_status 及低电量谨慎判定指引。"""
    # 1. 正常状态
    r1 = judge_template.render(
        persona=_persona_data,
        bot_id="1106447644",
        bot_status={"energy": 85.0, "current_state": "active"},
    )
    assert "当前精力值 (Energy)：85.0/100。" in r1
    assert "运行状态：active。" in r1
    assert "【低电量省电模式 (Power-Saving)】" not in r1
    assert '"energy_cost"' in r1
    assert '"dopamine_delta"' in r1

    # 2. 低电量省电状态
    r2 = judge_template.render(
        persona=_persona_data,
        bot_id="1106447644",
        bot_status={"energy": 30.0, "current_state": "power_saving"},
    )
    assert "【低电量省电模式 (Power-Saving)】" in r2
    assert "优先选择克制沉默" in r2

    # 3. 夜间休眠状态
    r3 = judge_template.render(
        persona=_persona_data,
        bot_id="1106447644",
        bot_status={"energy": 80.0, "current_state": "sleeping"},
    )
    assert "【夜间休眠状态 (Sleeping)】" in r3
    assert "安心休眠充电" in r3


def test_chat_system_template_power_saving_mode():
    """验证 Writer 聊天模板在低电量省电模式下的慵懒极简指令注入。"""
    # 1. 正常活跃
    r1 = chat_template.render(
        persona=_persona_data,
        bot_status={"energy": 90.0, "current_state": "active", "current_activity": "看书 (天体物理)"},
    )
    assert "当前运行状态：active。" in r1
    assert "你当前/刚才在做的事：看书 (天体物理)。" in r1
    assert "【当前运行状态：低电量省电模式 (Power-Saving Mode)】" not in r1
    assert '"energy_cost"' in r1
    assert '"dopamine_delta"' in r1

    # 2. 低电量省电状态
    r2 = chat_template.render(
        persona=_persona_data,
        bot_status={"energy": 28.5, "current_state": "power_saving"},
    )
    assert "【当前运行状态：低电量省电模式 (Power-Saving Mode)】" in r2
    assert "思维极度疲惫，大脑近乎宕机" in r2
    assert "回复风格：极度简短、松弛、慵懒" in r2

    # 3. 夜间休眠被唤醒状态
    r3 = chat_template.render(
        persona=_persona_data,
        bot_status={"energy": 65.0, "current_state": "sleeping"},
    )
    assert "【当前运行状态：夜间休眠被唤醒 (Sleeping / Drowsy)】" in r3
    assert "带着些许被吵醒的困意" in r3


def test_proactive_system_template_with_offline_activity():
    """验证主动话题生成模板融入离线生活状态与沉淀话题。"""
    r = proactive_template.render(
        persona=_persona_data,
        bot_status={
            "energy": 35.0,
            "current_state": "power_saving",
            "current_activity": "发呆放空 (趴在窗台看天上的云和晚霞)",
            "cur_objective": "刚才趴在窗边看了好一会儿云，像融化的棉花糖",
        },
    )
    assert "【你此刻的真实生活与生理状态】" in r
    assert "发呆放空 (趴在窗台看天上的云和晚霞)" in r
    assert "刚才趴在窗边看了好一会儿云，像融化的棉花糖" in r
    assert "你现在精力较低（处于省电模式），语气可以慵懒随意一点" in r


# ---------------------------------------------------------------------------
#  5. 全链路集成测试 (CorePlugin 交互驱动与低电量自动降级)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_end_to_end_event_driven_pipeline():
    """验证完整交互链路：Judge 返回 energy_cost -> 扣减精力 -> Writer 返回 energy_cost -> 跌破阈值进入省电极简回复。"""
    plugin = QJinEraPlugin()
    event = AsyncMock(spec=GroupMessageEvent)
    event.group_id = 10020
    event.user_id = 20030
    event.message = "年年，我们来聊聊死亡和宇宙的终极意义吧。"
    event.self_id = 1106447644
    event.reply = AsyncMock()

    # 初始状态：精力 50.0
    await bot_status_store.upsert(
        bot_id=str(event.self_id),
        energy=50.0,
        mood="平静",
        current_state="active",
    )

    # 模拟 Judge 判定进行深度哲学思辨，消耗 -12 点精力
    judge_result = {
        "should_intervene": True,
        "trigger_level": "medium",
        "reason": "深度哲学话题介入",
        "has_significant_info": False,
        "topic_shifted": False,
        "mentioned_entities": [],
        "state_updates": {
            "energy_cost": -12.0,
            "dopamine_delta": 4.0,
            "empathy_mood": "深邃沉静",
            "cur_objective": "探讨终极意义",
        },
    }

    # 模拟 Writer 生成深度思考回复，再消耗 10 点精力 (50 - 12 - 10 = 28 < 40)
    writer_result = {
        "messages": ["终极意义可能就是没有意义，所以每一个呼吸才弥足珍贵。"],
        "summary": "关于死亡与宇宙终极意义的探讨",
        "energy_cost": 10.0,
        "dopamine_delta": 2.0,
    }

    with patch("services.llm.judge_interruption", new_callable=AsyncMock, return_value=judge_result), \
         patch("services.llm.generate_chat", new_callable=AsyncMock, return_value=writer_result), \
         patch("services.topic.topic_manager.is_group_allowed", return_value=True):

        await topic_manager.handle_message(
            str(event.group_id), str(event.user_id), event.message, "Philosopher", str(event.self_id)
        )

        await plugin._debounce_then_judge(str(event.group_id), event)

        # 验证回复发送
        event.reply.assert_called_once_with("终极意义可能就是没有意义，所以每一个呼吸才弥足珍贵。")

        # 验证精力消耗并进入省电模式 (50 - 12 - 10 = 28.0)
        bot_st = await bot_status_store.get(str(event.self_id))
        assert bot_st is not None
        assert bot_st["energy"] == 28.0
        assert bot_st["current_state"] == "power_saving"
        assert bot_st["empathy_mood"] == "深邃沉静"


@pytest.mark.asyncio
async def test_life_engine_edge_cases():
    """验证极端输入、非标准字符串、边界值截断与时间回退等容错鲁棒性。"""
    bot_id = "test_bot_edge"

    # 1. 初始不存在时直接调用 apply_interaction_cost
    st1 = await life_engine.apply_interaction_cost(bot_id, energy_cost="  -15.5  ", dopamine_delta=" +20.0 ")
    assert st1["energy"] == 84.5
    assert st1["dopamine"] == 70.0
    assert st1["current_state"] == "active"

    # 2. 负数流逝时间（时钟回退）不能引起异常或倒扣精力
    t_now = datetime.datetime(2026, 10, 21, 14, 0, 0)
    st2 = await life_engine.tick(bot_id, current_time=t_now, now_ts=t_now.timestamp() - 3600.0)
    assert st2["energy"] >= 0.0

    # 3. 极值截断边界校验：精力不能超 100 也不能跌破 0，多巴胺同样被夹持在 [0, 100]
    st3 = await life_engine.apply_interaction_cost(bot_id, energy_cost=9999.0, dopamine_delta=-9999.0)
    assert st3["energy"] == 0.0
    assert st3["dopamine"] == 0.0
    assert st3["current_state"] == "power_saving"

    st4 = await life_engine.apply_interaction_cost(bot_id, energy_cost=-10.0, dopamine_delta=9999.0)
    # energy_cost 不管传正负，都作为消耗 abs() 处理，不会反向增加
    assert st4["energy"] == 0.0
    assert st4["dopamine"] == 100.0

    # 4. 阈值精确边界：40.0 为 active，39.999 为 power_saving
    assert life_engine.determine_state(40.0, is_sleeping=False) == "active"
    assert life_engine.determine_state(39.999, is_sleeping=False) == "power_saving"
    assert life_engine.determine_state(0.0, is_sleeping=False) == "power_saving"
    assert life_engine.determine_state(100.0, is_sleeping=True) == "sleeping"


@pytest.mark.asyncio
async def test_time_driven_cross_day_night_simulation():
    """验证跨越昼夜分界（白天 -> 夜晚 -> 晨起）的连续时间驱动回血与代谢演进。"""
    bot_id = "test_bot_cross"
    # 从 22:00（白天清醒时段）开始，精力 20.0，孤独感 50.0，多巴胺 70.0
    t0 = datetime.datetime(2026, 10, 20, 22, 0, 0)
    ts0 = t0.timestamp()

    await bot_status_store.upsert(
        bot_id=bot_id,
        energy=20.0,
        mood="疲惫",
        current_state="power_saving",
        loneliness=50.0,
        dopamine=70.0,
        last_updated=ts0,
    )

    # 跃迁到次日 08:00（共 10 小时：22:00-23:00 白天 1 小时，23:00-07:00 睡眠 8 小时，07:00-08:00 白天 1 小时）
    t1 = datetime.datetime(2026, 10, 21, 8, 0, 0)
    ts1 = t1.timestamp()
    st1 = await life_engine.tick(bot_id, current_time=t1, now_ts=ts1)

    # 验证能量回血：20 + 8 * 15 (睡眠) + 2 * 3 (白天) = 146 -> 封顶 100.0
    assert st1["energy"] == 100.0
    assert st1["current_state"] == "active"
    assert st1["current_activity"] != "睡眠休眠中"
    # 孤独感：50 - 8*2.0 (睡眠平复) + 2*2.5 (白天滋长) = 50 - 16 + 5 = 39.0
    assert st1["loneliness"] == 39.0
    # 多巴胺归位：原 70.0 高于基线 50.0，平复 8*4.0 + 2*1.0 = 34.0 -> 回归基线 50.0
    assert st1["dopamine"] == 50.0
    # 验证数据库中的 last_updated 确实记录为 ts1
    db_st = await bot_status_store.get(bot_id)
    assert db_st is not None
    assert db_st["last_updated"] == ts1


@pytest.mark.asyncio
async def test_ensure_tick_mechanism():
    """验证 ensure_tick 自动补全静默漂移并防止重复频繁计算。"""
    bot_id = "test_bot_ensure"
    t0 = datetime.datetime(2026, 10, 21, 10, 0, 0)
    ts0 = t0.timestamp()

    await bot_status_store.upsert(
        bot_id=bot_id,
        energy=50.0,
        current_state="active",
        last_updated=ts0,
    )

    # 1. 漂移仅 20 秒 (<60s)，不触发 tick 推进
    t1 = datetime.datetime(2026, 10, 21, 10, 0, 20)
    ts1 = t1.timestamp()
    st1 = await life_engine.ensure_tick(bot_id, current_time=t1, now_ts=ts1)
    assert st1["energy"] == 50.0

    # 2. 漂移超过 3600 秒 (1小时白天休息)，自动补全 tick 并流转离线活动
    t2 = datetime.datetime(2026, 10, 21, 11, 0, 0)
    ts2 = t2.timestamp()
    st2 = await life_engine.ensure_tick(bot_id, current_time=t2, now_ts=ts2)
    # 基础恢复 3.0 加离线活动 delta (-3~+4)，总精力处于 50.0~57.0 之间
    assert 50.0 <= st2["energy"] <= 57.0
    assert st2["last_updated"] == ts2
    assert st2["current_activity"] != ""


@pytest.mark.asyncio
async def test_writer_energy_cost_fallback_and_sleeping_reply():
    """验证 Writer 模型回复缺失 energy_cost 时自动托底扣减，以及夜间休眠被唤醒状态下限制 1 条回复。"""
    plugin = QJinEraPlugin()
    event = AsyncMock(spec=GroupMessageEvent)
    event.group_id = 99881
    event.user_id = 11223
    event.message = "[CQ:at,qq=1106447644] 醒醒，半夜有急事找你"
    event.self_id = 1106447644
    event.reply = AsyncMock()

    # 初始处于夜间休眠状态 (晚上 23:30)
    t_night = datetime.datetime(2026, 10, 20, 23, 30, 0)
    await bot_status_store.upsert(
        bot_id=str(event.self_id),
        energy=70.0,
        mood="宁静",
        current_state="sleeping",
        loneliness=10.0,
        dopamine=50.0,
        last_updated=time.time(),
    )

    # Writer 返回多条消息，但 LLM 遗漏了 energy_cost
    writer_result = {
        "messages": ["唔...这么晚了，怎么啦？", "我正睡得香呢..."],
        "summary": "深夜被唤醒简短沟通",
    }

    with patch("services.llm.generate_chat", new_callable=AsyncMock, return_value=writer_result), \
         patch("services.topic.topic_manager.is_group_allowed", return_value=True), \
         patch("services.life_engine.is_sleep_time", return_value=True):

        context = await topic_manager.handle_message(
            str(event.group_id), str(event.user_id), event.message, "NightOwl", str(event.self_id)
        )
        context["is_at_mentioned"] = True

        await plugin._respond(context, event)

        # 1. 验证夜间休眠被唤醒防护：回复消息被截断保护为仅 1 条
        event.reply.assert_called_once_with("唔...这么晚了，怎么啦？")

        # 2. 验证缺失能耗时自动托底扣除 2.0，且交互降低孤独感 (-2.0)
        bot_st = await bot_status_store.get(str(event.self_id))
        assert bot_st is not None
        assert bot_st["energy"] == 68.0
        assert bot_st["loneliness"] == 8.0
        # 依然保持 sleeping
        assert bot_st["current_state"] == "sleeping"


@pytest.mark.asyncio
async def test_apply_interaction_cost_wakes_up_in_morning_vs_stays_asleep_at_night():
    """验证休眠中的 Bot 在白天发生交互时自然苏醒，在深夜交互后保持休眠。"""
    bot_id = "test_bot_wake_schedule"

    # 1. 深夜 02:30 被交互唤醒，交互完毕后依然属于夜间休眠期
    t_night = datetime.datetime(2026, 10, 21, 2, 30, 0)
    await bot_status_store.upsert(
        bot_id=bot_id,
        energy=80.0,
        current_state="sleeping",
        last_updated=t_night.timestamp(),
    )
    st_night = await life_engine.apply_interaction_cost(
        bot_id, energy_cost=5.0, current_time=t_night
    )
    assert st_night["energy"] == 75.0
    assert st_night["current_state"] == "sleeping"

    # 2. 早晨 08:30 发生交互，Bot 自然苏醒并切入 active 状态
    t_morning = datetime.datetime(2026, 10, 21, 8, 30, 0)
    st_morning = await life_engine.apply_interaction_cost(
        bot_id, energy_cost=5.0, current_time=t_morning
    )
    assert st_morning["energy"] == 70.0
    assert st_morning["current_state"] == "active"


@pytest.mark.asyncio
async def test_scheduler_proactive_critically_low_energy():
    """验证调度器在精力极度匮乏 (<15) 时跳过主动冷场聊天，保护 Bot 蓄能。"""
    mock_bot = MagicMock()
    mock_bot.adapters = []
    gid = "990099"
    now = time.time()
    topic_manager.group_last_activity[gid] = now - 99999.0  # 远超冷场间隔

    # 设定极低精力 10.0
    await bot_status_store.upsert(
        bot_id=str(config.bot.admin_qq),
        energy=10.0,
        current_state="power_saving",
    )

    with patch("services.llm.generate_proactive_topic", new_callable=AsyncMock) as mock_gen, \
         patch("services.topic.topic_manager.is_group_allowed", return_value=True), \
         patch("asyncio.sleep", new_callable=AsyncMock, side_effect=[None, asyncio.CancelledError()]):
        try:
            await _loop(mock_bot)
        except asyncio.CancelledError:
            pass

        # 验证因为精力 < 15.0，主动话题生成被阻断
        mock_gen.assert_not_called()


@pytest.mark.asyncio
async def test_life_engine_corrupted_and_null_status():
    """验证当数据库中字段为 NULL、非法类型或损坏时的容错恢复。"""
    bot_id = "test_bot_null_corrupt"

    # 1. is_low_energy 容错
    assert life_engine.is_low_energy({"energy": None, "current_state": "active"}) is False
    assert life_engine.is_low_energy({"energy": "invalid", "current_state": "active"}) is False
    assert life_engine.is_low_energy({"energy": None, "current_state": "power_saving"}) is True
    assert life_engine.is_low_energy({}) is False

    # 2. 数据库插入包含 NULL 值的脏数据 (除 last_updated NOT NULL 约束外)
    async with database.get_db() as db:
        await db.execute(
            """
            INSERT INTO bot_status (
                bot_id, energy, mood, current_state, loneliness, dopamine,
                current_activity, focus_user, cur_objective, empathy_mood,
                active_concerns, last_updated
            )
            VALUES (?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1000.0)
            """,
            (bot_id,),
        )

    # 3. get() 安全规整化
    st_get = await bot_status_store.get(bot_id)
    assert st_get is not None
    assert st_get["energy"] == 100.0
    assert st_get["mood"] == "平静"
    assert st_get["current_state"] == "active"
    assert st_get["loneliness"] == 0.0
    assert st_get["dopamine"] == 50.0
    assert st_get["active_concerns"] == []

    # 4. apply_interaction_cost 正常运行不报 TypeError
    st_cost = await life_engine.apply_interaction_cost(bot_id, energy_cost=10.0)
    assert st_cost["energy"] == 90.0

    # 5. tick 正常推进不报异常（考虑随机离线活动可能附带微量消耗，90.0 - 3.0 = 87.0）
    st_tick = await life_engine.tick(bot_id)
    assert st_tick["energy"] >= 85.0


def test_calculate_sleep_and_awake_hours_edge_cases():
    """验证时间差计算对负数时间戳（Windows OSError 规避）、颠倒时间与跨月大跨度的健壮性。"""
    # 1. 负数或零时间戳（在 Windows 平台若直接 fromtimestamp 会引发 OSError）
    s_zero, a_zero = life_engine.calculate_sleep_and_awake_hours(-500.0, 100.0)
    assert s_zero == 0.0
    assert a_zero == 0.0

    # 2. 结束时间小于起始时间
    s_rev, a_rev = life_engine.calculate_sleep_and_awake_hours(1700001000.0, 1700000000.0)
    assert s_rev == 0.0
    assert a_rev == 0.0

    # 3. 非法参数类型
    s_err, a_err = life_engine.calculate_sleep_and_awake_hours(None, "invalid")
    assert s_err == 0.0
    assert a_err == 0.0

    # 4. 连续 30 天的大跨度时间流逝计算 (30 * 24 = 720h, 其中夜间 30 * 8 = 240h, 白天 30 * 16 = 480h)
    t_start = datetime.datetime(2026, 10, 1, 0, 0, 0).timestamp()
    t_end = datetime.datetime(2026, 10, 31, 0, 0, 0).timestamp()
    s_30d, a_30d = life_engine.calculate_sleep_and_awake_hours(t_start, t_end)
    assert s_30d == 240.0
    assert a_30d == 480.0


@pytest.mark.asyncio
async def test_ensure_tick_boundary_transition():
    """验证状态机在跨越昼夜临界点时正确流转昼夜状态与离线活动。"""
    bot_id = "test_bot_boundary"

    # 1. 跨入夜间临界点：22:50:00 (active) -> 23:05:00 (sleeping)
    t_pre_night = datetime.datetime(2026, 10, 20, 22, 50, 0)
    await bot_status_store.upsert(
        bot_id=bot_id,
        energy=80.0,
        current_state="active",
        last_updated=t_pre_night.timestamp(),
    )

    t_post_night = datetime.datetime(2026, 10, 20, 23, 5, 0)
    st_night = await life_engine.ensure_tick(bot_id, current_time=t_post_night, now_ts=t_post_night.timestamp())
    assert st_night["current_state"] == "sleeping"
    assert st_night["current_activity"] == "睡眠休眠中"

    # 2. 跨入清晨苏醒临界点：06:50:00 (sleeping) -> 07:05:00 (active)
    t_pre_morning = datetime.datetime(2026, 10, 21, 6, 50, 0)
    await bot_status_store.update_state(
        bot_id,
        current_state="sleeping",
        current_activity="睡眠休眠中",
        last_updated=t_pre_morning.timestamp(),
    )

    t_post_morning = datetime.datetime(2026, 10, 21, 7, 5, 0)
    st_morning = await life_engine.ensure_tick(bot_id, current_time=t_post_morning, now_ts=t_post_morning.timestamp())
    assert st_morning["current_state"] == "active"
    assert st_morning["current_activity"] != "睡眠休眠中"


def test_templates_with_none_energy_robustness():
    """验证当 bot_status 中 energy 为 None 或非浮点类型时，Jinja 模板渲染依然保持坚挺不抛出 TypeError。"""
    status_with_none = {"energy": None, "current_state": "power_saving", "mood": "疲惫"}

    # 1. judge_template
    r_judge = judge_template.render(
        persona=_persona_data,
        bot_id="1106447644",
        bot_status=status_with_none,
    )
    assert "当前精力值 (Energy)：100/100。" in r_judge
    assert "【低电量省电模式 (Power-Saving)】" in r_judge

    # 2. chat_template
    r_chat = chat_template.render(
        persona=_persona_data,
        bot_status=status_with_none,
    )
    assert "你当前的体力值 (Energy)：100/100。" in r_chat
    assert "【当前运行状态：低电量省电模式 (Power-Saving Mode)】" in r_chat

    # 3. proactive_template
    r_proactive = proactive_template.render(
        persona=_persona_data,
        bot_status=status_with_none,
    )
    assert "当前精力：100/100" in r_proactive
    assert "处于省电模式" in r_proactive


@pytest.mark.asyncio
async def test_scheduler_proactive_night_suppression_when_tick_fails():
    """验证调度器在夜间 (23:00 - 07:00) 即使 tick 失败抛异常且 bot_st 为 None 时，也绝不在深夜冷场发起主动话题。"""
    mock_bot = MagicMock()
    mock_bot.adapters = []
    gid = "778899"
    # 模拟深夜 03:00
    t_night = datetime.datetime(2026, 10, 21, 3, 0, 0)
    ts_night = t_night.timestamp()
    topic_manager.group_last_activity[gid] = ts_night - 99999.0

    with patch("time.time", return_value=ts_night), \
         patch("services.life_engine.tick", side_effect=RuntimeError("Tick DB lock error")), \
         patch("services.llm.generate_proactive_topic", new_callable=AsyncMock) as mock_gen, \
         patch("services.topic.topic_manager.is_group_allowed", return_value=True), \
         patch("asyncio.sleep", new_callable=AsyncMock, side_effect=[None, asyncio.CancelledError()]):
        try:
            await _loop(mock_bot)
        except asyncio.CancelledError:
            pass

        # 验证深夜休眠时段，主动冷场话题被坚决阻断
        mock_gen.assert_not_called()



