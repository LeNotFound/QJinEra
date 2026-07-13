"""全局公共工具函数库。"""

import asyncio
from typing import Coroutine, Any

from logger import get_logger

logger = get_logger("Utils")

_background_tasks: set[asyncio.Task] = set()


def spawn_task(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """
    发起一个后台异步任务（fire-and-forget）。
    自动将其加入全局强引用集合，防止被 Python 的垃圾回收器(GC)中途意外销毁。
    """
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def wait_all_tasks(timeout: float = 5.0) -> None:
    """
    等待所有后台任务执行完毕（通常用于优雅关机）。
    """
    if not _background_tasks:
        return

    logger.info("正在等待 %d 个后台任务完成...", len(_background_tasks))
    try:
        # 使用 wait 并在超时后不再死等
        await asyncio.wait(_background_tasks, timeout=timeout)
        if _background_tasks:
            logger.warning("有 %d 个任务未能在 %ss 内完成。", len(_background_tasks), timeout)
        else:
            logger.info("所有后台任务已优雅结束。")
    except Exception as e:
        logger.error("等待后台任务时发生异常: %s", e)
