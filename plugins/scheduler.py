from alicebot import Plugin
import time
import asyncio
from alicebot.adapter.cqhttp.message import CQHTTPMessage
from services.topic import topic_manager
from services.llm import llm_service
from config import settings

class SchedulerPlugin(Plugin):
    async def handle(self) -> None:
        pass

    async def rule(self) -> bool:
        return False

    async def on_ready(self):
        # Start the background task
        asyncio.create_task(self.check_inactivity())

    async def check_inactivity(self):
        interval = 60  # Check every minute
        inactivity_threshold = 15 * 60  # 15 minutes
        
        while True:
            await asyncio.sleep(interval)
            now = time.time()
            
            for group_id, last_time in topic_manager.group_last_activity.items():
                if now - last_time > inactivity_threshold:
                    try:
                        print(f"[Scheduler] Group {group_id} is inactive. Triggering proactive message.")
                        
                        # Generate topic
                        result = await llm_service.generate_proactive_topic()
                        messages = result.get("messages", [])
                        
                        if messages:
                            # Update activity time to prevent double trigger
                            topic_manager.group_last_activity[group_id] = now
                            
                            # Send messages using OneBot adapter
                            if hasattr(self.bot, "get_adapter"):
                                try:
                                    adapter = self.bot.get_adapter("alicebot.adapter.cqhttp")
                                    # If not found by name, try getting the first one or handle error
                                except Exception:
                                    # Fallback or try to find any adapter
                                    # In a real scenario, we should know the adapter name.
                                    # Assuming standard "alicebot.adapter.onebot" or similar.
                                    # Let's try to iterate or just log if not found.
                                    adapter = None
                                    for a in self.bot.adapters.values():
                                        adapter = a
                                        break
                                
                                if adapter:
                                    for msg in messages:
                                        await adapter.send(CQHTTPMessage(msg), group_id=int(group_id))
                                        await asyncio.sleep(1) # Delay between messages
                                else:
                                    print("[Scheduler] No adapter found to send message.")
                            
                            print(f"[Proactive] Sent to {group_id}: {messages}")
                            
                    except Exception as e:
                        print(f"[Scheduler] Error: {e}")
