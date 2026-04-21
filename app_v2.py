import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
import time
import plotly.express as px
from google import genai

# ==========================================
# 1. CONFIGURATION & CUSTOM CSS
# ==========================================
# 嚴格只從 Streamlit Cloud 的 Secrets 讀取
MY_API_KEY = st.secrets.get("GOOGLE_API_KEY")
DB_NAME = "finance.db"

def apply_custom_style():
    """加載極致美化 CSS"""
    st.markdown("""
        <style>
        .main { background-color: #f8f9fa; }
        /* 美化側邊欄按鈕 */
        .stButton > button {
            border-radius: 8px;
            transition: all 0.3s ease;
        }
        /* 數據卡片樣式 */
        [data-testid="stMetricValue"] { font-size: 2rem; color: #007bff; font-weight: 700; }
        [data-testid="stMetricLabel"] { font-size: 1.1rem; font-weight: 500; }
        /* 聊天視窗優化 */
        .stChatMessage { border-radius: 12px; border: 1px solid #e9ecef; margin-bottom: 10px; }
        </style>
    """, unsafe_allow_html=True)

def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

# ==========================================
# 2. DATABASE FUNCTIONS (User-Scoped & Migration)
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, category TEXT, description TEXT, username TEXT)')
    # 自動資料庫遷移邏輯
    c.execute("PRAGMA table_info(transactions)")
    columns = [info[1] for info in c.fetchall()]
    if 'username' not in columns:
        c.execute("ALTER TABLE transactions ADD COLUMN username TEXT")
    conn.commit(); conn.close()

def add_user(u, p):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (u, make_hashes(p)))
        conn.commit(); return True
    except: return False
    finally: conn.close()

def login_user(u, p):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("SELECT password FROM users WHERE username = ?", (u,))
    data = c.fetchone()
    conn.close()
    return data and make_hashes(p) == data[0]

def insert_transaction(amt, cat, desc, user):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("INSERT INTO transactions (amount, category, description, username) VALUES (?, ?, ?, ?)", (amt, cat, desc, user))
    conn.commit(); conn.close()

def get_user_transactions(user):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT amount, category, description FROM transactions WHERE username = ?", conn, params=(user,))
    conn.close()
    return df

def clear_user_data(user):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE username = ?", (user,))
    conn.commit(); conn.close()

# ==========================================
# 3. HYBRID AI ENGINE (The Final Solution)
# ==========================================
def local_fallback_parse(text):
    """【終極保底】如果 API 掛掉，使用 Regex 強行解析"""
    nums = re.findall(r'\d+\.?\d*', text.replace(',', ''))
    amount = float(nums[0]) if nums else 0.0
    category = "Others"
    t = text.lower()
    if any(k in t for k in ["food", "eat", "lunch", "dinner", "cafe", "meal"]): category = "Food"
    elif any(k in t for k in ["bus", "taxi", "uber", "gas", "transport"]): category = "Transport"
    elif any(k in t for k in ["rent", "home", "housing", "water", "bill"]): category = "Housing"
    elif any(k in t for k in ["movie", "game", "spotify", "fun"]): category = "Entertainment"
    return {"intent": "log", "amount": amount, "category": category, "description": text, "is_fallback": True}

def process_user_input(user_text, df):
    # 本地快速過濾打招呼
    greetings = ["hi", "hello", "你好", "hey", "thanks", "謝謝"]
    if user_text.lower().strip() in greetings:
        return {"intent": "chat", "chat_reply": "Hello! I'm your AI Finance Assistant. How can I help you today?"}

    if not MY_API_KEY: return local_fallback_parse(user_text)

    try:
        client = genai.Client(api_key=MY_API_KEY)
        history = df.tail(15).to_string(index=False) if not df.empty else "No history."
        prompt = f"""Analyze input: "{user_text}". History: {history}. 
        Return JSON ONLY: {{'intent': 'log', 'amount': 100, 'category': 'Food/Transport/Housing/Entertainment/Others', 'description': 'text'}} 
        or {{'intent': 'chat', 'chat_reply': 'advice'}}"""
        
        time.sleep(1.5) # 防 429 頻率限制
        response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match: return json.loads(match.group(0))
        raise Exception("Format Error")
    except:
        # API 失敗（包含 429）時，自動觸發保底，保證功能不中斷
        return local_fallback_parse(user_text)

