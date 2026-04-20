import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
import time
from google import genai

# ==========================================
# 1. 安全讀取 SECRETS (防止白畫面)
# ==========================================
def get_api_key():
    # 這是最安全的讀取方式，如果找不到 Key，網頁不會崩潰，會顯示警告
    try:
        if "GOOGLE_API_KEY" in st.secrets:
            return st.secrets["GOOGLE_API_KEY"]
        return None
    except:
        return None

MY_API_KEY = get_api_key()
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
    
    # 自動補欄位 (Migration)
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
    c.execute("INSERT INTO transactions (amount, category, description, username) VALUES (?, ?, ?, ?)", 
              (amount, category, description, username))
    conn.commit(); conn.close()

def get_user_transactions(username):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT amount, category, description FROM transactions WHERE username = ?", conn, params=(username,))
    conn.close()
    return df

# ==========================================
# 3. AI LOGIC (Gemini 2.0 Flash)
# ==========================================
def process_user_input(user_text, df):
    if not MY_API_KEY:
        return {"intent": "chat", "chat_reply": "❌ Please set GOOGLE_API_KEY in Streamlit Secrets!"}

    try:
        client = genai.Client(api_key=MY_API_KEY)
        history = df.tail(10).to_string(index=False) if not df.empty else "No history."
        
        prompt = f"""You are FinSight AI. History: {history}. User Input: "{user_text}".
        Return JSON only:
        - Log: {{"intent": "log", "amount": 0.0, "category": "Food/Transport/Housing/Others", "description": "text"}}
        - Chat: {{"intent": "chat", "chat_reply": "your advice"}}
        """
        # 強制等待 1 秒緩解頻率限制
        time.sleep(1)
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        if "429" in str(e): return {"intent": "chat", "chat_reply": "⚠️ API busy, wait 10s."}
        return None

# ==========================================
# 4. MAIN UI
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide")
    init_db()

    # 初始化狀態
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # 登入介面
    if not st.session_state.logged_in:
        st.title("💰 FinSight Pro Access")
        choice = st.selectbox("Action", ["Login", "Signup"])
        u = st.text_input("Username")
        p = st.text_input("Password", type='password')
        if st.button("Enter"):
            if choice == "Signup" and add_user(u, p): st.success("Created! Login now.")
            elif choice == "Login" and login_user(u, p):
                st.session_state.logged_in = True
                st.session_state.username = u
                st.rerun()
            else: st.error("Access Denied.")
    
    # 主程式介面
    else:
        username = st.session_state.username
        
        with st.sidebar:
            st.title(f"Hi, {username}!")
            df = get_user_transactions(username)
            if not df.empty:
                st.subheader("📊 Analytics")
                st.bar_chart(df.groupby('category')['amount'].sum())
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("Download CSV", csv, "data.csv")
            if st.button("Logout"):
                st.session_state.logged_in = False
                st.rerun()

        st.title("💰 AI Finance Assistant")
        # 顯示訊息
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if user_text := st.chat_input("Spent $100 on Food..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            with st.spinner("Analyzing..."):
                res = process_user_input(user_text, df)
                if res:
                    if res.get("intent") == "log":
                        insert_transaction(res['amount'], res['category'], res['description'], username)
                        reply = f"✅ Logged ${res['amount']} for {res['category']}"
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                        st.rerun()
                    elif res.get("intent") == "chat":
                        reply = res.get("chat_reply", "Processed.")
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                else:
                    st.error("AI Service Error.")

if __name__ == "__main__":
    main()
