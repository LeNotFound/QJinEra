from alicebot import Plugin
from alicebot.adapter.cqhttp.event import GroupMessageEvent
import asyncio
import random
from services.topic import topic_manager
from services.llm import llm_service
from config import settings

class QJinEraPlugin(Plugin):
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

        # 1. Topic Management & Context Building
        context = topic_manager.handle_message(group_id, user_id, content, nickname)
        
        # Check if mentioned
        # 1. Check event.to_me (AliceBot standard)
        # 2. Check if message contains [CQ:at,qq=self_id]
        is_mentioned = getattr(event, "to_me", False)
        
        if not is_mentioned:
            # Fallback: Check raw message for CQ code
            # We need to get the bot's self_id. In AliceBot, event.adapter.bot usually holds the bot instance, 
            # but event.self_id is more direct for the received event context.
            self_id = getattr(event, "self_id", None)
            if self_id:
                # Check if the message string representation contains the CQ code
                # event.message is a Message object, str(event.message) should give the CQ code string
                if f"[CQ:at,qq={self_id}]" in str(event.message):
                     is_mentioned = True
        
        if is_mentioned:
            context["is_at_mentioned"] = True
        
        # 2. Judge Interruption
        should_intervene = False
        if context["is_at_mentioned"]:
            print(f"[CorePlugin] Bot was mentioned. Intervening directly.")
            should_intervene = True
        else:
            print(f"[CorePlugin] Not mentioned. Asking Judge Model...")
            judge_result = await llm_service.judge_interruption(context)
            should_intervene = judge_result.get("should_intervene", False)
            print(f"[CorePlugin] Judge Result: {should_intervene}")
            
        if not should_intervene:
            return

        print(f"[CorePlugin] Generating Chat Response...")
        # 3. Generate Chat Response
        # Add flag to request summary if needed (e.g. every 10 messages or if context is long)
        # For MVP, let's just always ask for it or rely on LLM decision
        context["should_return_summary"] = True 
        
        chat_result = await llm_service.generate_chat(context)
        messages = chat_result.get("messages", [])
        summary = chat_result.get("summary")
        
        if summary:
            topic_manager.update_summary(group_id, summary)
            
        # 4. Send Messages
        for msg in messages:
            # Simulate typing delay
            delay = random.uniform(0.3, 1.2) + (len(msg) * 0.05)
            await asyncio.sleep(delay)
            await event.reply(msg)

    async def rule(self) -> bool:
        return isinstance(self.event, GroupMessageEvent)
