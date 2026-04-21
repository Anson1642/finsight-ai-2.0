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
# 3. AI LOGIC ENGINE (With Local Greeting Filter)
# ==========================================
def process_user_input(user_text, df):
    # --- [優化 1] 本地過濾：減少 API 額度消耗 ---
    clean_input = user_text.lower().strip()
    greetings = ["hi", "hello", "你好", "hey", "早安", "午安", "晚安", "thanks", "謝謝"]
    
    if clean_input in greetings:
        return {"intent": "chat", "chat_reply": "Hello! I am your AI assistant. How can I help you manage your money today?"}

    if not MY_API_KEY:
        return {"intent": "chat", "chat_reply": "❌ Secrets Error: GOOGLE_API_KEY missing."}

    try:
        client = genai.Client(api_key=MY_API_KEY)
        history = df.tail(10).to_string(index=False) if not df.empty else "No history."
        prompt = f"Analyze: {user_text}. History: {history}. Return JSON ONLY: {{'intent': 'log', 'amount': 100, 'category': 'Food', 'description': 'lunch'}} or {{'intent': 'chat', 'chat_reply': 'advice'}}"
        
        time.sleep(1) # 防護性等待
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        if "429" in str(e):
            return {"intent": "chat", "chat_reply": "⚠️ API limit reached. Try again in 10s."}
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
        st.title("💰 FinSight AI - Login")
        choice = st.selectbox("Action", ["Login", "Signup"])
        u = st.text_input("Username")
        p = st.text_input("Password", type='password')
        if st.button("Enter"):
            if choice == "Signup":
                conn = sqlite3.connect(DB_NAME); c = conn.cursor()
                try:
                    c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (u, make_hashes(p)))
                    conn.commit(); st.success("Success! Please Login.")
                except: st.error("User exists.")
                conn.close()
            elif u and p:
                conn = sqlite3.connect(DB_NAME); c = conn.cursor()
                c.execute("SELECT password FROM users WHERE username = ?", (u,))
                data = c.fetchone()
                conn.close()
                if data and make_hashes(p) == data[0]:
                    st.session_state.update({"logged_in": True, "username": u})
                    st.rerun()
                else: st.error("Wrong info.")
    else:
        username = st.session_state.username
        
        # --- SIDEBAR (包含快速查詢功能) ---
        with st.sidebar:
            st.title(f"Hi, {username}!")
            df = get_user_transactions(username)
            
            # --- [優化 2] 快速查詢按鈕 (完全不消耗 API) ---
            st.subheader("⚡ Quick Analysis")
            if not df.empty:
                col1, col2 = st.columns(2)
                if col1.button("💰 Total"):
                    st.info(f"Total: ${df['amount'].sum():.1f}")
                if col2.button("🍕 Top"):
                    top_cat = df.groupby('category')['amount'].sum().idxmax()
                    st.info(f"Top: {top_cat}")
                
                st.divider()
                st.subheader("📊 Chart")
                st.bar_chart(df.groupby('category')['amount'].sum())
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("Download CSV", csv, "data.csv")
            else:
                st.write("No data yet.")

            st.divider()
            if st.button("Logout"):
                st.session_state.update({"logged_in": False, "username": None, "messages": []})
                st.rerun()

        # --- MAIN CHAT AREA ---
        st.title("💰 AI Finance Assistant")
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if user_text := st.chat_input("Spent $50 on lunch..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            with st.spinner("Processing..."):
                res = process_user_input(user_text, df)
                if res:
                    if res.get("intent") == "log" and res.get("amount") is not None:
                        insert_transaction(res['amount'], res['category'], res['description'], username)
                        msg = f"✅ **Logged:** ${res['amount']} for {res['category']}"
                        # 檢查是否為本地解析（未來擴展用，目前此版本全由AI處理記帳）
                        st.session_state.messages.append({"role": "assistant", "content": msg})
                        st.rerun()
                    elif res.get("intent") == "chat":
                        reply = res.get("chat_reply", "Processed.")
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                else:
                    st.error("AI Service Issue.")

if __name__ == "__main__":
    main()
