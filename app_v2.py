import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
import time
import os

# --- LangChain 相關套件 ---
from langchain_community.llms import HuggingFaceEndpoint # <--- 更換為更穩定的 Endpoint
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

# ==========================================
# 1. CONFIGURATION & SECURITY
# ==========================================
# 從 Streamlit secrets 讀取 Token
HF_API_TOKEN = st.secrets.get("HUGGINGFACEHUB_API_TOKEN")

# 使用更穩定的開源模型
OPEN_SOURCE_LLM_MODEL = "mistralai/Mistral-7B-Instruct-v0.2" 
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
    df = pd.read_sql_query("SELECT id, amount, category, description FROM transactions WHERE username = ?", conn, params=(username,))
    conn.close()
    return df

def clear_user_data(username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE username = ?", (username,))
    conn.commit(); conn.close()

# ==========================================
# 3. AI LOGIC ENGINE (Updated to HuggingFaceEndpoint)
# ==========================================
@st.cache_resource
def get_llm_model_hf():
    if not HF_API_TOKEN:
        st.error("Error: HUGGINGFACEHUB_API_TOKEN not found in Secrets.")
        return None
    
    os.environ["HUGGINGFACEHUB_API_TOKEN"] = HF_API_TOKEN
    
    try:
        # 使用 HuggingFaceEndpoint 替代 HuggingFaceHub
        llm = HuggingFaceEndpoint(
            repo_id=OPEN_SOURCE_LLM_MODEL,
            huggingfacehub_api_token=HF_API_TOKEN,
            temperature=0.1,
            max_new_tokens=250,
        )
        return llm
    except Exception as e:
        st.error(f"Endpoint Init Error: {e}")
        return None

def process_user_input_with_hf(user_text, df):
    time.sleep(1) 
    llm = get_llm_model_hf()
    if llm is None: return None

    history_text = df.tail(10).to_string(index=False) if not df.empty else "No previous transactions."
    
    prompt = f"""You are FinSight AI.
    Transaction History: {history_text}
    User Input: "{user_text}"
    
    Task: Return JSON only. 
    If log: {{"intent": "log", "amount": 0.0, "category": "Food/Transport/Housing/Entertainment/Others", "description": "text"}}
    If chat: {{"intent": "chat", "chat_reply": "Your answer"}}
    """
    
    try:
        response_content = llm.invoke(prompt)
        match = re.search(r'\{.*\}', response_content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"AI Logic Error: {e}")
        return None

# ==========================================
# 4. MAIN UI
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide")
    init_db()

    if "logged_in" not in st.session_state: st.session_state.update({"logged_in": False, "username": None, "messages": []})
    
    if not st.session_state.logged_in:
        st.title("💰 FinSight AI - Access")
        choice = st.selectbox("Action", ["Login", "Signup"])
        user = st.text_input("Username")
        pwd = st.text_input("Password", type='password')
        if st.button("Enter"):
            if choice == "Signup" and add_user(user, pwd): st.success("Account created!")
            elif choice == "Login" and login_user(user, pwd):
                st.session_state.update({"logged_in": True, "username": user})
                st.rerun()
            else: st.error("Invalid credentials.")
    else:
        username = st.session_state.username
        with st.sidebar:
            st.title(f"Hi, {username}!")
            df = get_user_transactions(username)
            if not df.empty:
                st.bar_chart(df.groupby('category')['amount'].sum())
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("Download CSV", csv, "data.csv")
            if st.button("Logout"): st.session_state.update({"logged_in": False, "messages": []}); st.rerun()

        st.title("💰 FinSight AI Assistant")
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if user_text := st.chat_input("Log expense or ask question..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            with st.spinner("Analyzing..."):
                res = process_user_input_with_hf(user_text, df)
                if res:
                    if res.get("intent") == "log" and res.get("amount") is not None:
                        insert_transaction(res['amount'], res['category'], res['description'], username)
                        reply = f"✅ Logged ${res['amount']} for {res['category']}"
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                        st.rerun()
                    elif res.get("intent") == "chat":
                        reply = res.get("chat_reply", "I processed your request.")
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                else:
                    st.error("AI returned an empty response. Try again.")

if __name__ == "__main__":
    main()
