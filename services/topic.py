import time
from typing import List, Dict, Optional
from config import settings
from services.storage import storage

class TopicManager:
    def __init__(self):
        self.topic_gap = settings.get("topic", "topic_gap_minutes", 10) * 60
        self.continue_gap = settings.get("topic", "continue_gap_seconds", 20)
        
        # In-memory cache for current topic per group
        # {group_id: {"topic_id": int, "last_msg_time": float, "messages": []}}
        self.active_topics: Dict[str, Dict] = {}
        
        # Track last activity time for all groups to support active speaking
        # {group_id: float_timestamp}
        self.group_last_activity: Dict[str, float] = {}

    def get_current_topic(self, group_id: str) -> Dict:
        return self.active_topics.get(group_id)

    def get_latest_context(self, group_id: str) -> Optional[Dict]:
        topic = self.active_topics.get(group_id)
        if not topic or not topic["messages"]:
            return None
            
        last_msg = topic["messages"][-1]
        return self._build_context(
            group_id, 
            last_msg["user_id"], 
            last_msg["content"], 
            last_msg["timestamp"]
        )

    def handle_message(self, group_id: str, user_id: str, content: str, nickname: str = "") -> Dict:
        """
        Process a new message and determine if it belongs to the current topic or starts a new one.
        Returns the context for the LLM.
        """
        now = time.time()
        current_topic = self.active_topics.get(group_id)
        
        is_new_topic = False
        
        if not current_topic:
            is_new_topic = True
        else:
            last_time = current_topic["last_msg_time"]
            if now - last_time > self.topic_gap:
                # Topic expired, archive it
                self._archive_topic(group_id)
                is_new_topic = True
        
        if is_new_topic:
            topic_id = storage.create_topic(group_id, now)
            current_topic = {
                "topic_id": topic_id,
                "last_msg_time": now,
                "messages": [],
                "summary": None
            }
            self.active_topics[group_id] = current_topic
        
        # Update current topic
        current_topic["last_msg_time"] = now
        current_topic["messages"].append({
            "user_id": user_id,
            "nickname": nickname,
            "content": content,
            "timestamp": now
        })
        
        # Save message to DB
        storage.add_message(current_topic["topic_id"], user_id, content, now, nickname)
        
        self.group_last_activity[group_id] = now
        
        return self._build_context(group_id, user_id, content, now)

    def _archive_topic(self, group_id: str):
        topic = self.active_topics.get(group_id)
        if topic:
            storage.update_topic_summary(topic["topic_id"], topic.get("summary"), topic["last_msg_time"])
            del self.active_topics[group_id]

    def update_summary(self, group_id: str, summary: str):
        if group_id in self.active_topics:
            self.active_topics[group_id]["summary"] = summary

    def _build_context(self, group_id: str, user_id: str, content: str, now: float) -> Dict:
        topic = self.active_topics.get(group_id)
        messages = topic["messages"]
        
        # Calculate time gaps
        time_since_last_group = 0
        time_since_last_user = 0
        
        if len(messages) > 1:
            time_since_last_group = now - messages[-2]["timestamp"]
            
            # Find last message from same user
            for msg in reversed(messages[:-1]):
                if msg["user_id"] == user_id:
                    time_since_last_user = now - msg["timestamp"]
                    break
        
        # Get recent messages (last 10)
        # Use nickname if available, otherwise fallback to user_id
        recent_msgs = []
        for m in messages[-10:]:
            sender_name = m.get("nickname") or m["user_id"]
            recent_msgs.append(f"{sender_name}: {m['content']}")
        
        return {
            "persona": settings.get("prompts", "persona"),
            "recent_messages": recent_msgs,
            "topic_summary": topic.get("summary"),
            "latest_message": content,
            "time_since_last_group_message": time_since_last_group,
            "time_since_last_user_message": time_since_last_user,
            "is_at_mentioned": False # This will be overridden by the plugin
        }

topic_manager = TopicManager()
