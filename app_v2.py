import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
import time
import os

# --- 官方最新套件 ---
from langchain_huggingface import HuggingFaceEndpoint
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import JsonOutputParser

# ==========================================
# 1. CONFIGURATION & SECURITY
# ==========================================
HF_API_TOKEN = st.secrets.get("HUGGINGFACEHUB_API_TOKEN")

# 更換為 Zephyr 模型：這是目前與 LangChain 兼容性最高、最穩定的開源模型
OPEN_SOURCE_LLM_MODEL = "HuggingFaceH4/zephyr-7b-beta" 
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
    if data and make_hashes(password) == data[0]: return True
    return False

def insert_transaction(amount, category, description, username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (amount, category, description, username) VALUES (?, ?, ?, ?)", (amount, category, description, username))
    conn.commit(); conn.close()

def get_user_transactions(username):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT id, amount, category, description FROM transactions WHERE username = ?", conn, params=(username,))
    conn.close()
    return df

# ==========================================
# 3. AI LOGIC ENGINE (The Most Stable Version)
# ==========================================
@st.cache_resource
def get_llm_model_hf():
    if not HF_API_TOKEN:
        st.error("Secrets missing: HUGGINGFACEHUB_API_TOKEN")
        return None
    try:
        # 強制指定 task="text-generation" 避開伺服器分類錯誤
        return HuggingFaceEndpoint(
            repo_id=OPEN_SOURCE_LLM_MODEL,
            huggingfacehub_api_token=HF_API_TOKEN,
            task="text-generation", 
            temperature=0.1,
            max_new_tokens=250,
        )
    except Exception as e:
        st.error(f"Endpoint connection failed: {e}")
        return None

def process_user_input_with_hf(user_text, df):
    llm = get_llm_model_hf()
    if llm is None: return None

    history = df.tail(5).to_string(index=False) if not df.empty else "No records."
    
    # 針對 Zephyr 模型的最佳 Prompt 格式
    prompt = f"""<|system|>
You are a Finance Assistant. Only output JSON.
History: {history}
<|user|>
Analyze: "{user_text}". 
Return JSON:
- If logging: {{"intent": "log", "amount": 10.0, "category": "Food", "description": "text"}}
- If asking: {{"intent": "chat", "chat_reply": "answer"}}
<|assistant|>
"""
    try:
        response = llm.invoke(prompt)
        match = re.search(r'\{.*\}', response, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"AI error: {e}")
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
        st.title("💰 FinSight Pro")
        choice = st.selectbox("Action", ["Login", "Signup"])
        user = st.text_input("Username")
        pwd = st.text_input("Password", type='password')
        if st.button("Enter"):
            if choice == "Signup" and add_user(user, pwd): st.success("Created!")
            elif choice == "Login" and login_user(user, pwd):
                st.session_state.update({"logged_in": True, "username": user})
                st.rerun()
            else: st.error("Failed.")
    else:
        username = st.session_state.username
        with st.sidebar:
            st.title(f"Hi, {username}!")
            df = get_user_transactions(username)
            if not df.empty:
                st.bar_chart(df.groupby('category')['amount'].sum())
                st.download_button("CSV", df.to_csv(index=False).encode('utf-8'), "data.csv")
            if st.button("Logout"):
                st.session_state.update({"logged_in": False, "messages": []}); st.rerun()

        st.title("💰 AI Finance Assistant")
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if user_text := st.chat_input("Log something..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            with st.spinner("Processing..."):
                res = process_user_input_with_hf(user_text, df)
                if res:
                    if res.get("intent") == "log" and res.get("amount") is not None:
                        insert_transaction(res['amount'], res['category'], res['description'], username)
                        msg = f"✅ Logged: ${res['amount']} for {res['category']}"
                        st.session_state.messages.append({"role": "assistant", "content": msg})
                        st.rerun()
                    elif res.get("intent") == "chat":
                        reply = res.get("chat_reply", "I processed it.")
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                else:
                    st.error("AI returned empty or error.")

if __name__ == "__main__":
    main()
