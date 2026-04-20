import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
import time
import os

# --- LangChain 相關套件 ---
from langchain_community.llms import HuggingFaceEndpoint 
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

# ==========================================
# 1. CONFIGURATION & SECURITY
# ==========================================
# 確保在 Streamlit Cloud Secrets 設定 HUGGINGFACEHUB_API_TOKEN
HF_API_TOKEN = st.secrets.get("HUGGINGFACEHUB_API_TOKEN")

# 使用開源模型 (Mistral 性能優秀且免費額度較高)
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
    
    # 資料庫遷移：自動檢查並加入 username 欄位
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
# 3. AI LOGIC ENGINE (Using HuggingFaceEndpoint)
# ==========================================
@st.cache_resource
def get_llm_model_hf():
    if not HF_API_TOKEN:
        st.error("Error: HUGGINGFACEHUB_API_TOKEN not found in Secrets.")
        return None
    os.environ["HUGGINGFACEHUB_API_TOKEN"] = HF_API_TOKEN
    try:
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
    llm = get_llm_model_hf()
    if llm is None: return None

    history_text = df.tail(10).to_string(index=False) if not df.empty else "No history."
    
    # 嚴格規範 JSON 輸出
    prompt = f"""[INST] You are FinSight AI. Based on history, parse user input.
    History: {history_text}
    User: "{user_text}"
    
    Return JSON only:
    - If logging: {{"intent": "log", "amount": 10.0, "category": "Food", "description": "pizza"}}
    - If asking/chatting: {{"intent": "chat", "chat_reply": "your answer"}}
    [/INST]"""
    
    try:
        response_content = llm.invoke(prompt)
        # 用正則表達式提取 JSON 區塊，避免 AI 多說話
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

    if "logged_in" not in st.session_state: 
        st.session_state.update({"logged_in": False, "username": None, "messages": []})
    
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
        
        # --- SIDEBAR ---
        with st.sidebar:
            st.title(f"Hi, {username}!")
            df = get_user_transactions(username)
            if not df.empty:
                st.subheader("📊 Analytics")
                st.bar_chart(df.groupby('category')['amount'].sum())
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("Download CSV", csv, f"{username}_data.csv", "text/csv")
            
            st.divider()
            if st.button("🗑️ Clear My Data"):
                clear_user_data(username)
                st.session_state.messages = []
                st.rerun()
            if st.button("Logout"):
                st.session_state.update({"logged_in": False, "username": None, "messages": []})
                st.rerun()

        # --- CHAT AREA ---
        st.title("💰 FinSight AI Assistant")
        # 顯示歷史對話
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if user_text := st.chat_input("Spent $50 on lunch / How much did I spend?"):
            # 顯示用戶訊息
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            with st.spinner("AI is analyzing..."):
                res = process_user_input_with_hf(user_text, df)
                
                if res:
                    if res.get("intent") == "log" and res.get("amount") is not None:
                        insert_transaction(res['amount'], res['category'], res['description'], username)
                        reply = f"✅ **Logged:** ${res['amount']} for {res['category']} ({res['description']})"
                        # 儲存回覆並重整 (顯示圖表更新)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                        st.rerun()
                    
                    elif res.get("intent") == "chat":
                        reply = res.get("chat_reply", "I've processed your request.")
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                else:
                    st.error("AI service is busy or returned an empty response. Please try again.")

if __name__ == "__main__":
    main()
