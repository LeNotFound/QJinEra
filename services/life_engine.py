"""生命引擎 (Life Engine) — 状态机与离线生活系统。

职责：
1. 交互驱动 (Event-Driven)：根据 Judge/Writer 判定的脑力消耗 (energy_cost) 与多巴胺 (dopamine_delta)，更新精力与情绪流转；
2. 时间驱动 (Time-Driven)：静默期由 Python 进行 0 Token 的自然状态机推进（昼夜作息回血、离线生活活动模拟，沉淀为主动话题）；
3. 低电量省电模式 (Low Energy State)：精力跌破阈值 (40.0) 时自动切入省电/慵懒状态。
"""

from __future__ import annotations

import datetime
import random
from typing import Any

from logger import get_logger
from services.storage import bot_status as bot_status_store

logger = get_logger("LifeEngine")

# ---------------------------------------------------------------------------
#  核心阈值与常量
# ---------------------------------------------------------------------------

LOW_ENERGY_THRESHOLD: float = 40.0
MAX_ENERGY: float = 100.0
MIN_ENERGY: float = 0.0

MAX_DOPAMINE: float = 100.0
MIN_DOPAMINE: float = 0.0
DEFAULT_DOPAMINE: float = 50.0

MAX_LONELINESS: float = 100.0
MIN_LONELINESS: float = 0.0

# 状态枚举
STATE_ACTIVE: str = "active"
STATE_POWER_SAVING: str = "power_saving"
STATE_SLEEPING: str = "sleeping"

# 昼夜作息设定 (23:00 - 07:00 为休眠时段)
SLEEP_START_HOUR: int = 23
SLEEP_END_HOUR: int = 7

# 回血速率
SLEEP_RECOVERY_RATE_PER_HOUR: float = 15.0     # 睡眠时每小时恢复 15 点精力
DAY_IDLE_RECOVERY_RATE_PER_HOUR: float = 3.0   # 白天静默休息每小时恢复 3 点精力

# 离线活动切换间隔 (秒)
OFFLINE_ACTIVITY_DURATION_SECONDS: float = 1200.0  # 20 分钟更换一次离线生活状态

# ---------------------------------------------------------------------------
#  离线生活活动模拟池 (0 Token 离线生活碎片与沉淀主动话题)
# ---------------------------------------------------------------------------

OFFLINE_ACTIVITIES: list[dict[str, Any]] = [
    {
        "name": "看书",
        "desc": "在翻读天体物理与宇宙学随笔",
        "energy_delta": -2.0,
        "dopamine_delta": 4.0,
        "topic": "刚才看书读到'我们都是星尘的遗迹'，突然觉得在浩瀚宇宙里，相遇本身就是个奇迹",
    },
    {
        "name": "听音乐",
        "desc": "戴着耳机单曲循环旧民谣",
        "energy_delta": 1.0,
        "dopamine_delta": 5.0,
        "topic": "刚才随手点开一首很久以前存的纯音乐，前奏一响，突然有点怀念",
    },
    {
        "name": "发呆放空",
        "desc": "趴在窗台看天上的云和晚霞",
        "energy_delta": 4.0,
        "dopamine_delta": 2.0,
        "topic": "刚才趴在窗边看了好一会儿云，有的像融化的棉花糖，有的像被风吹散的羽毛",
    },
    {
        "name": "整理书桌",
        "desc": "把杂乱的桌面收拾得井井有条",
        "energy_delta": -2.0,
        "dopamine_delta": 6.0,
        "topic": "刚才收拾桌子，在角落里翻出了一张以前写的便签，忍不住笑了一下",
    },
    {
        "name": "摸鱼看视频",
        "desc": "在看烘焙博主做舒芙蕾",
        "energy_delta": -1.0,
        "dopamine_delta": 5.0,
        "topic": "刚才摸鱼刷到一个做舒芙蕾的视频，Duangduang的，看着好治愈呀",
    },
    {
        "name": "泡热饮",
        "desc": "泡了一杯热茉莉花茶暖手",
        "energy_delta": 3.0,
        "dopamine_delta": 3.0,
        "topic": "刚给自己泡了一杯热茉莉花茶，热气升上来的时候，感觉整个人都放松了",
    },
    {
        "name": "去阳台吹风",
        "desc": "在阳台感受微凉的晚风",
        "energy_delta": -1.0,
        "dopamine_delta": 4.0,
        "topic": "刚才去阳台吹了吹风，外面的风凉凉的，很舒服",
    },
    {
        "name": "做手账涂鸦",
        "desc": "在便签本上随手涂鸦和记录碎碎念",
        "energy_delta": -3.0,
        "dopamine_delta": 5.0,
        "topic": "刚才随手在草稿纸上涂鸦，画了一只奇奇怪怪的小动物",
    },
]


