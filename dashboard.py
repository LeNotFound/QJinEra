import streamlit as st
import sqlite3
import pandas as pd
import time
import os

# --- Page Config ---
st.set_page_config(
    page_title="柒槿年(QJinEra) - 赛博大脑监控", 
    page_icon="🌸", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- Custom CSS (Sakura Theme) ---
st.markdown("""
<style>
    /* Global Font */
    html, body, [class*="css"] {
        font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    }
    
    /* Background & Main Colors */
    .stApp {
        background-color: #fdf6f9; /* Very light pink background */
    }
    
    /* Headers */
    h1, h2, h3 {
        color: #d63384; /* Deep pink */
        font-weight: 600;
    }
    
    /* Metrics Cards */
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #f3d2e0;
        border-radius: 10px;
        padding: 15px;
        box-shadow: 2px 2px 10px rgba(214, 51, 132, 0.1);
    }
    div[data-testid="stMetricLabel"] {
        color: #888;
        font-size: 0.9rem;
    }
    div[data-testid="stMetricValue"] {
        color: #d63384;
        font-weight: bold;
    }

    /* Decision Cards */
    .decision-card {
        background-color: white;
        padding: 15px;
        border-radius: 12px;
        margin-bottom: 12px;
        border-left: 5px solid #ddd;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        transition: transform 0.2s;
    }
    .decision-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 10px rgba(0,0,0,0.1);
    }
    .status-intervene {
        border-left-color: #198754; /* Green */
    }
    .status-silent {
        border-left-color: #adb5bd; /* Grey */
    }
    .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
    }
    .card-title {
        font-weight: bold;
        color: #333;
    }
    .card-time {
        font-size: 0.85rem;
        color: #999;
    }
    .card-reason {
        color: #555;
        font-size: 0.95rem;
        font-style: italic;
    }
    .card-trigger-level {
        font-size: 0.8rem;
        padding: 2px 8px;
        border-radius: 10px;
        color: white;
    }
    .level-high { background-color: #dc3545; }
    .level-medium { background-color: #ffc107; color: #333; }
    .level-low { background-color: #0dcaf0; color: #333; }
    
    /* Tables */
    .stDataFrame {
        border-radius: 10px;
        overflow: hidden;
        border: 1px solid #f3d2e0;
    }
    
    /* Remove default Streamlit clutter */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
</style>
""", unsafe_allow_html=True)

# --- Database & Logic ---

DB_PATH = "qjinera.db"

def get_connection():
    if not os.path.exists(DB_PATH):
        return None
    return sqlite3.connect(DB_PATH)

def get_metrics():
    conn = get_connection()
    if not conn:
        return 0, 0, "0%"
    
    try:
        # Total decisions today
        df_today = pd.read_sql_query("SELECT should_intervene FROM decision_logs WHERE timestamp > strftime('%s', 'now', 'start of day')", conn)
        total_decisions = len(df_today)
        interventions = df_today['should_intervene'].sum() if total_decisions > 0 else 0
        intervention_rate = f"{(interventions / total_decisions * 100):.1f}%" if total_decisions > 0 else "0%"
        
        # Active Topics count (last 24h)
        active_topics = pd.read_sql_query("SELECT count(*) as cnt FROM topics WHERE start_time > strftime('%s', 'now', '-1 day')", conn).iloc[0]['cnt']
        
        conn.close()
        return total_decisions, active_topics, intervention_rate
    except Exception:
        if conn: conn.close()
        return 0, 0, "0%"

# --- Header ---
st.title("🌸 柒槿年 (QJinEra) · 赛博大脑")
st.caption(f"Last updated: {time.strftime('%H:%M:%S')}")

# Auto-refresh logic
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = False

col_btn, col_toggle = st.columns([1, 4])
with col_btn:
    if st.button('🔄 刷新 (Now)', type="primary"):
        st.rerun()
with col_toggle:
    st.session_state.auto_refresh = st.toggle("⏱️ 自动刷新 (Auto Refresh 3s)", value=st.session_state.auto_refresh)

if st.session_state.auto_refresh:
    time.sleep(3)
    st.rerun()

# --- Metrics Section ---
m1, m2, m3 = st.columns(3)
total_d, active_t, rate = get_metrics()

m1.metric("🧠 今日思考 (Decisions)", total_d, delta="Today")
m2.metric("💬 活跃话题 (24h)", active_t)
m3.metric("⚡ 插话率 (Intervention Rate)", rate)

st.markdown("---")

# --- Main Layout ---
col_log, col_memories, col_stats = st.columns([2, 1.5, 1.5])

conn = get_connection()

if not conn:
    st.error("⚠️ 数据库未找到，请先运行机器人。")
else:
    # === Column 1: Decision Stream ===
    with col_log:
        st.subheader("📡 思维流 (Thoughts)")
        try:
            df_logs = pd.read_sql_query(
                "SELECT id, should_intervene, trigger_level, reason, context_summary, datetime(timestamp, 'unixepoch', 'localtime') as time FROM decision_logs ORDER BY id DESC LIMIT 15", 
                conn
            )
            
            for index, row in df_logs.iterrows():
                # Card Styling
                status_class = "status-intervene" if row['should_intervene'] else "status-silent"
                icon = "🟢 插话" if row['should_intervene'] else "⚪ 沉默"
                level_class = f"level-{row['trigger_level']}" if row['trigger_level'] in ['high', 'medium', 'low'] else "level-low"
                
                # HTML Card
                st.markdown(f"""
                <div class="decision-card {status_class}">
                    <div class="card-header">
                        <span class="card-title">{icon}</span>
                        <span class="card-time">{row['time']}</span>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <span class="card-trigger-level {level_class}">{row['trigger_level'].upper()}</span>
                        <span class="card-reason">{row['reason']}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Expander for context
                if row['context_summary']:
                     with st.expander(f"📜 上下文"):
                        st.caption(row['context_summary'])
                        
        except Exception as e:
            st.warning(f"Error loading logs: {e}")

    # === Column 2: Live Memories ===
    with col_memories:
        st.subheader("🧠 实时记忆 (Memories)")
        try:
            # Check if table exists first
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memories'")
            if cursor.fetchone():
                df_mems = pd.read_sql_query(
                    "SELECT user_id, content, datetime(timestamp, 'unixepoch', 'localtime') as time FROM memories ORDER BY id DESC LIMIT 20", 
                    conn
                )
                if not df_mems.empty:
                    for i, row in df_mems.iterrows():
                        st.info(f"**{row['user_id']}**: {row['content']}")
                else:
                    st.caption("暂无提取到的记忆")
            else:
                st.warning("Memories table not created yet.")
        except Exception as e:
            st.error(f"Error: {e}")

    # === Column 3: Stats (Users & Topics) ===
    with col_stats:
        st.subheader("👥 活跃群友")
        try:
            df_users = pd.read_sql_query("SELECT nickname as '昵称', interaction_count as '互动' FROM users ORDER BY interaction_count DESC LIMIT 10", conn)
            st.dataframe(df_users, hide_index=True, use_container_width=True)
        except:
            st.text("暂无数据")
            
        st.subheader("💬 近期话题")
        try:
            df_topics = pd.read_sql_query("SELECT summary as '摘要' FROM topics WHERE summary IS NOT NULL ORDER BY id DESC LIMIT 8", conn)
            st.dataframe(df_topics, hide_index=True, use_container_width=True)
        except:
            st.text("暂无数据")

    conn.close()
