import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
import time
from google import genai

# ==========================================
# 1. CONFIG & SECURITY
# ==========================================
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
    c.execute("PRAGMA table_info(transactions)")
    if 'username' not in [info[1] for info in c.fetchall()]:
        c.execute("ALTER TABLE transactions ADD COLUMN username TEXT")
    conn.commit(); conn.close()

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
# 3. FAIL-SAFE LOGIC (本地保底解析器)
# ==========================================
def heuristic_parse(text):
    """如果 AI 掛掉，用這個 Python 邏輯保底記帳"""
    # 找數字
    numbers = re.findall(r'\d+', text)
    amount = float(numbers[0]) if numbers else 0.0
    
    # 找分類關鍵字
    category = "Others"
    text_lower = text.lower()
    if any(k in text_lower for k in ["food", "eat", "lunch", "dinner", "cafe"]): category = "Food"
    elif any(k in text_lower for k in ["bus", "taxi", "uber", "gas", "train", "transport"]): category = "Transport"
    elif any(k in text_lower for k in ["rent", "home", "housing", "water", "power"]): category = "Housing"
    elif any(k in text_lower for k in ["movie", "game", "spotify", "netflix", "fun"]): category = "Entertainment"
    
    return {"intent": "log", "amount": amount, "category": category, "description": text, "is_fallback": True}

# ==========================================
# 4. AI LOGIC ENGINE (With Auto-Retry)
# ==========================================
def process_user_input(user_text, df):
    if not MY_API_KEY:
        return heuristic_parse(user_text)

    client = genai.Client(api_key=MY_API_KEY)
    history = df.tail(5).to_string(index=False) if not df.empty else "No records."
    prompt = f"Analyze: {user_text}. History: {history}. Standard Cats: Food, Transport, Housing, Entertainment, Others. Return JSON only: {{'intent': 'log', 'amount': 0.0, 'category': '...', 'description': '...'}} or {{'intent': 'chat', 'chat_reply': '...'}}"

    # 嘗試呼叫 API，最多重試 2 次
    for attempt in range(2):
        try:
            time.sleep(1) # 基礎等待
            response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match: return json.loads(match.group(0))
        except Exception as e:
            if "429" in str(e):
                time.sleep(3) # 遇到 429，多等 3 秒
                continue
    
    # 如果重試都失敗了，啟動保底模式
    return heuristic_parse(user_text)

# ==========================================
# 5. MAIN UI
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide")
    init_db()

    if "logged_in" not in st.session_state: 
        st.session_state.update({"logged_in": False, "username": None, "messages": []})
    
    if not st.session_state.logged_in:
        st.title("💰 FinSight Pro Access")
        choice = st.selectbox("Action", ["Login", "Signup"])
        u = st.text_input("Username")
        p = st.text_input("Password", type='password')
        if st.button("Enter"):
            if choice == "Signup":
                conn = sqlite3.connect(DB_NAME); c = conn.cursor()
                try:
                    c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (u, make_hashes(p)))
                    conn.commit(); st.success("Account created!")
                except: st.error("Exists!")
                conn.close()
            elif login_user(u, p):
                st.session_state.update({"logged_in": True, "username": u})
                st.rerun()
    else:
        username = st.session_state.username
        with st.sidebar:
            st.title(f"Hi, {username}!")
            df = get_user_transactions(username)
            if not df.empty:
                st.subheader("📊 Analytics")
                st.bar_chart(df.groupby('category')['amount'].sum())
                st.download_button("Download CSV", df.to_csv(index=False).encode('utf-8'), "data.csv")
            if st.button("Logout"):
                st.session_state.update({"logged_in": False, "messages": []}); st.rerun()

        st.title("💰 AI Finance Assistant")
        for msg in st.session_state.messages:
