"""
针对本次 /boost 改 的全面验证测试：
涵盖四大问题（自指与人格解离、实体映射与反公文腔、群分层与隐私隔离、世界观管理与记忆遗忘）。
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from services.identity import (
    BOT_ALIASES,
    CORE_IDENTITIES,
    build_identity_map,
    is_bot_self,
    is_bot_self_memory,
    resolve_subject_id,
    sanitize_memory_content,
)
from services.llm import _persona_data, chat_template, memory_consolidator_template, memory_extractor_template
from services.storage import database, groups as group_store, memories, world_lore


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_boost.db"
    monkeypatch.setattr(database, "_DB_PATH", str(test_db))
    monkeypatch.setattr(
        "services.identity.get_configured_identities",
        lambda persona=None: {"10001": "UserAlpha", "10002": "UserBeta / UserBetaAlias"},
    )
    monkeypatch.setattr("services.identity.KNOWN_BOT_IDS", {"99999"})
    await database.init_db()
    yield test_db


# ==============================================================================
# 问题一：自指认知与人格解离
# ==============================================================================

def test_is_bot_self_detection():
    """验证机器人全量别名自指识别。"""
    # 核心别名
    assert is_bot_self("柒槿年") is True
    assert is_bot_self("年年") is True
    assert is_bot_self("年年宝") is True
    assert is_bot_self("QJinEra") is True
    assert is_bot_self("qjinera") is True
    assert is_bot_self("机器人") is True
    assert is_bot_self("生命引擎") is True
    assert is_bot_self("赛博哨兵") is True

    # 变体前缀/后缀与符号括号变体
    assert is_bot_self("机器人柒槿年") is True
    assert is_bot_self("小年年") is True
    assert is_bot_self("年年系统") is True
    assert is_bot_self("Bot年年") is True
    assert is_bot_self("年年 (Bot)") is True
    assert is_bot_self("年年(bot)") is True
    assert is_bot_self("年年（机器人）") is True
    assert is_bot_self("年年_bot") is True
    assert is_bot_self("柒槿年bot") is True
    assert is_bot_self("QJinEra 机器人") is True

    # QQ号匹配
    assert is_bot_self("99999", bot_id="99999") is True

    # 非机器人实体（绝不误伤）
    assert is_bot_self("奶黄包") is False
    assert is_bot_self("奶黄包 (猫)") is False
    assert is_bot_self("UserAlpha") is False
    assert is_bot_self("UserBeta") is False
    assert is_bot_self("UserBetaAlias") is False
    assert is_bot_self("深渊潜水协议") is False
    assert is_bot_self("蓝莓千层") is False
    assert is_bot_self("10001") is False


def test_is_bot_self_memory():
    """验证记忆陈述句级别的 Bot 自指判定。"""
    # 第三人称描述 Bot 的句子（必须拦截）
    assert is_bot_self_memory("年年是一个需要优化的系统") is True
    assert is_bot_self_memory("年年确实是一个需要优化的系统") is True
    assert is_bot_self_memory("柒槿年具备跨天日志机制") is True
    assert is_bot_self_memory("年年计划下个版本加新功能") is True
    assert is_bot_self_memory("机器人目前处于调试状态") is True
    assert is_bot_self_memory("QJinEra 拥有生命引擎") is True
    assert is_bot_self_memory("小年年很可爱") is True
    assert is_bot_self_memory("年年很可爱") is True
    assert is_bot_self_memory("年年") is True

    # 以人类用户为主语的正常事实（绝不误伤）
    assert is_bot_self_memory("UserAlpha 喜欢吃羊肉泡馍") is False
    assert is_bot_self_memory("UserBeta 正在为年年写新功能") is False
    assert is_bot_self_memory("正在进行年年提示词的调整工作") is False
    assert is_bot_self_memory("能够赋予年年感知时间和世界的能力") is False
    assert is_bot_self_memory("对年年端水的行为感到不满") is False
    assert is_bot_self_memory("奶黄包是一只橘猫") is False


@pytest.mark.asyncio
async def test_world_lore_and_memories_bot_guard():
    """验证后端入库前守卫：禁止将机器人自身存入 World Lore 或 Memories。"""
    gid = "test_group"

    # 1. World Lore 守卫拦截
    res1 = await world_lore.add_or_update(gid, "u1", "年年", "一个具备跨天日志机制的系统")
    assert res1 is False
    lores = await world_lore.get_all(gid)
    assert len(lores) == 0

    res2 = await world_lore.add_or_update(gid, "u1", "生命引擎", "消耗体力机制")
    assert res2 is False

    res_lore_bracket = await world_lore.add_or_update(gid, "u1", "年年 (Bot)", "群助手")
    assert res_lore_bracket is False

    # 正常实体允许入库
    res3 = await world_lore.add_or_update(gid, "u1", "奶黄包", "一只可爱的橘猫")
    assert res3 is True
    lores = await world_lore.get_all(gid)
    assert len(lores) == 1
    assert lores[0]["entity_name"] == "奶黄包"

    # 2. Memories 守卫拦截
    res_mem1 = await memories.add("99999", gid, {"subject_id": "99999", "content": "计划下个版本增加图片识别"})
    assert res_mem1 is False
    res_mem2 = await memories.add("u1", gid, {"subject_id": "年年", "content": "年年很可爱"})
    assert res_mem2 is False

    # 关键测试：即使 subject_id 填了人类用户，但 content 是第三人称描述 Bot 的自指，必须拦截！
    res_mem_dissoc = await memories.add("10001", gid, {"subject_id": "10001", "content": "年年是一个需要优化的系统"})
    assert res_mem_dissoc is False

    res_mem_dissoc2 = await memories.add("10001", gid, {"subject_id": "10001", "content": "柒槿年具备跨天日志机制"})
    assert res_mem_dissoc2 is False

    # 正常人类记忆允许入库
    res_mem3 = await memories.add("10001", gid, {"subject_id": "10001", "content": "UserAlpha 喜欢吃羊肉泡馍"})
    assert res_mem3 is True
    mems = await memories.get_for_context("10001")
    assert len(mems) == 1
    assert "羊肉泡馍" in mems[0]


def test_chat_system_self_reference_anchor():
    """验证 chat_system.jinja 渲染第一人称绝对自指锚定与防解离指令。"""
    rendered = chat_template.render(
        persona=_persona_data,
        bot_status={"energy": 100.0, "mood": "平静"},
    )
    assert "【🔴 第一人称绝对自指锚定 (Self-Reference & Identity Anchor)】" in rendered
    assert "100% 绝对等价于第一人称“我”" in rendered
    assert "杜绝第三人称解离" in rendered
    assert "绝对禁止以第三人称旁观者视角接话" in rendered


# ==============================================================================
# 问题二：长期记忆中的主体指代与反机械公文腔
# ==============================================================================

def test_identity_resolution_mapping():
    """验证实体解析映射：核心 QQ 号与真实昵称对应关系。"""
    id_map = build_identity_map([("578260535", "shmily"), ("10001", "ignored")])
    # 核心映射优先级高
    assert id_map["10001"] == "UserAlpha"
    assert "UserBeta" in id_map["10002"]
    assert id_map["578260535"] == "shmily"


def test_resolve_subject_id_and_sanitization():
    """验证主客体实体反向解析及非人化代词净化。"""
    # 核心映射与别名反向解析
    assert resolve_subject_id("10001") == "10001"
    assert resolve_subject_id("UserAlpha") == "10001"
    assert resolve_subject_id("UserBeta") == "10002"
    assert resolve_subject_id("UserBetaAlias") == "10002"
    assert resolve_subject_id("shmily", identity_map={"578260535": "shmily"}) == "578260535"
    assert resolve_subject_id("未知路人", fallback_id="10001") == "10001"

    # 净化内容（替换"该用户"、"该个体"、数字 QQ 等）
    s1 = sanitize_memory_content("该用户喜欢吃羊肉泡馍", "UserAlpha")
    assert "UserAlpha" in s1 and "该用户" not in s1

    s2 = sanitize_memory_content("与10001处于亲密关系中")
    assert "UserAlpha" in s2 and "10001" not in s2

    s3 = sanitize_memory_content("与UserBeta（用户）有互动")
    assert s3 == "与UserBeta有互动"


def test_memory_extractor_and_consolidator_templates():
    """验证提取器与巩固器模板包含身份映射、反公文腔红线及提炼去冗协议。"""
    id_map = {"10001": "UserAlpha", "10002": "UserBeta"}

    # 提取器
    ext_rendered = memory_extractor_template.render(
        persona=_persona_data,
        bot_id="99999",
        identity_map=id_map,
    )
    assert "【已知人物身份映射 (Identity Resolution)】" in ext_rendered
    assert "QQ 10001 对应真实姓名/常用称呼：UserAlpha" in ext_rendered
    assert "绝对禁止提取机器人自身为 World Lore" in ext_rendered
    assert "严禁使用非人化代词" in ext_rendered
    assert "绝对严禁" in ext_rendered and "该用户" in ext_rendered and "个体" in ext_rendered

    # 巩固器
    cons_rendered = memory_consolidator_template.render(
        persona=_persona_data,
        bot_id="99999",
        user_name="UserAlpha",
        identity_map=id_map,
    )
    assert "当前整理画像所属人物：UserAlpha" in cons_rendered
    assert "核心风格要求：温暖具名，拒绝冷血公文腔" in cons_rendered
    assert "画像更新与精炼去冗协议 (Refinement & Pruning)" in cons_rendered
    assert "提炼去冗，拒绝无脑累加" in cons_rendered


# ==============================================================================
# 问题三：群分层架构与私密小群隐私隔离
# ==============================================================================

@pytest.mark.asyncio
async def test_memory_group_privacy_scoping():
    """
    验证私密小群深层记忆与普通公开群的作用域隔离：
    在 soulmate / private 群创建的专属记忆，在 public 群中绝不召回！
    """
    soulmate_gid = "88801"
    public_gid = "88802"
    user_id = "10001"

    # 初始化群组亲密度
    await group_store.upsert(soulmate_gid, "私密圣所")
    await group_store.update_overlay(soulmate_gid, "专属行为覆层", intimacy_level="soulmate")

    await group_store.upsert(public_gid, "公开测试群")
    await group_store.update_overlay(public_gid, "普通覆层", intimacy_level="public")

    # 在私密群插入深层记忆
    await memories.add(user_id, soulmate_gid, {
        "subject_id": user_id,
        "content": "与UserBeta许下了重要的约定",
    })

    # 在公开群插入通用记忆
    await memories.add(user_id, public_gid, {
        "subject_id": user_id,
        "content": "喜欢吃羊肉泡馍",
    })

    # 1. 在公开群查询该用户的记忆：只能看到公开群的记忆，绝不能召回私密群的深层记忆！
    public_recalled = await memories.get_for_context(user_id, group_id=public_gid)
    assert len(public_recalled) == 1
    assert "羊肉泡馍" in public_recalled[0]
    assert "UserBeta" not in public_recalled[0]

    # 2. 在私密圣所群查询该用户的记忆：可以召回本群的私密专属记忆
    soulmate_recalled = await memories.get_for_context(user_id, group_id=soulmate_gid)
    contents_text = " ".join(soulmate_recalled)
    assert "UserBeta许下了重要的约定" in contents_text
    assert "羊肉泡馍" in contents_text


@pytest.mark.asyncio
async def test_world_lore_scope():
    """验证 World Lore 全局 scope 与群私有 scope 的检索隔离。"""
    gid1 = "group_1"
    gid2 = "group_2"

    # group_1 私有设定
    await world_lore.add_or_update(gid1, "u1", "本群特供梗", "群1专属", scope="group")
    # 全局设定
    await world_lore.add_or_update(gid1, "u1", "通用常识", "全局通用设定", scope="global")

    # group_1 能查到两者
    lores1 = await world_lore.get_all(gid1)
    names1 = {l["entity_name"] for l in lores1}
    assert "本群特供梗" in names1
    assert "通用常识" in names1

    # group_2 只能查到全局设定，查不到 group_1 的私有设定
    lores2 = await world_lore.get_all(gid2)
    names2 = {l["entity_name"] for l in lores2}
    assert "本群特供梗" not in names2
    assert "通用常识" in names2

    # 通过实体名检索也符合隔离
    res2 = await world_lore.get_by_entities(gid2, ["本群特供梗", "通用常识"])
    matched2 = {r["entity_name"] for r in res2["exact"]}
    assert "本群特供梗" not in matched2
    assert "通用常识" in matched2


# ==============================================================================
# 问题四：长期记忆纠错与遗忘机制
# ==============================================================================

@pytest.mark.asyncio
async def test_world_lore_delete_and_forget_keywords():
    """验证 /lore del 与 /forget 的持久化效果。"""
    gid = "group_ops"
    uid = "10001"

    # 1. World lore 删除
    await world_lore.add_or_update(gid, uid, "临时设定", "测试删除")
    assert len(await world_lore.get_all(gid)) == 1

    del_res = await world_lore.delete(gid, "临时设定")
    assert del_res is True
    assert len(await world_lore.get_all(gid)) == 0

    del_res2 = await world_lore.delete(gid, "不存在的设定")
    assert del_res2 is False

    # 2. Memories 关键词遗忘
    await memories.add(uid, gid, {"subject_id": uid, "content": "讨厌吃香菜"})
    await memories.add(uid, gid, {"subject_id": uid, "content": "非常讨厌吃香菜而且闻到就想吐"})
    await memories.add(uid, gid, {"subject_id": uid, "content": "喜欢吃羊肉泡馍"})

    active_mems = await memories.get_for_context(uid, group_id=gid)
    assert len(active_mems) == 3

    # 执行遗忘香菜
    forgotten_count = await memories.forget_by_keyword(gid, "香菜")
    assert forgotten_count == 2

    # 再次查询活跃记忆：香菜记忆已归档，只剩羊肉泡馍
    active_mems_after = await memories.get_for_context(uid, group_id=gid)
    assert len(active_mems_after) == 1
    assert "羊肉泡馍" in active_mems_after[0]


@pytest.mark.asyncio
async def test_world_lore_delete_global_fallback():
    """验证从任意群均可成功删除全局 World Lore 设定。"""
    gid_creator = "group_100"
    gid_other = "group_200"

    # 在 group_100 创建全局设定
    await world_lore.add_or_update(gid_creator, "u1", "跨群世界观", "全服可见设定", scope="global")
    assert len(await world_lore.get_all(gid_other)) == 1

    # 在 group_200 执行删除：能命中全局设定并成功删除
    del_res = await world_lore.delete(gid_other, "跨群世界观")
    assert del_res is True
    assert len(await world_lore.get_all(gid_other)) == 0
