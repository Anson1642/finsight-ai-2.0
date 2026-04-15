
import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
from google import genai

# ==========================================
# 1. CONFIGURATION & SECURITY
# ==========================================
# 優先讀取 Streamlit Cloud 的 Secrets，若無則使用代碼中的 Key
if "GOOGLE_API_KEY" in st.secrets:
    MY_API_KEY = st.secrets["GOOGLE_API_KEY"]
else:
    MY_API_KEY = "AIzaSyBwzvW898kUFdaLfy7cZxNoTZ4ESfu6qnw"

DB_NAME = "finance.db"

def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

# ==========================================
# 2. DATABASE FUNCTIONS (Robust Migration)
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # 建立 users 表
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
    # 建立 transactions 表
    c.execute('''CREATE TABLE IF NOT EXISTS transactions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, category TEXT, description TEXT, username TEXT)''')
    
    # 檢查並自動補上 username 欄位
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
        conn.commit()
        return True
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
    c.execute("INSERT INTO transactions (amount, category, description, username) VALUES (?, ?, ?, ?)", 
              (amount, category, description, username))
    conn.commit()
    conn.close()

def get_user_transactions(username):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT amount, category, description FROM transactions WHERE username = ?", conn, params=(username,))
    conn.close()
    return df

def clear_user_data(username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE username = ?", (username,))
    conn.commit()
    conn.close()

# ==========================================
# 3. AI LOGIC ENGINE
# ==========================================
def process_user_input(user_text, df):
    client = genai.Client(api_key=MY_API_KEY)
    history_text = df.to_string(index=False) if not df.empty else "No transactions."
    
    prompt = f"""You are a professional AI Finance Assistant.
    History: {history_text}. User Input: "{user_text}".
    Return STRICTLY valid JSON.
    If log: {{"intent": "log", "amount": <num>, "category": "<word>", "description": "<text>"}}
    If chat: {{"intent": "chat", "chat_reply": "<answer>"}}
    No markdown blocks."""
    
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except: return None

# ==========================================
# 4. STREAMLIT UI
# ==========================================
def main():
    st.set_page_config(page_title="FinSight AI", page_icon="💰", layout="wide")
    init_db()

    if "logged_in" not in st.session_state:
        st.session_state.update({"logged_in": False, "username": None})

    if not st.session_state.logged_in:
        st.title("💰 FinSight AI - Login")
        choice = st.selectbox("Action", ["Login", "Signup"])
        user = st.text_input("Username")
        pwd = st.text_input("Password", type='password')
        if st.button("Enter"):
            if choice == "Signup" and add_user(user, pwd): st.success("Created!")
            elif choice == "Login" and login_user(user, pwd):
                st.session_state.update({"logged_in": True, "username": user})
                st.rerun()
            else: st.error("Login failed / User exists")
    else:
        username = st.session_state.username
        st.sidebar.button("Logout", on_click=lambda: st.session_state.update({"logged_in": False, "messages": []}))
        
        df = get_user_transactions(username)
        
        with st.sidebar:
            st.title(f"Hi, {username}!")
            if not df.empty:
                st.bar_chart(df.groupby('category')['amount'].sum())
            if st.button("🗑️ Clear My Data"):
                clear_user_data(username); st.rerun()

        st.title("💰 FinSight AI Assistant")
        if "messages" not in st.session_state: st.session_state.messages = []
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if user_text := st.chat_input("Log expense or ask question..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            result = process_user_input(user_text, df)
            if result and result.get("intent") == "log":
                insert_transaction(result["amount"], result["category"], result["description"], username)
                st.rerun()
            elif result and result.get("intent") == "chat":
                reply = result.get("chat_reply")
                st.chat_message("assistant").markdown(reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})

if __name__ == "__main__":
    main()
