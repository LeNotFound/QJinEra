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
            content TEXT,
            timestamp REAL,
            FOREIGN KEY(topic_id) REFERENCES topics(id)
        )
        ''')
        
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

    def update_topic_summary(self, topic_id: int, summary: str, end_time: float):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE topics SET summary = ?, end_time = ? WHERE id = ?', (summary, end_time, topic_id))
        conn.commit()
        conn.close()

    def add_message(self, topic_id: int, user_id: str, content: str, timestamp: float):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO messages (topic_id, user_id, content, timestamp) VALUES (?, ?, ?, ?)', 
                       (topic_id, user_id, content, timestamp))
        conn.commit()
        conn.close()

    def get_topic_messages(self, topic_id: int, limit: int = 50) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, content, timestamp FROM messages WHERE topic_id = ? ORDER BY timestamp ASC LIMIT ?', (topic_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return [{"user_id": r[0], "content": r[1], "timestamp": r[2]} for r in rows]

storage = Storage()
