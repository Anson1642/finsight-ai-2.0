import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
from google import genai
import time

# ==========================================
# 1. CONFIG & SECURITY
# ==========================================
# 在 Streamlit Cloud 的 Secrets 設定 GOOGLE_API_KEY
if "GOOGLE_API_KEY" in st.secrets:
    MY_API_KEY = st.secrets["GOOGLE_API_KEY"]
else:
    MY_API_KEY = "AIzaSyBOWAqxkAKxBBNkUy2-Fck_PkTqZlL6gIQ" # 本地測試用

DB_NAME = "finance.db"

# ==========================================
# 2. DATABASE FUNCTIONS
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, category TEXT, description TEXT, username TEXT)''')
    conn.commit(); conn.close()

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
# 3. AI LOGIC ENGINE (Using Gemini 2.0 Flash)
# ==========================================
def process_user_input(user_text, df):
    client = genai.Client(api_key=MY_API_KEY)
    history = df.tail(10).to_string()
    prompt = f"""You are FinSight AI. Analyze user input: "{user_text}".
    History: {history}.
    Task: Respond with JSON only.
    If log: {{"intent": "log", "amount": 0, "category": "Food", "description": "text"}}
    If chat: {{"intent": "chat", "chat_reply": "response"}}"""
    
    try:
        # 切換到 2.0 模型
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        # 捕捉 429 錯誤
        if "429" in str(e):
            return {"intent": "chat", "chat_reply": "⚠️ API limit reached. Please wait a moment or try again later."}
        return None

# ==========================================
# 4. STREAMLIT UI
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide")
    init_db()

    if "logged_in" not in st.session_state: st.session_state.update({"logged_in": False, "username": None})

    if not st.session_state.logged_in:
        st.title("💰 FinSight AI - Login")
        user = st.text_input("Username")
        pwd = st.text_input("Password", type='password')
        if st.button("Enter"):
            st.session_state.update({"logged_in": True, "username": user})
            st.rerun()
    else:
        username = st.session_state.username
        st.sidebar.title(f"Hi, {username}!")
        if st.sidebar.button("Logout"): st.session_state.update({"logged_in": False, "messages": []}); st.rerun()
        
        df = get_user_transactions(username)
        
        with st.sidebar:
            st.subheader("Spending Chart")
            if not df.empty: st.bar_chart(df.groupby('category')['amount'].sum())

        st.title("💰 FinSight AI Assistant")
        if "messages" not in st.session_state: st.session_state.messages = []
        for msg in st.session_state.messages: st.chat_message(msg["role"]).markdown(msg["content"])

        if user_text := st.chat_input("Log expense or ask question..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            res = process_user_input(user_text, df)
            if res and res.get("intent") == "log":
                insert_transaction(res['amount'], res['category'], res['description'], username)
                st.rerun()
            elif res and res.get("intent") == "chat":
                st.chat_message("assistant").markdown(res['chat_reply'])
                st.session_state.messages.append({"role": "assistant", "content": res['chat_reply']})
            else:
                st.error("AI connection issue (Rate limit reached?).")

if __name__ == "__main__":
    main()

    
