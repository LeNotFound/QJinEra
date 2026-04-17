"""
QJinEra 异步日志系统。

- 控制台：彩色输出，保持 [ModuleName] 风格的可读性
- 文件：logs/latest.log，每天午夜自动轮转为 logs/qjinera_YYYY-MM-DD.log
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

    # --- 跨天重启日志检查与归档 ---
    latest_log_path = os.path.join(log_dir, "latest.log")
    if os.path.exists(latest_log_path):
        try:
            mtime = os.path.getmtime(latest_log_path)
            last_mod_date = datetime.fromtimestamp(mtime).date()
            today_date = datetime.today().date()
            
            # 如果文件的最后修改日期不是今天，则代表跨天重启，将其归档
            if last_mod_date != today_date:
                date_str = last_mod_date.strftime("%Y-%m-%d")
                backup_log_path = os.path.join(log_dir, f"qjinera_{date_str}.log")
                
                if not os.path.exists(backup_log_path):
                    os.rename(latest_log_path, backup_log_path)
                else:
                    # 如果目标备份文件存在，则采用安全的追加模式
                    with open(latest_log_path, 'r', encoding='utf-8') as src:
                        content = src.read()
                    with open(backup_log_path, 'a', encoding='utf-8') as dst:
                        if content and content[0] != '\n':
                            dst.write("\n")
                        dst.write(content)
                    os.remove(latest_log_path)
        except Exception as e:
            # 异常时不要阻断启动
            print(f"日志初始化时处理跨天遗留文件出错: {e}", file=sys.stderr)

    log_level = getattr(logging, level.upper(), logging.INFO)

    # — 控制台 Handler —
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    console.setFormatter(_ConsoleFormatter())

    # — 文件 Handler —
    log_file = os.path.join(log_dir, "latest.log")
    file_h = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=0, encoding="utf-8"
    )
    
    def _namer(default_name: str) -> str:
        dir_name, base_name = os.path.split(default_name)
        if base_name.startswith("latest.log."):
            date_str = base_name[len("latest.log."):]
            return os.path.join(dir_name, f"qjinera_{date_str}.log")
        return default_name

    file_h.namer = _namer
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
