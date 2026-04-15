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
MY_API_KEY = "AIzaSyBOWAqxkAKxBBNkUy2-Fck_PkTqZlL6gIQ"
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
    conn.commit(); conn.close()

def insert_transaction(amount, category, description, username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (amount, category, description, username) VALUES (?, ?, ?, ?)", 
              (amount, category, description, username))
    conn.commit(); conn.close()

def get_user_transactions(username):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM transactions WHERE username = ?", conn, params=(username,))
    conn.close()
    return df

def clear_user_data(username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE username = ?", (username,))
    conn.commit(); conn.close()

# ==========================================
# 3. AI LOGIC ENGINE
# ==========================================
def process_user_input(user_text, df):
    # 強制等待 2 秒，避免觸發 Google API 429 錯誤
    time.sleep(2)
    
    client = genai.Client(api_key=MY_API_KEY)
    history_text = df.tail(10).to_string() if not df.empty else "No transactions."
    
    prompt = f"""You are FinSight AI. History: {history_text}. User Input: "{user_text}".
    Return STRICTLY valid JSON.
    If log expense: {{"intent": "log", "amount": <num>, "category": "<Food/Transport/Housing/Entertainment/Others>", "description": "<text>"}}
    If chat/question: {{"intent": "chat", "chat_reply": "<answer>"}}
    No markdown blocks."""
    
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        return {"intent": "chat", "chat_reply": f"AI Error: {str(e)}"}

# ==========================================
# 4. STREAMLIT UI
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide")
    init_db()

    if "logged_in" not in st.session_state: st.session_state.update({"logged_in": False, "username": None})
    if "last_input" not in st.session_state: st.session_state.last_input = ""

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
            if not df.empty: st.bar_chart(df.groupby('category')['amount'].sum())
            if st.button("🗑️ Clear My Data"): clear_user_data(username); st.rerun()

        st.title("💰 FinSight AI Assistant")
        if "messages" not in st.session_state: st.session_state.messages = []
        for msg in st.session_state.messages: st.chat_message(msg["role"]).markdown(msg["content"])

        if user_text := st.chat_input("Log expense or ask question..."):
            # 防抖動檢查：防止重複觸發
            if st.session_state.last_input != user_text:
                st.session_state.last_input = user_text
                st.chat_message("user").markdown(user_text)
                st.session_state.messages.append({"role": "user", "content": user_text})
                
                with st.spinner("Analyzing..."):
                    res = process_user_input(user_text, df)
                    if res and res.get("intent") == "log":
                        insert_transaction(res['amount'], res['category'], res['description'], username)
                        st.rerun()
                    elif res and res.get("intent") == "chat":
                        reply = res.get("chat_reply")
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})

if __name__ == "__main__":
    main()
