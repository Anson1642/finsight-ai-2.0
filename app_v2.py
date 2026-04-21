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
# 1. CONFIGURATION & CUSTOM CSS (FULL VERSION)
# ==========================================
# 優先讀取 Streamlit Cloud 的 Secrets，若無則使用代碼中的硬編碼 Key
if "GOOGLE_API_KEY" in st.secrets:
    MY_API_KEY = st.secrets["GOOGLE_API_KEY"]
else:
    MY_API_KEY = "AIzaSyBwzvW898kUFdaLfy7cZxNoTZ4ESfu6qnw" # 你的 Key

DB_NAME = "finance.db"

def apply_custom_style():
    """加載自定義 CSS，美化按鈕、背景與字體"""
    st.markdown("""
        <style>
        .main { background-color: #f8f9fa; }
        div.stButton > button:first-child {
            border-radius: 10px;
            height: 3em;
            width: 100%;
            border: 1px solid #007bff;
            background-color: white;
            color: #007bff;
            font-weight: bold;
            transition: 0.3s;
        }
        div.stButton > button:hover {
            background-color: #007bff;
            color: white;
        }
        [data-testid="stMetricValue"] { font-size: 1.8rem; color: #1f1f1f; }
        [data-testid="stMetricLabel"] { font-size: 1rem; color: #666; }
        .stChatMessage {
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            border-radius: 15px;
            margin-bottom: 10px;
        }
        </style>
    """, unsafe_allow_html=True)

def make_hashes(password):
    """密碼雜湊處理 (SHA-256)"""
    return hashlib.sha256(str.encode(password)).hexdigest()

