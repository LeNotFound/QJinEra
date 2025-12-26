import streamlit as st
import sqlite3
import pandas as pd
import time
import os

# 页面配置
st.set_page_config(page_title="柒槿年(QJinEra) - 赛博大脑监控", page_icon="🌸", layout="wide")
st.title("🌸 柒槿年 (QJinEra) 运行监控台")

DB_PATH = "qjinera.db"

def get_connection():
    if not os.path.exists(DB_PATH):
        return None
    return sqlite3.connect(DB_PATH)

# 自动刷新逻辑
if 'last_update' not in st.session_state:
    st.session_state.last_update = time.time()

if st.button('🔄 刷新数据'):
    st.session_state.last_update = time.time()
    st.rerun()

col1, col2 = st.columns([2, 1])

conn = get_connection()

if not conn:
    st.error("⚠️ 数据库文件未找到，请先运行机器人 (python main.py) 生成数据库。")
else:
    # --- 左侧：思考日志 ---
    with col1:
        st.subheader("🧠 判官模型思考日志 (Decision Logs)")
        try:
            # 读取最近 10 条决策
            df_logs = pd.read_sql_query(
                "SELECT id, should_intervene, trigger_level, reason, context_summary, datetime(timestamp, 'unixepoch', 'localtime') as time FROM decision_logs ORDER BY id DESC LIMIT 10", 
                conn
            )
            
            for index, row in df_logs.iterrows():
                with st.container(border=True):
                    # 状态图标
                    icon = "🟢" if row['should_intervene'] else "⚪"
                    action = "插话" if row['should_intervene'] else "沉默"
                    
                    st.markdown(f"**{icon} [{row['time']}] 决定: {action} (Level: {row['trigger_level']})**")
                    st.info(f"💡 **理由**: {row['reason']}")
                    
                    if row['context_summary']:
                        with st.expander("查看当时上下文摘要"):
                            st.caption(row['context_summary'])
        except Exception as e:
            st.warning(f"无法读取日志表 (可能是数据库尚未迁移): {e}")

    # --- 右侧：记忆与话题 ---
    with col2:
        st.subheader("👥 群友画像 (Long-term Memory)")
        try:
            df_users = pd.read_sql_query("SELECT nickname, description, interaction_count FROM users ORDER BY interaction_count DESC LIMIT 20", conn)
            st.dataframe(
                df_users, 
                column_config={
                    "nickname": "昵称",
                    "description": "Bot的印象",
                    "interaction_count": "互动"
                },
                hide_index=True,
                use_container_width=True
            )
        except:
            st.text("暂无用户数据")

        st.divider()
        
        st.subheader("💬 活跃话题 (Topics)")
        try:
            df_topics = pd.read_sql_query("SELECT id, summary, datetime(start_time, 'unixepoch', 'localtime') as start FROM topics ORDER BY id DESC LIMIT 5", conn)
            st.dataframe(df_topics, hide_index=True)
        except:
            st.text("暂无话题数据")
            
    conn.close()
