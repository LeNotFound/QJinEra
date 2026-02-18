"""
QJinEra 异步日志系统。

- 控制台：彩色输出，保持 [ModuleName] 风格的可读性
- 文件：logs/qjinera_YYYY-MM-DD.log，按天一个文件
- 异步：QueueHandler + QueueListener，文件 I/O 不阻塞事件循环

Usage:
    from logger import get_logger

    logger = get_logger("CorePlugin")
    logger.info("处理消息 %s", msg_id)
    logger.error("出错", exc_info=True)      # 自动附带 traceback
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import queue
import sys
from datetime import datetime


# ---------------------------------------------------------------------------
#  ANSI 颜色
# ---------------------------------------------------------------------------

class _C:
    """ANSI escape codes for terminal colors."""
    RESET  = "\033[0m"
    GREY   = "\033[38;5;245m"
    GREEN  = "\033[38;5;114m"
    YELLOW = "\033[38;5;220m"
    RED    = "\033[38;5;196m"
    B_RED  = "\033[1;38;5;196m"
    CYAN   = "\033[38;5;80m"


_LEVEL_COLORS = {
    logging.DEBUG:    _C.GREY,
    logging.INFO:     _C.GREEN,
    logging.WARNING:  _C.YELLOW,
    logging.ERROR:    _C.RED,
    logging.CRITICAL: _C.B_RED,
}


# ---------------------------------------------------------------------------
#  格式化器
# ---------------------------------------------------------------------------

class _ConsoleFormatter(logging.Formatter):
    """控制台彩色格式化器，模拟原来 print("[Module] msg") 的风格。
    
    输出示例：07:22:34 I [CorePlugin] 处理消息 12345
    """

    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, _C.RESET)
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        lvl = record.levelname[0]                       # I / D / W / E / C
        msg = record.getMessage()

        parts = [
            f"{_C.GREY}{ts}{_C.RESET}",
            f"{color}{lvl}{_C.RESET}",
            f"{_C.CYAN}[{record.name}]{_C.RESET}",
            msg,
        ]
        text = " ".join(parts)

        if record.exc_info and record.exc_info[0] is not None:
            text += "\n" + self.formatException(record.exc_info)
        return text


class _FileFormatter(logging.Formatter):
    """文件格式化器 — 结构化、可 grep。
    
    输出示例：2026-02-18 07:22:34.123 | INFO    | CorePlugin | 处理消息 12345
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        msg = f"{ts} | {record.levelname:<7} | {record.name} | {record.getMessage()}"
        if record.exc_info and record.exc_info[0] is not None:
            msg += "\n" + self.formatException(record.exc_info)
        return msg


# ---------------------------------------------------------------------------
#  全局状态
# ---------------------------------------------------------------------------

_listener: logging.handlers.QueueListener | None = None


# ---------------------------------------------------------------------------
#  公开 API
# ---------------------------------------------------------------------------

def setup_logging(level: str = "INFO", log_dir: str = "logs") -> None:
    """初始化日志系统，启动时调用一次。"""
    global _listener

    os.makedirs(log_dir, exist_ok=True)
    log_level = getattr(logging, level.upper(), logging.INFO)

    # — 控制台 Handler —
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    console.setFormatter(_ConsoleFormatter())

    # — 文件 Handler —
    log_file = os.path.join(log_dir, f"qjinera_{datetime.now().strftime('%Y-%m-%d')}.log")
    file_h = logging.FileHandler(log_file, encoding="utf-8")
    file_h.setLevel(logging.DEBUG)                  # 文件始终 DEBUG
    file_h.setFormatter(_FileFormatter())

    # — 异步队列（QueueHandler → QueueListener） —
    log_queue: queue.Queue[logging.LogRecord] = queue.Queue(-1)
    queue_handler = logging.handlers.QueueHandler(log_queue)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(queue_handler)

    _listener = logging.handlers.QueueListener(
        log_queue, console, file_h, respect_handler_level=True,
    )
    _listener.start()

    # 降低第三方库的日志噪音
    for name in ("openai", "httpx", "httpcore", "websockets"):
        logging.getLogger(name).setLevel(logging.WARNING)


def shutdown_logging() -> None:
    """关闭日志系统，确保队列中的消息全部刷盘。"""
    global _listener
    if _listener:
        _listener.stop()
        _listener = None


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的 Logger。"""
    return logging.getLogger(name)
