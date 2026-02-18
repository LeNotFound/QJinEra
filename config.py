"""
QJinEra 配置系统 — 基于 Pydantic 的强类型一次性加载。

Usage:
    from config import config

    print(config.bot.name)       # IDE 自动补全 + 类型校验
    print(config.llm.api_key)    # str, 而不是 Any
"""

from __future__ import annotations

import sys
from pathlib import Path

import tomli
from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
#  子配置模型
# ---------------------------------------------------------------------------

class BotConfig(BaseModel):
    """Bot 基础配置 — 对应 config.toml [bot]。"""
    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str = "柒槿年"
    english_name: str = "QJinEra"
    admin_qq: int = 0
    plugins: list[str] = []
    plugin_dirs: list[str] = []
    adapters: list[str] = []
    allowed_groups: list[int] = []


class LLMConfig(BaseModel):
    """LLM API 配置 — 必填段，缺失则启动报错。"""
    model_config = ConfigDict(frozen=True)

    api_base: str
    api_key: str
    proxy: str | None = None
    judge_model: str = "gpt-3.5-turbo"
    chat_model: str = "gpt-4"


class StorageConfig(BaseModel):
    """数据库与文件路径。"""
    model_config = ConfigDict(frozen=True)

    database_file: str = "qjinera.db"
    data_dir: str = "data"


class TopicConfig(BaseModel):
    """话题检测阈值。"""
    model_config = ConfigDict(frozen=True)

    topic_gap_minutes: int = 10
    continue_gap_seconds: int = 20
    debounce_seconds: float = 3.0
    proactive_chat_interval_minutes: int = 3


class PromptsConfig(BaseModel):
    """所有 Prompt 模板。"""
    model_config = ConfigDict(frozen=True)

    judge_system: str = ""
    chat_system: str = ""
    proactive_system: str = ""
    persona: str = ""
    memory_consolidator_system: str = ""
    memory_extractor_system: str = ""


class LogConfig(BaseModel):
    """日志配置。"""
    model_config = ConfigDict(frozen=True)

    level: str = "INFO"
    log_dir: str = "logs"


# ---------------------------------------------------------------------------
#  顶层配置
# ---------------------------------------------------------------------------

class AppConfig(BaseModel):
    """聚合所有子配置的顶层模型。启动时从 config.toml 加载，运行时只读。"""
    model_config = ConfigDict(frozen=True)

    bot: BotConfig = BotConfig()
    llm: LLMConfig                              # 必填
    storage: StorageConfig = StorageConfig()
    topic: TopicConfig = TopicConfig()
    prompts: PromptsConfig = PromptsConfig()
    log: LogConfig = LogConfig()


# ---------------------------------------------------------------------------
#  加载函数
# ---------------------------------------------------------------------------

def load_config(path: str = "config.toml") -> AppConfig:
    """从 TOML 文件加载配置，启动时调用一次。"""
    config_path = Path(path)

    if not config_path.exists():
        config_path = Path(__file__).parent / path

    if not config_path.exists():
        print(f"[FATAL] 配置文件 {path} 未找到，无法启动。", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "rb") as f:
        raw = tomli.load(f)

    return AppConfig(
        bot=raw.get("bot", {}),
        llm=raw.get("llm", {}),
        storage=raw.get("storage", {}),
        topic=raw.get("topic", {}),
        prompts=raw.get("prompts", {}),
        log=raw.get("log", {}),
    )


# 全局唯一实例 — import 时加载，运行时只读
config = load_config()