# ==========================================
# 2. DATABASE FUNCTIONS (User-Scoped & Migration)
# ==========================================
def init_db():
    """初始化資料庫並執行自動遷移"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, category TEXT, description TEXT, username TEXT)')
    
    # 自動補上 username 欄位 (防止舊版資料庫報錯)
    c.execute("PRAGMA table_info(transactions)")
    columns = [info[1] for info in c.fetchall()]
    if 'username' not in columns:
        c.execute("ALTER TABLE transactions ADD COLUMN username TEXT")
    
    conn.commit()
    conn.close()

def add_user(username, password):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, make_hashes(password)))
        conn.commit(); return True
    except: return False
    finally: conn.close()

def login_user(username, password):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("SELECT password FROM users WHERE username = ?", (username,))
    data = c.fetchone()
    conn.close()
    return data and make_hashes(password) == data[0]

def insert_transaction(amount, category, description, username):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("INSERT INTO transactions (amount, category, description, username) VALUES (?, ?, ?, ?)", (amount, category, description, username))
    conn.commit(); conn.close()

def get_user_transactions(username):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT amount, category, description FROM transactions WHERE username = ?", conn, params=(username,))
    conn.close()
    return df

def clear_user_data(username):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE username = ?", (username,))
    conn.commit(); conn.close()

# ==========================================
# 3. AI LOGIC ENGINE (With Hybrid Local Filtering)
# ==========================================
def process_user_input(user_text, df):
    # 優化 1：本地過濾打招呼，節省 API 額度
    greetings = ["hi", "hello", "你好", "hey", "thanks", "謝謝", "早上好", "晚安"]
    if user_text.lower().strip() in greetings:
        return {"intent": "chat", "chat_reply": "Hello! I'm your AI finance assistant. I'm ready to log your expenses or analyze your spending history."}

    if not MY_API_KEY: return None
    
    try:
        client = genai.Client(api_key=MY_API_KEY)
        # 提供歷史資料給 AI 進行 RAG 分析
        history = df.tail(15).to_string(index=False) if not df.empty else "No transactions logged yet."
        
        prompt = f"""You are 'FinSight AI', a professional finance assistant.
        Transaction History: {history}
        User Input: "{user_text}"
        
        Task: Analyze intent and return STRICT JSON ONLY.
        If Logging: {{"intent": "log", "amount": 100.0, "category": "Food/Transport/Housing/Entertainment/Others", "description": "text"}}
        If Question: {{"intent": "chat", "chat_reply": "your advice based on history"}}
        No markdown, no conversation outside JSON.
        """
        
        time.sleep(1.5) # 頻率限制防禦
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        
        # 使用正則強行提取 JSON，防止 AI 回傳額外文字導致解析失敗
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
        
    except Exception as e:
        if "429" in str(e): return {"intent": "chat", "chat_reply": "⚠️ API limit reached. Please wait 10 seconds or use the Quick View analysis."}
        return None

# ==========================================
# 4. MAIN APPLICATION UI
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide", page_icon="💰")
    apply_custom_style()
    init_db()

    if "logged_in" not in st.session_state: 
        st.session_state.update({"logged_in": False, "username": None, "messages": []})

    # --- 登入/註冊頁面 ---
    if not st.session_state.logged_in:
        st.markdown("<h1 style='text-align: center;'>💰 FinSight Pro</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: grey;'>The Smartest AI Personal Finance Tool</p>", unsafe_allow_html=True)
        
        col_l, col_m, col_r = st.columns([1, 2, 1])
        with col_m:
            choice = st.radio("Action", ["Login", "Signup"], horizontal=True)
            u = st.text_input("Username")
            p = st.text_input("Password", type='password')
            if st.button("Enter Dashboard"):
                if choice == "Signup":
                    if add_user(u, p): st.success("Account created! Please Login.")
                    else: st.error("Account creation failed (User might exist).")
                elif u and p:
                    if login_user(u, p):
                        st.session_state.update({"logged_in": True, "username": u})
                        st.rerun()
                    else: st.error("Access denied. Please check your credentials.")
    
    # --- 已登入主介面 ---
    else:
        username = st.session_state.username
        df = get_user_transactions(username)

        # 側邊欄：快速分析與管理
        with st.sidebar:
            st.image("https://cdn-icons-png.flaticon.com/512/1611/1611179.png", width=70)
            st.title(f"Hi, {username}!")
            
            st.subheader("⚡ Quick Insights (No API)")
            if not df.empty:
                st.info(f"Total Spent: ${df['amount'].sum():,.1f}")
                st.info(f"Top Category: {df.groupby('category')['amount'].sum().idxmax()}")
            
            st.divider()
            with st.expander("⚙️ Management"):
                if st.button("🗑️ Clear All Data"):
                    clear_user_data(username); st.session_state.messages = []; st.rerun()
                if st.button("Logout"): 
                    st.session_state.update({"logged_in": False, "username": None, "messages": []})
                    st.rerun()

        # 頂部核心指標指標
        st.title("💼 Financial Dashboard")
        m1, m2, m3 = st.columns(3)
        total_val = df['amount'].sum() if not df.empty else 0
        count_val = len(df)
        top_cat = df.groupby('category')['amount'].sum().idxmax() if not df.empty else "N/A"
        
        m1.metric("Total Expenses", f"${total_val:,.1f}")
        m2.metric("Records", count_val)
        m3.metric("Top Category", top_cat)

        st.divider()

        # 分頁系統：聊天 vs 數據報表
        tab_chat, tab_data = st.tabs(["💬 AI Assistant", "📊 Analytics & Export"])

        with tab_chat:
            # 顯示對話歷史紀錄
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]): st.markdown(msg["content"])

            if prompt := st.chat_input("Log an expense (e.g., Spent $20 on Pizza)..."):
                st.chat_message("user").markdown(prompt)
                st.session_state.messages.append({"role": "user", "content": prompt})
                
                with st.spinner("AI is analyzing..."):
                    res = process_user_input(prompt, df)
                    if res:
                        if res.get("intent") == "log" and res.get("amount") is not None:
                            insert_transaction(res['amount'], res['category'], res['description'], username)
                            msg = f"✅ **Logged successfully:** ${res['amount']} for {res['category']}"
                            st.session_state.messages.append({"role": "assistant", "content": msg})
                            st.rerun() # 自動重載更新頂部 Metric 與圖表
                        elif res.get("intent") == "chat":
                            reply = res.get("chat_reply", "I've analyzed your data.")
                            st.chat_message("assistant").markdown(reply)
                            st.session_state.messages.append({"role": "assistant", "content": reply})
                    else: st.error("AI service is currently busy. Try again or use Quick Insights.")

        with tab_data:
            if not df.empty:
                # 互動式 Plotly 圓餅圖
                fig = px.pie(df, values='amount', names='category', hole=0.4,
                             title="Expense Distribution by Category",
                             color_discrete_sequence=px.colors.qualitative.Safe)
                st.plotly_chart(fig, use_container_width=True)
                
                st.divider()
                st.subheader("📝 Transaction History")
                st.dataframe(df, use_container_width=True)
                
                # CSV 下載按鈕
                csv_file = df.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download Financial Report (CSV)", csv_file, "fin_report.csv", "text/csv")
            else:
                st.warning("No data found. Start logging your expenses in the Chat tab!")

if __name__ == "__main__":
    main()
