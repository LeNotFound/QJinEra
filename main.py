"""QJinEra — 拟人化赛博群友 QQBot 入口。"""

from __future__ import annotations

import asyncio

from config import config
from logger import get_logger, setup_logging, shutdown_logging
from services.storage.database import init_db

logger = get_logger("Main")


async def main() -> None:
    # 1. 初始化日志
    setup_logging(level=config.log.level, log_dir=config.log.log_dir)
    logger.info("启动 %s (%s) ...", config.bot.name, config.bot.english_name)

    # 2. 初始化数据库
    init_db()
    logger.info("数据库就绪: %s", config.storage.database_file)

    # 3. 启动 AliceBot
    from alicebot import Bot

    bot = Bot()
    try:
        await bot.run_async()
    finally:
        shutdown_logging()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")
