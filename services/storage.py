import sqlite3
import json
import os
import time
from typing import List, Dict, Any, Optional
from config import settings

class Storage:
    def __init__(self):
        self.db_path = settings.get("storage", "database_file", "qjinera.db")
        self.data_dir = settings.get("storage", "data_dir", "data")
        
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create topics table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT,
            start_time REAL,
            end_time REAL,
            summary TEXT
        )
        ''')
        
        # Create messages table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER,
            user_id TEXT,
            nickname TEXT,
            content TEXT,
            timestamp REAL,
            FOREIGN KEY(topic_id) REFERENCES topics(id)
        )
        ''')

        # Create users table for user profiles
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT,
            group_id TEXT,
            nickname TEXT,
            description TEXT,
            interaction_count INTEGER DEFAULT 0,
            last_active_time REAL,
            PRIMARY KEY (user_id, group_id)
        )
        ''')
        
        # [新增] 决策日志表 - 用于 Dashboard 可视化监控
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS decision_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT,
            timestamp REAL,
            judge_model TEXT,
            should_intervene BOOLEAN,
            trigger_level TEXT,
            reason TEXT,
            context_summary TEXT
        )
        ''')

        # [新增] 记忆表 - 用于存储用户特定的事实 (Gemini Style)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            group_id TEXT,
            content TEXT,
            timestamp REAL,
            UNIQUE(user_id, content)
        )
        ''')

        # Check if nickname column exists in messages (for migration)
        cursor.execute("PRAGMA table_info(messages)")
        columns = [info[1] for info in cursor.fetchall()]
        if "nickname" not in columns:
            try:
                cursor.execute("ALTER TABLE messages ADD COLUMN nickname TEXT")
            except Exception as e:
                print(f"Migration warning: {e}")
        
        conn.commit()
        conn.close()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    # JSON Operations
    def save_json(self, filename: str, data: Any):
        path = os.path.join(self.data_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_json(self, filename: str, default: Any = None) -> Any:
        path = os.path.join(self.data_dir, filename)
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    # Database Operations
    def create_topic(self, group_id: str, start_time: float) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO topics (group_id, start_time) VALUES (?, ?)', (group_id, start_time))
        topic_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return topic_id

    def update_topic_summary(self, topic_id: int, summary: str, end_time: float = None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if end_time:
            cursor.execute('UPDATE topics SET summary = ?, end_time = ? WHERE id = ?', (summary, end_time, topic_id))
        else:
            cursor.execute('UPDATE topics SET summary = ? WHERE id = ?', (summary, topic_id))
        conn.commit()
        conn.close()

    def add_message(self, topic_id: int, user_id: str, content: str, timestamp: float, nickname: str = ""):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO messages (topic_id, user_id, nickname, content, timestamp) VALUES (?, ?, ?, ?, ?)', 
                       (topic_id, user_id, nickname, content, timestamp))
        conn.commit()
        conn.close()

    def get_topic_messages(self, topic_id: int, limit: int = 50) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, nickname, content, timestamp FROM messages WHERE topic_id = ? ORDER BY timestamp ASC LIMIT ?', (topic_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return [{"user_id": r[0], "nickname": r[1], "content": r[2], "timestamp": r[3]} for r in rows]

    def get_user(self, group_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE group_id = ? AND user_id = ?', (group_id, user_id))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "user_id": row[0],
                "group_id": row[1],
                "nickname": row[2],
                "description": row[3],
                "interaction_count": row[4],
                "last_active_time": row[5]
            }
        return None

    def update_user(self, group_id: str, user_id: str, nickname: str, timestamp: float):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute('SELECT interaction_count FROM users WHERE group_id = ? AND user_id = ?', (group_id, user_id))
        row = cursor.fetchone()
        
        if row:
            new_count = row[0] + 1
            cursor.execute('''
                UPDATE users 
                SET nickname = ?, interaction_count = ?, last_active_time = ? 
                WHERE group_id = ? AND user_id = ?
            ''', (nickname, new_count, timestamp, group_id, user_id))
        else:
            cursor.execute('''
                INSERT INTO users (user_id, group_id, nickname, interaction_count, last_active_time)
                VALUES (?, ?, ?, 1, ?)
            ''', (user_id, group_id, nickname, timestamp))
            
        conn.commit()
        conn.close()

    def update_user_description(self, group_id: str, user_id: str, description: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET description = ? WHERE group_id = ? AND user_id = ?', (description, group_id, user_id))
        conn.commit()
        conn.close()

    def add_decision_log(self, group_id: str, judge_model: str, result: Dict, context_summary: Optional[str]):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO decision_logs (group_id, timestamp, judge_model, should_intervene, trigger_level, reason, context_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                group_id, 
                time.time(), 
                judge_model,
                result.get("should_intervene", False),
                result.get("trigger_level", "none"),
                result.get("reason", ""),
                context_summary or ""
            ))
            conn.commit()
        except Exception as e:
            print(f"[Storage] Failed to log decision: {e}")
        finally:
            conn.close()

    def add_memory(self, user_id: str, group_id: str, content: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO memories (user_id, group_id, content, timestamp)
                VALUES (?, ?, ?, ?)
            ''', (user_id, group_id, content, time.time()))
            conn.commit()
        except Exception as e:
            print(f"[Storage] Failed to add memory: {e}")
        finally:
            conn.close()

    def get_memories(self, user_id: str, limit: int = 20) -> List[str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT content FROM memories 
            WHERE user_id = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (user_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows]

    def get_recent_topics(self, group_id: str, limit: int = 5) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, summary, start_time, end_time 
            FROM topics 
            WHERE group_id = ? AND summary IS NOT NULL 
            ORDER BY start_time DESC 
            LIMIT ?
        ''', (group_id, limit))
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {"id": r[0], "summary": r[1], "start_time": r[2], "end_time": r[3]} 
            for r in rows
        ]

    def get_latest_active_topic(self, group_id: str) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        # Find the latest topic that hasn't been "closed" (end_time is NULL or 0)
        # Or just the latest one, and we let logic decide if it's stale
        cursor.execute('''
            SELECT id, start_time, end_time, summary 
            FROM topics 
            WHERE group_id = ? 
            ORDER BY start_time DESC 
            LIMIT 1
        ''', (group_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return None
            
        topic_id, start_time, end_time, summary = row
        
        # Get messages for this topic
        cursor.execute('''
            SELECT user_id, nickname, content, timestamp 
            FROM messages 
            WHERE topic_id = ? 
            ORDER BY timestamp ASC
        ''', (topic_id,))
        messages = [
            {"user_id": r[0], "nickname": r[1], "content": r[2], "timestamp": r[3]}
            for r in cursor.fetchall()
        ]
        conn.close()
        
        return {
            "topic_id": topic_id,
            "start_time": start_time,
            "last_msg_time": messages[-1]["timestamp"] if messages else start_time,
            "messages": messages,
            "summary": summary
        }
        
storage = Storage()