# ==========================================
# 4. MAIN UI SYSTEM
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide", page_icon="💰")
    apply_custom_style(); init_db()

    if "logged_in" not in st.session_state: 
        st.session_state.update({"logged_in": False, "username": None, "messages": []})

    if not st.session_state.logged_in:
        st.title("💰 FinSight Pro - Access")
        col_l, col_m, col_r = st.columns([1, 2, 1])
        with col_m:
            choice = st.radio("Action", ["Login", "Signup"], horizontal=True)
            u = st.text_input("Username")
            p = st.text_input("Password", type='password')
            if st.button("Access Dashboard"):
                if choice == "Signup":
                    if add_user(u, p): st.success("Success! Please Login.")
                    else: st.error("User exists or error.")
                elif login_user(u, p):
                    st.session_state.update({"logged_in": True, "username": u}); st.rerun()
                else: st.error("Denied.")
    else:
        username = st.session_state.username
        df = get_user_transactions(username)

        # 側邊欄：快速分析與管理
        with st.sidebar:
            st.title(f"👋 Hi, {username}!")
            if not df.empty:
                st.subheader("⚡ Quick Insights")
                st.info(f"Total spent: ${df['amount'].sum():,.1f}")
                top_c = df.groupby('category')['amount'].sum().idxmax()
                st.info(f"Main Expense: {top_c}")
            st.divider()
            if st.button("🗑️ Clear My Data"): 
                clear_user_data(username); st.session_state.messages = []; st.rerun()
            if st.button("Logout"): 
                st.session_state.update({"logged_in": False, "username": None, "messages": []}); st.rerun()

        # 頂部核心指標
        st.title("💼 Financial Dashboard")
        m1, m2, m3 = st.columns(3)
        total_val = df['amount'].sum() if not df.empty else 0
        m1.metric("Total Spending", f"${total_val:,.1f}")
        m2.metric("Total Records", len(df))
        m3.metric("Top Category", df.groupby('category')['amount'].sum().idxmax() if not df.empty else "N/A")
        st.divider()

        # 分頁標籤
        tab_chat, tab_data = st.tabs(["💬 AI Assistant", "📊 Detailed Analytics"])

        with tab_chat:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]): st.markdown(msg["content"])

            if prompt := st.chat_input("Log expense (e.g., Spent $50 on Food)..."):
                st.chat_message("user").markdown(prompt)
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.spinner("Analyzing..."):
                    res = process_user_input(prompt, df)
                    if res and res.get("intent") == "log":
                        insert_transaction(res['amount'], res['category'], res['description'], username)
                        tag = " (AI)" if not res.get("is_fallback") else " (Fail-safe)"
                        msg = f"✅ **Logged successfully:** ${res['amount']} for {res['category']}{tag}"
                        st.session_state.messages.append({"role": "assistant", "content": msg})
                        st.rerun()
                    elif res and res.get("intent") == "chat":
                        reply = res.get("chat_reply", "Processed.")
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})

        with tab_data:
            if not df.empty:
                # Plotly 互動式圖表
                fig = px.pie(df, values='amount', names='category', hole=0.4, title="Spending Distribution")
                st.plotly_chart(fig, use_container_width=True)
                # 歷史數據表格
                st.subheader("Transaction History")
                st.dataframe(df, use_container_width=True)
                # 一鍵匯出 CSV
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download Data (CSV)", csv, f"fin_report_{username}.csv", "text/csv")
            else:
                st.warning("No data found. Start logging in the Chat tab!")

if __name__ == "__main__":
    main()