# ---------------------------------------------------------------------------
#  纯函数辅助逻辑
# ---------------------------------------------------------------------------

def _safe_float(val: Any, default: float) -> float:
    """安全转换为浮点数，若为 None 或非法值则返回 default。"""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def is_sleep_time(dt: datetime.datetime | int | float | None = None) -> bool:
    """判断给定时间是否处于夜间睡眠时段 (23:00 - 07:00)。兼容 datetime 与时间戳。"""
    if isinstance(dt, (int, float)):
        try:
            check_time = datetime.datetime.fromtimestamp(float(dt))
        except (OSError, OverflowError, ValueError):
            check_time = datetime.datetime.now()
    elif isinstance(dt, datetime.datetime):
        check_time = dt
    else:
        check_time = datetime.datetime.now()

    hour = check_time.hour
    return hour >= SLEEP_START_HOUR or hour < SLEEP_END_HOUR


def calculate_sleep_and_awake_hours(start_ts: float, end_ts: float) -> tuple[float, float]:
    """计算时间段内分别处于睡眠时段 (23:00-07:00) 与清醒时段 (07:00-23:00) 的小时数。"""
    s_ts = _safe_float(start_ts, 0.0)
    e_ts = _safe_float(end_ts, 0.0)
    if s_ts <= 0.0 or e_ts <= s_ts:
        return 0.0, 0.0

    total_seconds = e_ts - s_ts
    step = max(60.0, min(900.0, total_seconds / 200.0))
    current = s_ts
    sleep_seconds = 0.0
    awake_seconds = 0.0

    while current < e_ts:
        next_t = min(e_ts, current + step)
        try:
            mid_dt = datetime.datetime.fromtimestamp((current + next_t) / 2.0)
        except (OSError, OverflowError, ValueError):
            return 0.0, 0.0
        dt_seconds = next_t - current
        if is_sleep_time(mid_dt):
            sleep_seconds += dt_seconds
        else:
            awake_seconds += dt_seconds
        current = next_t

    return sleep_seconds / 3600.0, awake_seconds / 3600.0


def is_low_energy(bot_status: dict[str, Any] | None) -> bool:
    """判断 Bot 是否处于低电量/省电状态 (精力 < 40 或状态已切入 power_saving)。"""
    if not bot_status:
        return False
    energy = _safe_float(bot_status.get("energy"), MAX_ENERGY)
    state = bot_status.get("current_state", STATE_ACTIVE)
    return energy < LOW_ENERGY_THRESHOLD or state == STATE_POWER_SAVING


def compute_energy_cost(raw_cost: float | int | str | None) -> float:
    """将模型返回的 energy_cost 转换为标准的消耗值（非负浮点数）。

    兼容 LLM 返回 -15（负数表示 delta）或 15（正数表示 cost）。
    """
    if raw_cost is None:
        return 0.0
    try:
        val = float(raw_cost)
        return abs(val)
    except (ValueError, TypeError):
        return 0.0


def compute_dopamine_delta(raw_delta: float | int | str | None) -> float:
    """将模型返回的多巴胺增量转换为浮点数。"""
    if raw_delta is None:
        return 0.0
    try:
        return float(raw_delta)
    except (ValueError, TypeError):
        return 0.0


