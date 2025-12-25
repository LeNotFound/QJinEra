from alicebot import Bot
from config import settings

async def main():
    
    cqhttp_config = settings.get("adapter.cqhttp")
    
    bot = Bot()
    
    print(f"Starting {settings.get('bot', 'name')} ({settings.get('bot', 'english_name')})...")

    await bot.run_async()

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")
