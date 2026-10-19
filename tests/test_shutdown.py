"""验证全局后台任务优雅关机与秒级取消机制。"""

from __future__ import annotations

import asyncio
import time

import pytest

from utils import spawn_task, wait_all_tasks


@pytest.mark.asyncio
async def test_wait_all_tasks_graceful_cancellation():
    """验证后台长任务在 wait_all_tasks 时能被主动取消并毫秒级优雅退出，不会超时卡死。"""
    cancelled = False

    async def long_running_daemon():
        nonlocal cancelled
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled = True
            raise

    spawn_task(long_running_daemon())

    start_t = time.time()
    await wait_all_tasks(timeout=5.0)
    elapsed = time.time() - start_t

    assert cancelled is True
    assert elapsed < 2.0  # 远小于 5 秒超时，毫秒级响应
