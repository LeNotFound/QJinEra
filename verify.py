import asyncio
from unittest.mock import MagicMock, patch
from config import settings
from services.storage import storage
from services.topic import topic_manager
from services.llm import llm_service

async def verify_flow():
    print("=== Starting Verification ===")
    
    # 1. Verify Config
    print(f"Bot Name: {settings.get('bot', 'name')}")
    assert settings.get("bot", "name") == "柒槿年"
    print("[PASS] Config loaded.")

    # 2. Verify Storage
    topic_id = storage.create_topic("group_123", 1000.0)
    print(f"Created Topic ID: {topic_id}")
    storage.add_message(topic_id, "user_1", "Hello", 1001.0)
    msgs = storage.get_topic_messages(topic_id)
    assert len(msgs) == 1
    assert msgs[0]["content"] == "Hello"
    print("[PASS] Storage operations working.")

    # 3. Verify Topic Manager
    # Mock LLM to avoid real API calls
    with patch.object(llm_service, '_call_llm', new_callable=MagicMock) as mock_llm:
        # Setup mock responses
        # First call: Judge (should intervene)
        # Second call: Chat (response)
        
        async def side_effect(model, system, user, json_mode=True):
            # Check for keywords in the system prompt to distinguish models
            if "插话" in system or "judge" in model:
                return {"should_intervene": True, "reason": "Test"}
            else:
                return {
                    "messages": ["Hello there!", "Nice to meet you."],
                    "summary": "User said hello."
                }
        
        mock_llm.side_effect = side_effect

        # Simulate handling a message
        print("Simulating message handling...")
        group_id = "group_test"
        user_id = "user_test"
        content = "Hello QJinEra"
        
        context = topic_manager.handle_message(group_id, user_id, content)
        print("Context built:", context.keys())
        
        # Simulate Plugin Logic (simplified)
        judge_result = await llm_service.judge_interruption(context)
        print(f"Judge Result: {judge_result}")
        
        if judge_result.get("should_intervene"):
            chat_result = await llm_service.generate_chat(context)
            print(f"Chat Result: {chat_result}")
            
            # Verify summary update
            if chat_result.get("summary"):
                topic_manager.update_summary(group_id, chat_result["summary"])
                t = topic_manager.get_current_topic(group_id)
                assert t["summary"] == "User said hello."
                print("[PASS] Topic summary updated.")

    print("=== Verification Completed Successfully ===")

if __name__ == "__main__":
    asyncio.run(verify_flow())
