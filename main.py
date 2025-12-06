from alicebot import Bot
from config import settings

async def main():
    # Initialize AliceBot
    # Note: AliceBot usually requires a config file or dictionary.
    # We will use a minimal config here and rely on our own config.toml for plugin logic.
    # In a real NapCat setup, AliceBot connects via WebSocket.
    
    # For this MVP, we assume the user will run this script.
    # We might need to adjust this based on how AliceBot is typically run (e.g. via CLI).
    # But here is a programmatic entry point.
    
    bot = Bot(
        # config_dict={
        #     "adapter": {
        #         "alicebot.adapter.cqhttp": {
        #             "adapter_type": "reverse-ws",
        #             "host": "127.0.0.1",
        #             "port": 1314,
        #             "url": "/",
        #             "access_token": "", # Add token if needed
        #         }
        #     }
        # }
    )
    
    # We will load our plugin manually or via config if AliceBot supports it.
    # For now, let's just print a startup message.
    print(f"Starting {settings.get('bot', 'name')} ({settings.get('bot', 'english_name')})...")
    
    # Load plugins
    # bot.load_plugins_from_dirs(["plugins"])
    # Or load specific plugin module
    # bot.load_adapters("alicebot.adapter.cqhttp")
    # bot.load_plugins("plugins.core")
    # bot.load_plugins("plugins.scheduler")

    await bot.run_async()

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")
