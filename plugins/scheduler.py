from alicebot import Plugin
import time
import asyncio
from services.topic import topic_manager
from services.llm import llm_service
from config import settings

class SchedulerPlugin(Plugin):
    async def handle(self) -> None:
        pass

    async def rule(self) -> bool:
        return False

    async def on_ready(self):
        print("[Scheduler] Plugin loaded. Starting background task...")
        # Wait a bit for adapter to be fully ready
        await asyncio.sleep(5)
        await self.init_groups()
        asyncio.create_task(self.check_inactivity())

    async def init_groups(self):
        try:
            adapter = None
            # Try to find the CQHTTP adapter
            for a in self.bot.adapters.values():
                adapter = a
                break
            
            if adapter:
                print("[Scheduler] Fetching group list...")
                try:
                    groups = await adapter.call_api("get_group_list")
                    now = time.time()
                    for g in groups:
                        gid = str(g["group_id"])
                        if gid not in topic_manager.group_last_activity:
                            # Initialize with current time to avoid immediate trigger upon restart
                            topic_manager.group_last_activity[gid] = now
                            print(f"[Scheduler] Discovered group {gid}, initialized timer.")
                except Exception as api_err:
                    print(f"[Scheduler] API Error (get_group_list): {api_err}")
            else:
                print("[Scheduler] No adapter found during init.")
        except Exception as e:
            print(f"[Scheduler] Failed to init groups: {e}")

    async def check_inactivity(self):
        interval = 60  # Check every minute
        
        while True:
            await asyncio.sleep(interval)
            
            threshold_minutes = settings.get("topic", "proactive_chat_interval_minutes", 15)
            inactivity_threshold = threshold_minutes * 60
            
            now = time.time()
            # print(f"[Scheduler] Checking inactivity... Threshold: {threshold_minutes}m")
            
            # Iterate over a copy to avoid runtime modification issues
            for group_id, last_time in list(topic_manager.group_last_activity.items()):
                if now - last_time > inactivity_threshold:
                    try:
                        print(f"[Scheduler] Group {group_id} is inactive (> {threshold_minutes}m). Triggering proactive message.")
                        
                        # Generate topic
                        result = await llm_service.generate_proactive_topic()
                        messages = result.get("messages", [])
                        
                        if messages:
                            # Update activity time FIRST to prevent double trigger
                            topic_manager.group_last_activity[group_id] = now
                            
                            # Send messages
                            adapter = None
                            for a in self.bot.adapters.values():
                                adapter = a
                                break
                                
                            if adapter:
                                for msg in messages:
                                    # Use send_group_msg API
                                    await adapter.call_api("send_group_msg", group_id=int(group_id), message=msg)
                                    
                                    # Record bot message to context
                                    # Try to get self_id from adapter, fallback to 'bot'
                                    # Note: adapter might not have self_id attribute directly accessible if it's generic
                                    bot_id = "bot" 
                                    # In AliceBot CQHTTP, adapter usually has bot info after connect
                                    
                                    topic_manager.add_bot_message(group_id, msg, bot_id, "柒槿年")
                                    
                                    await asyncio.sleep(2) # Delay
                                    
                                print(f"[Proactive] Sent to {group_id}: {messages}")
                            else:
                                print("[Scheduler] No adapter found to send message.")
                            
                    except Exception as e:
                        print(f"[Scheduler] Error processing group {group_id}: {e}")
