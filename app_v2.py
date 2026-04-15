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
MY_API_KEY = "AIzaSyB3-kbbqZfyvtP3ioHmbMAOwBcIC33oA0E"
DB_NAME = "finance.db"

def make_hashes(password): return hashlib.sha256(str.encode(password)).hexdigest()

# ==========================================
# 2. DATABASE FUNCTIONS
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, category TEXT, description TEXT, username TEXT)''')
    c.execute("PRAGMA table_info(transactions)")
    columns = [info[1] for info in c.fetchall()]
    if 'username' not in columns: c.execute("ALTER TABLE transactions ADD COLUMN username TEXT")
    conn.commit(); conn.close()

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
    if data and make_hashes(password) == data[0]: return True
    return False

def insert_transaction(amount, category, description, username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (amount, category, description, username) VALUES (?, ?, ?, ?)", (amount, category, description, username))
    conn.commit(); conn.close()

def get_user_transactions(username):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM transactions WHERE username = ?", conn, params=(username,))
    conn.close()
    return df

# ==========================================
# 3. AI LOGIC ENGINE
# ==========================================
def process_user_input(user_text, df):
    client = genai.Client(api_key=MY_API_KEY)
    history_text = df.tail(15).to_string() if not df.empty else "No previous transactions."
    
    prompt = f"""You are a professional AI Finance Assistant.
    Transaction History: {history_text}
    User Input: "{user_text}"
    
    Task: Analyze the input and return STRICTLY valid JSON.
    - If user is logging a new expense: {{"intent": "log", "amount": 0.0, "category": "Food/Transport/Housing/Entertainment/Others", "description": "text"}}
    - If user is asking a question or analyzing data: {{"intent": "chat", "chat_reply": "Your advice/answer here"}}
    No markdown blocks."""
    
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except: return None

# ==========================================
# 4. MAIN UI (STREAMLIT)
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide")
    init_db()

    # Session Management
    if "logged_in" not in st.session_state: st.session_state.update({"logged_in": False, "username": None, "messages": []})

    if not st.session_state.logged_in:
        st.title("💰 FinSight AI - Login")
        choice = st.selectbox("Action", ["Login", "Signup"])
        user = st.text_input("Username")
        pwd = st.text_input("Password", type='password')
        if st.button("Enter"):
            if choice == "Signup" and add_user(user, pwd): st.success("Created! Please Login.")
            elif choice == "Login" and login_user(user, pwd):
                st.session_state.update({"logged_in": True, "username": user})
                st.rerun()
            else: st.error("Invalid credentials.")
    else:
        username = st.session_state.username
        st.sidebar.title(f"Hi, {username}!")
        if st.sidebar.button("Logout"): st.session_state.update({"logged_in": False, "messages": []}); st.rerun()
        
        df = get_user_transactions(username)
        with st.sidebar:
            st.subheader("📊 Analytics")
            if not df.empty: st.bar_chart(df.groupby('category')['amount'].sum())
        
        st.title("💰 FinSight AI Assistant")
        # 顯示歷史訊息
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        # 處理訊息輸入
        if user_text := st.chat_input("Log expense or ask question..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            with st.spinner("Processing..."):
                res = process_user_input(user_text, df)
                if res and res.get("intent") == "log":
                    insert_transaction(res['amount'], res['category'], res['description'], username)
                    reply = f"✅ Logged ${res['amount']} for {res['category']}"
                    st.chat_message("assistant").markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                    st.rerun()
                elif res and res.get("intent") == "chat":
                    reply = res.get("chat_reply")
                    st.chat_message("assistant").markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                else:
                    st.error("AI couldn't process this.")

if __name__ == "__main__":
    main()
