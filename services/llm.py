import openai
import json
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

llm_service = LLMService()
