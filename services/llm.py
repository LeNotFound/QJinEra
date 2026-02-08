import openai
import json
import time
from typing import Dict, Any, List, Optional
from config import settings

class LLMService:
    def __init__(self):
        self.api_key = settings.get("llm", "api_key")
        self.api_base = settings.get("llm", "api_base")
        self.proxy = settings.get("llm", "proxy")
        
        self.client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_base,
            http_client=openai.DefaultAsyncHttpxClient(proxy=self.proxy) if self.proxy else None
        )
        
        self.judge_model = settings.get("llm", "judge_model", "gpt-3.5-turbo")
        self.chat_model = settings.get("llm", "chat_model", "gpt-4")

    async def _call_llm(self, model: str, system_prompt: str, user_content: str, json_mode: bool = True) -> Dict[str, Any]:
        print(f"[{model}] Requesting...")
        
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                response_format={"type": "json_object"} if json_mode else None
            )
            content = response.choices[0].message.content
            print(f"[{model}] Response: {content}")
            
            if json_mode:
                return json.loads(content)
            return content
        except Exception as e:
            print(f"LLM Call Error: {e}")
            return {}

    async def judge_interruption(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call the small model to judge if the bot should intervene.
        """
        system_prompt = settings.get("prompts", "judge_system")
        user_content = json.dumps(context, ensure_ascii=False)
        return await self._call_llm(self.judge_model, system_prompt, user_content)

    async def generate_chat(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call the large model to generate chat responses.
        """
        system_prompt = settings.get("prompts", "chat_system")
        user_content = json.dumps(context, ensure_ascii=False)
        return await self._call_llm(self.chat_model, system_prompt, user_content)

    async def generate_proactive_topic(self) -> Dict[str, Any]:
        """
        Call the model to generate a proactive topic.
        """
        system_prompt = settings.get("prompts", "proactive_system")
        return await self._call_llm(self.chat_model, system_prompt, "请开始你的表演")

    async def analyze_user(self, current_profile: str, recent_messages: List[str]) -> str:
        """
        Call the model to update user profile.
        """
        system_prompt = settings.get("prompts", "profiler_system")
        user_content = f"Current Profile: {current_profile}\n\nRecent Messages:\n" + "\n".join(recent_messages)
        return await self._call_llm(self.judge_model, system_prompt, user_content, json_mode=False)

    async def extract_memories(self, recent_messages: List[str]) -> List[str]:
        """
        Extract distinct facts/memories from user messages.
        """
        system_prompt = settings.get("prompts", "memory_extractor_system")
        user_content = "Recent User Messages:\n" + "\n".join(recent_messages)
        
        result = await self._call_llm(self.judge_model, system_prompt, user_content, json_mode=True)
        return result.get("facts", [])

    async def consolidate_memory(self, current_profile: str, active_facts: List[Dict]) -> Dict[str, Any]:
        """
        Consolidate active facts into the long-term user description.
        active_facts: [{"id": 1, "content": "..."}]
        """
        system_prompt = settings.get("prompts", "memory_consolidator_system")
        if not system_prompt:
             # Fallback prompt if config not reloaded
             system_prompt = "You are a memory consolidator. Return JSON {new_description, consolidated_ids, discarded_ids}."

        # Convert timestamp to readable format or relative time
        import datetime
        def format_time(ts):
            return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')

        facts_text = "\n".join([
            f"ID: {f['id']} | Time: {format_time(f['timestamp'])} | Content: {f['content']}" 
            for f in active_facts
        ])
        
        user_content = f"Current Description:\n{current_profile}\n\nNew Active Facts (Current Time: {format_time(time.time())}):\n{facts_text}"
        
        print(f"[LLM] Consolidating memory for {len(active_facts)} facts...")
        return await self._call_llm(self.chat_model, system_prompt, user_content, json_mode=True)

llm_service = LLMService()