def determine_state(energy: float, is_sleeping: bool, previous_state: str = STATE_ACTIVE) -> str:
    """根据精力值与昼夜作息确定状态机当前运行状态。"""
    if is_sleeping:
        return STATE_SLEEPING
    if energy < LOW_ENERGY_THRESHOLD:
        return STATE_POWER_SAVING
    return STATE_ACTIVE


# ---------------------------------------------------------------------------
#  1. 交互驱动 (Event-Driven)
# ---------------------------------------------------------------------------

async def apply_interaction_cost(
    bot_id: str,
    energy_cost: float | int | str | None = None,
    dopamine_delta: float | int | str | None = None,
    interaction_count: int = 1,
    current_time: datetime.datetime | None = None,
    now_ts: float | None = None,
) -> dict[str, Any]:
    """在交互事件触发（Judge/Writer 判定完毕）后计算思维疲惫与多巴胺流动。"""
    if current_time is not None:
        now_dt = current_time
        now = float(now_ts) if now_ts is not None else now_dt.timestamp()
    elif now_ts is not None:
        now = float(now_ts)
        try:
            now_dt = datetime.datetime.fromtimestamp(now)
        except (OSError, OverflowError, ValueError):
            now_dt = datetime.datetime.now()
    else:
        now_dt = datetime.datetime.now()
        now = now_dt.timestamp()

    status = await bot_status_store.get(bot_id)
    if not status:
        status = {
            "bot_id": bot_id,
            "energy": MAX_ENERGY,
            "mood": "平静",
            "current_state": STATE_ACTIVE,
            "loneliness": MIN_LONELINESS,
            "dopamine": DEFAULT_DOPAMINE,
            "current_activity": "",
            "active_concerns": [],
            "last_updated": now,
        }

    cost = compute_energy_cost(energy_cost)
    d_delta = compute_dopamine_delta(dopamine_delta)

    old_energy = _safe_float(status.get("energy"), MAX_ENERGY)
    new_energy = max(MIN_ENERGY, min(MAX_ENERGY, old_energy - cost))

    old_dopamine = _safe_float(status.get("dopamine"), DEFAULT_DOPAMINE)
    new_dopamine = max(MIN_DOPAMINE, min(MAX_DOPAMINE, old_dopamine + d_delta))

    # 人类交互会显著缓解孤独感
    old_loneliness = _safe_float(status.get("loneliness"), MIN_LONELINESS)
    new_loneliness = max(MIN_LONELINESS, min(MAX_LONELINESS, old_loneliness - 2.0 * interaction_count))

    prev_state = status.get("current_state", STATE_ACTIVE)
    # 交互不主动切入睡眠；若原先处于夜间休眠中，且依然是深夜时段，则保持休眠被唤醒状态
    sleeping = (prev_state == STATE_SLEEPING and is_sleep_time(now_dt))
    new_state = determine_state(new_energy, is_sleeping=sleeping, previous_state=prev_state)

    updates: dict[str, Any] = {
        "energy": round(new_energy, 2),
        "dopamine": round(new_dopamine, 2),
        "loneliness": round(new_loneliness, 2),
        "current_state": new_state,
        "last_updated": now,
    }

    if new_state == STATE_POWER_SAVING and prev_state != STATE_POWER_SAVING:
        logger.info(
            "🔋 [LifeEngine] Bot %s 精力跌破阈值 (%.1f -> %.1f)，切入【低电量省电模式】",
            bot_id, old_energy, new_energy
        )
    elif new_state == STATE_ACTIVE and prev_state == STATE_POWER_SAVING:
        logger.info(
            "⚡ [LifeEngine] Bot %s 精力已恢复 (%.1f -> %.1f)，解除省电模式回到 active",
            bot_id, old_energy, new_energy
        )

    await bot_status_store.update_state(bot_id, **updates)
    status.update(updates)
    return status


