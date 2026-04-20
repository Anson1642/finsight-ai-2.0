import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
import time
from google import genai

# ==========================================
# 1. CONFIGURATION & SECURITY (Only st.secrets)
# ==========================================
# 嚴格只從 Streamlit Cloud 的 Secrets 讀取
# 介面位置：Manage App -> Settings -> Secrets
# 格式：GOOGLE_API_KEY = "你的KEY"
MY_API_KEY = st.secrets.get("GOOGLE_API_KEY")

DB_NAME = "finance.db"

def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

# ==========================================
# 2. DATABASE FUNCTIONS
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, category TEXT, description TEXT, username TEXT)''')
    
    # 自動偵測並修正資料庫欄位 (Migration)
    c.execute("PRAGMA table_info(transactions)")
    columns = [info[1] for info in c.fetchall()]
    if 'username' not in columns:
        c.execute("ALTER TABLE transactions ADD COLUMN username TEXT")
    
    conn.commit()
    conn.close()

def add_user(username, password):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, make_hashes(password)))
        conn.commit(); return True
    except: return False
    finally: conn.close()

def login_user(username, password):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT password FROM users WHERE username = ?", (username,))
    data = c.fetchone()
    conn.close()
    return data and make_hashes(password) == data[0]

def insert_transaction(amount, category, description, username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (amount, category, description, username) VALUES (?, ?, ?, ?)", (amount, category, description, username))
    conn.commit(); conn.close()

def get_user_transactions(username):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT amount, category, description FROM transactions WHERE username = ?", conn, params=(username,))
    conn.close()
    return df

# ==========================================
# 3. AI LOGIC ENGINE (Gemini 2.0 Flash)
# ==========================================
def process_user_input(user_text, df):
    if not MY_API_KEY:
        return {"intent": "chat", "chat_reply": "❌ Error: GOOGLE_API_KEY not found in Secrets."}

    client = genai.Client(api_key=MY_API_KEY)
    history = df.tail(10).to_string(index=False) if not df.empty else "No history."
    
    prompt = f"""You are 'FinSight AI', a professional finance assistant.
    Transaction History: {history}
    User input: "{user_text}"
    
    Task: Analyze the input and return ONLY JSON.
    - If logging an expense: {{"intent": "log", "amount": 10.0, "category": "Food/Transport/Housing/Entertainment/Others", "description": "pizza"}}
    - If asking/chatting: {{"intent": "chat", "chat_reply": "your advice or answer based on data"}}
    No markdown blocks, no extra text.
    """
    try:
        # 強制加入少許延遲，防止 429 錯誤
        time.sleep(1)
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        # 用正則表達式提取 JSON，防止 AI 多廢話
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        if "429" in str(e):
            return {"intent": "chat", "chat_reply": "⚠️ API limit reached. Please wait 10 seconds and try again."}
        return None

# ==========================================
# 4. MAIN UI (STREAMLIT)
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide")
    init_db()

    # Session 管理
    if "logged_in" not in st.session_state: 
        st.session_state.update({"logged_in": False, "username": None, "messages": []})

    if not st.session_state.logged_in:
        st.title("💰 FinSight Pro - Login")
        choice = st.selectbox("Action", ["Login", "Signup"])
        u = st.text_input("Username")
        p = st.text_input("Password", type='password')
        if st.button("Enter"):
            if choice == "Signup" and add_user(u, p): st.success("Success! Please Login.")
            elif choice == "Login" and login_user(u, p):
                st.session_state.update({"logged_in": True, "username": u})
                st.rerun()
            else: st.error("Access denied.")
    else:
        username = st.session_state.username
        
        # --- SIDEBAR ---
        with st.sidebar:
            st.title(f"Welcome, {username}!")
            df = get_user_transactions(username)
            if not df.empty:
                st.subheader("📊 Analytics")
                st.bar_chart(df.groupby('category')['amount'].sum())
                # 下載 CSV 功能
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("Download CSV", csv, f"{username}_data.csv", "text/csv")
            
            st.divider()
            if st.button("Logout"):
                st.session_state.update({"logged_in": False, "username": None, "messages": []})
                st.rerun()

        # --- MAIN CHAT ---
        st.title("💰 AI Finance Assistant")
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if user_text := st.chat_input("Spent $50 on lunch..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            with st.spinner("Analyzing..."):
                res = pro
