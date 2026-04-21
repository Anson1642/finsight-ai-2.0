import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
import time
from google import genai

# ==========================================
# 1. CONFIGURATION (STRICT SECRETS)
# ==========================================
# 確保你在 Streamlit Settings -> Secrets 裡有設定 GOOGLE_API_KEY
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
# 3. REAL AI ENGINE (No more silent fails)
# ==========================================
def process_user_input(user_text, df):
    if not MY_API_KEY:
        return {"intent": "chat", "chat_reply": "❌ Error: API Key not found in Secrets. Check your settings!"}

    try:
        client = genai.Client(api_key=MY_API_KEY)
        history = df.tail(10).to_string(index=False) if not df.empty else "No history."
        
        prompt = f"""You are a professional AI Finance Assistant.
        User Transaction History: {history}
        Current Input: "{user_text}"
        
        Task: 
        1. If logging a new expense: Return JSON {{"intent": "log", "amount": 100.0, "category": "Food/Transport/Housing/Others", "description": "text"}}
        2. If asking a question: Return JSON {{"intent": "chat", "chat_reply": "Your intelligent answer based on history"}}
        
        Respond ONLY with JSON. No markdown."""

        # 這裡換成最穩定的 1.5 Flash
        response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
        
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        else:
            return {"intent": "chat", "chat_reply": f"🤖 AI Response Error: AI didn't return JSON. Raw output: {response.text[:100]}"}

    except Exception as e:
        # 如果出錯，直接印出錯誤碼
        return {"intent": "chat", "chat_reply": f"❌ API Connection Failed: {str(e)}"}

# ==========================================
# 4. MAIN UI
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide")
    init_db()

    if "logged_in" not in st.session_state: 
        st.session_state.update({"logged_in": False, "username": None, "messages": []})
    
    if not st.session_state.logged_in:
        st.title("💰 FinSight AI - Access")
        choice = st.selectbox("Action", ["Login", "Signup"])
        u = st.text_input("Username")
        p = st.text_input("Password", type='password')
        if st.button("Enter"):
            if choice == "Signup":
                conn = sqlite3.connect(DB_NAME); c = conn.cursor()
                try:
                    c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (u, make_hashes(p)))
                    conn.commit(); st.success("Account created!")
                except: st.error("Username taken.")
                conn.close()
            elif u and p:
                conn = sqlite3.connect(DB_NAME); c = conn.cursor()
                c.execute("SELECT password FROM users WHERE username = ?", (u,))
                data = c.fetchone()
                conn.close()
                if data and make_hashes(p) == data[0]:
                    st.session_state.update({"logged_in": True, "username": u})
                    st.rerun()
                else: st.error("Wrong credentials.")
    else:
        username = st.session_state.username
        with st.sidebar:
            st.title(f"Hi, {username}!")
            df = get_user_transactions(username)
            if not df.empty:
                st.subheader("📊 Spending")
                st.bar_chart(df.groupby('category')['amount'].sum())
                st.download_button("Export CSV", df.to_csv(index=False).encode('utf-8'), "data.csv")
            if st.button("Logout"):
                st.session_state.update({"logged_in": False, "messages": []}); st.rerun()

        st.title("💰 FinSight AI Assistant")
        # 顯示歷史紀錄
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if user_text := st.chat_input("Tell me your expense..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            with st.spinner("AI is analyzing..."):
                res = process_user_input(user_text, df)
                
                if res:
                    if res.get("intent") == "log":
                        insert_transaction(res['amount'], res['category'], res['description'], username)
                        reply = f"✅ **Logged:** ${res['amount']} for {res['category']}"
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                        st.rerun() # 自動刷新圖表
                    elif res.get("intent") == "chat":
                        reply = res.get("chat_reply")
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                else:
                    st.error("System Error.")

if __name__ == "__main__":
    main()