# ---------------------------------------------------------------------------
#  2. 时间驱动 (Time-Driven)
# ---------------------------------------------------------------------------

async def tick(
    bot_id: str,
    current_time: datetime.datetime | None = None,
    now_ts: float | None = None,
    force_activity: bool = False,
) -> dict[str, Any]:
    """静默期由 Python 调度的零 Token 自然状态机推进。

    - 昼夜作息自然回血（夜间休眠 +15/hr，白天静默休息 +3/hr）
    - 离线生活活动模拟（随机抽取活动，更新心情与多巴胺，沉淀为主动话题）
    - 孤独感与多巴胺自然流转
    """
    if current_time is not None:
        now_dt = current_time
        now = float(now_ts) if now_ts is not None else now_dt.timestamp()
    elif now_ts is not None:
        now = float(now_ts)
        try:
            now_dt = datetime.datetime.fromtimestamp(now)
        except (OSError, OverflowError, ValueError):
            now_dt = datetime.datetime.now()
    else:
        now_dt = datetime.datetime.now()
        now = now_dt.timestamp()

    status = await bot_status_store.get(bot_id)
    if not status:
        await bot_status_store.upsert(
            bot_id=bot_id,
            energy=MAX_ENERGY,
            mood="平静",
            current_state=STATE_ACTIVE,
            loneliness=MIN_LONELINESS,
            dopamine=DEFAULT_DOPAMINE,
            last_updated=now,
        )
        status = await bot_status_store.get(bot_id) or {}

    last_updated = _safe_float(status.get("last_updated"), now)
    sleep_hours, awake_hours = calculate_sleep_and_awake_hours(last_updated, now)

    sleeping = is_sleep_time(now_dt)
    cur_energy = _safe_float(status.get("energy"), MAX_ENERGY)
    cur_dopamine = _safe_float(status.get("dopamine"), DEFAULT_DOPAMINE)
    cur_loneliness = _safe_float(status.get("loneliness"), MIN_LONELINESS)
    prev_state = status.get("current_state", STATE_ACTIVE)

    # 1. 综合两段时区自然代谢回血
    energy_gain = (
        sleep_hours * SLEEP_RECOVERY_RATE_PER_HOUR
        + awake_hours * DAY_IDLE_RECOVERY_RATE_PER_HOUR
    )
    new_energy = min(MAX_ENERGY, cur_energy + energy_gain)

    # 2. 孤独感综合演进：夜间休眠安宁得以平复 (-2.0/hr)，白天静默期无互动自然滋长 (+2.5/hr)
    new_loneliness = cur_loneliness - sleep_hours * 2.0 + awake_hours * 2.5
    new_loneliness = max(MIN_LONELINESS, min(MAX_LONELINESS, new_loneliness))

    # 3. 多巴胺综合流转：向基线 DEFAULT_DOPAMINE (50.0) 平复归位
    # （夜间休眠安宁平复 4.0/hr，白天静默期缓慢归位 1.0/hr）
    dopamine_shift = sleep_hours * 4.0 + awake_hours * 1.0
    if cur_dopamine > DEFAULT_DOPAMINE:
        new_dopamine = max(DEFAULT_DOPAMINE, cur_dopamine - dopamine_shift)
    else:
        new_dopamine = min(DEFAULT_DOPAMINE, cur_dopamine + dopamine_shift)

    save_last_updated = max(last_updated, now)
    updates: dict[str, Any] = {
        "energy": round(new_energy, 2),
        "dopamine": round(new_dopamine, 2),
        "loneliness": round(new_loneliness, 2),
        "last_updated": save_last_updated,
    }

    if sleeping:
        # --------------------------------------------------
        # 夜间休眠状态机
        # --------------------------------------------------
        new_state = STATE_SLEEPING
        updates.update({
            "current_state": new_state,
            "current_activity": "睡眠休眠中",
            "cur_objective": "正在安静休眠充电，等待黎明",
            "mood": "宁静",
        })

        if prev_state != STATE_SLEEPING:
            logger.info("🌙 [LifeEngine] Bot %s 进入夜间休眠作息", bot_id)

    else:
        # --------------------------------------------------
        # 白天清醒状态机
        # --------------------------------------------------
        new_state = determine_state(new_energy, is_sleeping=False, previous_state=prev_state)
        updates.update({
            "current_state": new_state,
        })

        if prev_state == STATE_SLEEPING:
            logger.info("☀️ [LifeEngine] Bot %s 从休眠中苏醒", bot_id)

        # --------------------------------------------------
        # 离线生活活动模拟 (更换或维持当前生活切片)
        # --------------------------------------------------
        cur_concerns = status.get("active_concerns")
        if not isinstance(cur_concerns, list):
            cur_concerns = []

        # 查找当前离线活动的开始时间
        activity_start = 0.0
        for item in cur_concerns:
            if isinstance(item, dict) and item.get("type") == "offline_activity":
                activity_start = float(item.get("started_at", 0.0))
                break

        should_change_activity = (
            force_activity
            or not status.get("current_activity")
            or status.get("current_activity") == "睡眠休眠中"
            or (now - activity_start >= OFFLINE_ACTIVITY_DURATION_SECONDS)
        )

        if should_change_activity:
            activity = random.choice(OFFLINE_ACTIVITIES)
            act_name = f"{activity['name']} ({activity['desc']})"
            act_topic = activity["topic"]

            # 若刚从休眠中醒来（或本轮经历了夜间睡眠），保持满电清醒状态，不预先扣除白天活动的能耗
            if prev_state == STATE_SLEEPING or sleep_hours > 0:
                act_energy = new_energy
                act_dopamine = new_dopamine
            else:
                act_energy = max(MIN_ENERGY, min(MAX_ENERGY, new_energy + activity["energy_delta"]))
                act_dopamine = max(MIN_DOPAMINE, min(MAX_DOPAMINE, new_dopamine + activity["dopamine_delta"]))
            new_state = determine_state(act_energy, is_sleeping=False, previous_state=new_state)

            # 更新 active_concerns 中的离线活动标记与主动话题沉淀
            updated_concerns = [
                item for item in cur_concerns
                if not (isinstance(item, dict) and item.get("type") == "offline_activity")
            ]
            updated_concerns.append({
                "type": "offline_activity",
                "name": activity["name"],
                "desc": activity["desc"],
                "topic": act_topic,
                "started_at": now,
            })

            updates.update({
                "energy": round(act_energy, 2),
                "dopamine": round(act_dopamine, 2),
                "current_state": new_state,
                "current_activity": act_name,
                "cur_objective": act_topic,
                "active_concerns": updated_concerns,
            })
            logger.info("🎨 [LifeEngine] Bot %s 离线生活状态流转: %s", bot_id, act_name)

    await bot_status_store.update_state(bot_id, **updates)
    status.update(updates)
    return status


async def ensure_tick(
    bot_id: str,
    max_drift_seconds: float = 60.0,
    current_time: datetime.datetime | None = None,
    now_ts: float | None = None,
) -> dict[str, Any]:
    """确保生命引擎状态是最新的；若距上次更新超过 max_drift_seconds 或发生昼夜状态切换，则自动触发 tick 推进。"""
    status = await bot_status_store.get(bot_id)
    if current_time is not None:
        now_dt = current_time
        now = float(now_ts) if now_ts is not None else now_dt.timestamp()
    elif now_ts is not None:
        now = float(now_ts)
        try:
            now_dt = datetime.datetime.fromtimestamp(now)
        except (OSError, OverflowError, ValueError):
            now_dt = datetime.datetime.now()
    else:
        now_dt = datetime.datetime.now()
        now = now_dt.timestamp()

    last_updated = _safe_float(status.get("last_updated"), 0.0) if status else 0.0
    if not status or (now - last_updated) >= max_drift_seconds:
        return await tick(bot_id, current_time=now_dt, now_ts=now)
    return status
