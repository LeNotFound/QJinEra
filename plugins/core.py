from alicebot import Plugin
from alicebot.adapter.cqhttp.event import GroupMessageEvent
import asyncio
import random
import re
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
        
        # [修改] 预处理消息，防止图片被过滤为空字符串
        raw_message = str(event.message)
        # 将 CQ 码图片替换为文本标记，让 LLM 知道这里有图
        content = re.sub(r'\[CQ:image,[^\]]+\]', ' [图片] ', raw_message)
        # 移除其他 CQ 码（可选）并去两端空格
        content = re.sub(r'\[CQ:[^\]]+\]', '', content).strip()

        # 如果处理后为空（例如只发了表情），给个默认值防止报错
        if not content:
            content = "[表情/图片]"
        
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
        
        # Note: Memory update is now triggered by the Judge model inside debounce_and_judge

    async def debounce_and_judge(self, group_id: str, event, delay: float):
        try:
            await asyncio.sleep(delay)
            
            # Get fresh context (re-fetch because new messages might have arrived)
            context = topic_manager.get_latest_context(group_id)
            if not context:
                return

            print(f"[CorePlugin] Debounce finished. Asking Judge Model...")
            judge_result = await llm_service.judge_interruption(context)
            
            # [新增] 核心修改：将思考过程写入数据库
            try:
                from services.storage import storage
                storage.add_decision_log(
                    group_id=group_id,
                    judge_model=settings.get("llm", "judge_model", "unknown"),
                    result=judge_result,
                    context_summary=context.get("topic_summary", "")
                )
            except Exception as e:
                print(f"[CorePlugin] Log Error: {e}")

            # 1. Memory Extraction Trigger
            # If the Judge thinks there's significant info, trigger the extractor
            if judge_result.get("has_significant_info", False):
                user_id = str(event.user_id) # Use the ID from the event that triggered this
                print(f"[CorePlugin] Judge detected significant info. Triggering memory extraction for {user_id}...")
                asyncio.create_task(self.update_user_profile(group_id, user_id))

            # 2. Intervention Decision
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
            
        for msg in messages:
            # Simulate typing delay
            delay = random.uniform(0.3, 1.2) + (len(msg) * 0.05)
            await asyncio.sleep(delay)
            await event.reply(msg)
            
            # Record bot's own message
            bot_id = str(getattr(event, "self_id", "bot"))
            topic_manager.add_bot_message(str(event.group_id), msg, bot_id, "柒槿年")

    async def update_user_profile(self, group_id: str, user_id: str):
        try:
            from services.storage import storage
            
            # Check if user exists (to ensure basic record)
            user = storage.get_user(group_id, user_id)
            if not user:
                return

            # Get recent messages from this user in this group
            topic = topic_manager.get_current_topic(group_id)
            if not topic:
                return
                
            user_msgs = [m["content"] for m in topic["messages"] if m["user_id"] == user_id]
            if len(user_msgs) < 2: # Reduce threshold to capture facts quickly
                return

            print(f"[CorePlugin] Extracting memories for user {user_id}...")
            
            # Extract new facts
            new_facts = await llm_service.extract_memories(user_msgs[-10:])
            
            if new_facts:
                print(f"[CorePlugin] Found {len(new_facts)} new memories for {user_id}")
                for fact in new_facts:
                    storage.add_memory(user_id, group_id, fact)
                    print(f"  + Memory: {fact}")
                
        except Exception as e:
            print(f"[CorePlugin] Error updating user profile: {e}")


    async def rule(self) -> bool:
        return isinstance(self.event, GroupMessageEvent)
