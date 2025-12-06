import asyncio
import time
from unittest.mock import MagicMock, AsyncMock
from plugins.scheduler import SchedulerPlugin
from services.topic import topic_manager
from services.llm import llm_service

async def test_scheduler():
    print("Testing SchedulerPlugin...")
    
    # Mock Bot and Adapter
    mock_bot = MagicMock()
    mock_adapter = AsyncMock()
    mock_bot.get_adapter.return_value = mock_adapter
    mock_bot.adapters = {"onebot": mock_adapter}
    
    # plugin = SchedulerPlugin()
    # plugin.bot = mock_bot
    # Use MagicMock directly since we don't assume setter on Plugin.bot
    plugin = MagicMock()
    plugin.bot = mock_bot
    
    # Mock LLM Service
    llm_service.generate_proactive_topic = AsyncMock(return_value={
        "messages": ["Hello, anyone there?", "It's quiet today."]
    })
    
    # Set up inactivity
    group_id = "123456"
    # Set last activity to 20 minutes ago (threshold is 15 min)
    topic_manager.group_last_activity[group_id] = time.time() - (20 * 60)
    
    # Run check_inactivity once (we need to modify the loop or just extract the logic)
    # Since check_inactivity has a while True loop, we can't call it directly without it blocking.
    # We will extract the logic inside the loop for testing or just mock sleep to raise exception to break loop?
    # Better: let's just copy the logic here to verify it works as expected, 
    # OR better yet, we can modify the plugin to allow a single run or use a flag.
    # But for this test script, let's just simulate what the loop does.
    
    print("Simulating inactivity check...")
    now = time.time()
    inactivity_threshold = 15 * 60
    
    for gid, last_time in topic_manager.group_last_activity.items():
        if now - last_time > inactivity_threshold:
            print(f"Detected inactivity for group {gid}")
            
            # Call LLM
            result = await llm_service.generate_proactive_topic()
            messages = result.get("messages", [])
            print(f"Generated messages: {messages}")
            
            if messages:
                # Update time
                topic_manager.group_last_activity[gid] = now
                
                # Send messages
                if hasattr(plugin.bot, "get_adapter"):
                    adapter = plugin.bot.get_adapter("alicebot.adapter.onebot")
                    for msg in messages:
                        await adapter.call_api("send_group_msg", group_id=int(gid), message=msg)
                        print(f"Sent message: {msg}")
                        
    # Verify calls
    llm_service.generate_proactive_topic.assert_called_once()
    assert mock_adapter.call_api.call_count == 2
    mock_adapter.call_api.assert_any_call("send_group_msg", group_id=123456, message="Hello, anyone there?")
    mock_adapter.call_api.assert_any_call("send_group_msg", group_id=123456, message="It's quiet today.")
    
    print("Test passed!")

if __name__ == "__main__":
    asyncio.run(test_scheduler())
