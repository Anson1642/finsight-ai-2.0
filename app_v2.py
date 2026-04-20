import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
import time
from google import genai

# ==========================================
# 1. CONFIGURATION & SECURITY
# ==========================================
# 優先讀取雲端 Secrets，否則使用硬編碼 Key
if "GOOGLE_API_KEY" in st.secrets:
    MY_API_KEY = st.secrets["GOOGLE_API_KEY"]
else:
    MY_API_KEY = "AIzaSyB3-kbbqZfyvtP3ioHmbMAOwBcIC33oA0E" # 這是你的 Key

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
# 3. AI ENGINE (Gemini 2.0 Flash - The Most Stable)
# ==========================================
def process_user_input(user_text, df):
    client = genai.Client(api_key=MY_API_KEY)
    history = df.tail(10).to_string(index=False) if not df.empty else "No records."
    
    prompt = f"""You are a professional Finance Assistant. 
    Analyze history: {history}
    User input: "{user_text}"
    Return JSON only:
    - Log: {{"intent": "log", "amount": 0.0, "category": "Food/Transport/Housing/Entertainment/Others", "description": "text"}}
    - Chat: {{"intent": "chat", "chat_reply": "your advice"}}
    """
    try:
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        if "429" in str(e): return {"intent": "chat", "chat_reply": "⚠️ API is busy. Please wait 10 seconds."}
        return None

# ==========================================
# 4. MAIN UI
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide")
    init_db()

    if "logged_in" not in st.session_state: 
        st.session_state.update({"logged_in": False, "username": None, "messages": []})
    
    if not st.session_state.logged_in:
        st.title("💰 FinSight Pro - Login")
        choice = st.selectbox("Action", ["Login", "Signup"])
        u = st.text_input("Username")
        p = st.text_input("Password", type='password')
        if st.button("Enter"):
            if choice == "Signup" and add_user(u, p): st.success("Created!")
            elif choice == "Login" and login_user(u, p):
                st.session_state.update({"logged_in": True, "username": u})
                st.rerun()
            else: st.error("Error.")
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
                st.session_state.update({"logged_in": False, "username": None, "messages": []}); st.rerun()

        st.title("💰 AI Finance Assistant")
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if user_text := st.chat_input("Spent $50 on lunch..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            with st.spinner("AI is thinking..."):
                res = process_user_input(user_text, df)
                if res:
                    if res.get("intent") == "log" and res.get("amount") is not None:
                        insert_transaction(res['amount'], res['category'], res['description'], username)
                        reply = f"✅ Logged: ${res['amount']} for {res['category']}"
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                        st.rerun()
                    elif res.get("intent") == "chat":
                        reply = res.get("chat_reply", "Processed.")
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                else:
                    st.error("AI service error.")

if __name__ == "__main__":
    main()
