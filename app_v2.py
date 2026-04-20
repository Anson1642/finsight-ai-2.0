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
    columns = [info[1] for info in c.fetchall()]
    if 'username' not in columns:
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
# 3. FAIL-SAFE LOGIC (保底解析)
# ==========================================
def heuristic_parse(text):
    # 找數字
    numbers = re.findall(r'\d+', text)
    amount = float(numbers[0]) if numbers else 0.0
    # 找分類關鍵字
    category = "Others"
    t = text.lower()
    if any(k in t for k in ["food", "eat", "lunch", "cafe"]): category = "Food"
    elif any(k in t for k in ["bus", "taxi", "gas", "uber"]): category = "Transport"
    elif any(k in t for k in ["rent", "home", "housing"]): category = "Housing"
    return {"intent": "log", "amount": amount, "category": category, "description": text, "is_fallback": True}

# ==========================================
# 4. AI ENGINE (With Throttling)
# ==========================================
def process_user_input(user_text, df):
    if not MY_API_KEY: return heuristic_parse(user_text)
    client = genai.Client(api_key=MY_API_KEY)
    history = df.tail(5).to_string(index=False) if not df.empty else "None"
    prompt = f"Analyze: {user_text}. History: {history}. Return JSON: {{'intent': 'log', 'amount': 0.0, 'category': '...', 'description': '...'}} or {{'intent': 'chat', 'chat_reply': '...'}}"
    
    try:
        time.sleep(1)
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match: return json.loads(match.group(0))
    except:
        pass
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
                    conn.commit(); st.success("Created!")
                except: st.error("Exists!")
                conn.close()
            elif u and p: # Login check
                conn = sqlite3.connect(DB_NAME); c = conn.cursor()
                c.execute("SELECT password FROM users WHERE username = ?", (u,))
                data = c.fetchone()
                conn.close()
                if data and make_hashes(p) == data[0]:
                    st.session_state.update({"logged_in": True, "username": u})
                    st.rerun()
                else: st.error("Wrong password")
    else:
        # 已登入介面
        username = st.session_state.username
        with st.sidebar:
            st.title(f"Hi, {username}!")
            df = get_user_transactions(username)
            if not df.empty:
                st.bar_chart(df.groupby('category')['amount'].sum())
                st.download_button("Download CSV", df.to_csv(index=False).encode('utf-8'), "data.csv")
            if st.button("Logout"):
                st.session_state.update({"logged_in": False, "messages": []}); st.rerun()

        st.title("💰 AI Finance Assistant")
        # 顯示訊息 (修復縮排報錯的地方)
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if user_text := st.chat_input("Spent $50 on food..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            with st.spinner("Processing..."):
                res = process_user_input(user_text, df)
                if res and res.get("intent") == "log":
                    insert_transaction(res['amount'], res['category'], res['description'], username)
                    status = "(AI)" if not res.get("is_fallback") else "(Fail-safe)"
                    reply = f"✅ **Logged:** ${res['amount']} for {res['category']} {status}"
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                    st.rerun()
                elif res:
                    reply = res.get("chat_reply", "Processed.")
                    st.chat_message("assistant").markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply})

if __name__ == "__main__":
    main()
