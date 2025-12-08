from alicebot import Plugin
from alicebot.adapter.cqhttp.event import GroupMessageEvent
import asyncio
import random
from services.topic import topic_manager
from services.llm import llm_service
from config import settings

class QJinEraPlugin(Plugin):
    # Class-level dictionary to store debounce tasks
    # Key: group_id, Value: asyncio.Task
    _debounce_tasks: dict[str, asyncio.Task] = {}

    async def handle(self) -> None:
        event = self.event
        if not isinstance(event, GroupMessageEvent):
            return

        print(f"[CorePlugin] Handling event: {event.message_id} from user {event.user_id}")

        user_id = str(event.user_id)
        group_id = str(event.group_id)
        content = event.get_plain_text()
        
        # Get nickname if available
        nickname = ""
        if hasattr(event, "sender") and hasattr(event.sender, "nickname"):
            nickname = event.sender.nickname

        # 1. Topic Management & Context Building (Always update immediately)
        context = topic_manager.handle_message(group_id, user_id, content, nickname)
        
        # Check if mentioned
        # 1. Check event.to_me (AliceBot standard)
        # 2. Check if message contains [CQ:at,qq=self_id]
        is_mentioned = getattr(event, "to_me", False)
        
        if not is_mentioned:
            # Fallback: Check raw message for CQ code
            self_id = getattr(event, "self_id", None)
            if self_id:
                if f"[CQ:at,qq={self_id}]" in str(event.message):
                     is_mentioned = True
        
        if is_mentioned:
            context["is_at_mentioned"] = True
            # If mentioned, cancel any pending debounce task for this group to avoid double reply
            if group_id in self._debounce_tasks:
                self._debounce_tasks[group_id].cancel()
                print(f"[CorePlugin] Mentioned! Cancelled pending debounce for group {group_id}")
            
            print(f"[CorePlugin] Bot was mentioned. Intervening directly.")
            await self.process_chat(context, event)
            return

        # 2. Debounce for Judge
        # Cancel existing task for this group
        if group_id in self._debounce_tasks:
            self._debounce_tasks[group_id].cancel()
            
        # Schedule new task
        # Use the current event for replying (it's the latest one)
        debounce_time = settings.get("topic", "debounce_seconds", 3.0)
        task = asyncio.create_task(self.debounce_and_judge(group_id, event, debounce_time))
        self._debounce_tasks[group_id] = task

    async def debounce_and_judge(self, group_id: str, event, delay: float):
        try:
            await asyncio.sleep(delay)
            
            # Get fresh context (re-fetch because new messages might have arrived)
            context = topic_manager.get_latest_context(group_id)
            if not context:
                return

            print(f"[CorePlugin] Debounce finished. Asking Judge Model...")
            judge_result = await llm_service.judge_interruption(context)
            should_intervene = judge_result.get("should_intervene", False)
            print(f"[CorePlugin] Judge Result: {should_intervene}")
            
            if should_intervene:
                await self.process_chat(context, event)
                
        except asyncio.CancelledError:
            # This is expected when a new message arrives before the timer expires
            pass
        except Exception as e:
            print(f"[CorePlugin] Error in debounce task: {e}")

    async def process_chat(self, context: dict, event):
        print(f"[CorePlugin] Generating Chat Response...")
        # 3. Generate Chat Response
        context["should_return_summary"] = True 
        
        chat_result = await llm_service.generate_chat(context)
        messages = chat_result.get("messages", [])
        summary = chat_result.get("summary")
        
        if summary:
            topic_manager.update_summary(str(event.group_id), summary)
            
        # 4. Send Messages
        for msg in messages:
            # Simulate typing delay
            delay = random.uniform(0.3, 1.2) + (len(msg) * 0.05)
            await asyncio.sleep(delay)
            await event.reply(msg)

    async def rule(self) -> bool:
        return isinstance(self.event, GroupMessageEvent)
