import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
import time

# --- LangChain 相關套件 ---
from langchain_community.llms import HuggingFaceHub # 如果需要HuggingFace
from langchain_google_genai import ChatGoogleGenerativeAI # 如果需要Google Gemini
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain.prompts import PromptTemplate # 這個 PromptTemplate 模組目前仍在 langchain 套件下

# ==========================================
# 1. CONFIGURATION & SECURITY
# ==========================================
# 請將你的 Hugging Face Token 貼在這裡
# 這將替代你的 Google API Key
import os # <-- 確保在最上方 import os

# ==========================================
# 1. CONFIGURATION & SECURITY
# ==========================================
# 從 Streamlit secrets 讀取，否則從環境變數讀取 (本地開發用)
 "HF_API_TOKEN" in st.secrets:
    HF_API_TOKEN = st.secrets["HF_API_TOKEN"]


OPEN_SOURCE_LLM_MODEL = "meta-llama/Llama-2-7b-chat-hf" 
DB_NAME = "finance.db"
# 你可以換成其他模型，例如 "mistralai/Mistral-7B-Instruct-v0.2"

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
    except sqlite3.IntegrityError: return False
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
# 3. AI LOGIC ENGINE (Now with LangChain & Hugging Face)
# ==========================================
@st.cache_resource
def get_llm_model_hf():
    """Initializes and returns the LangChain-wrapped Hugging Face model."""
    if not HF_API_TOKEN or HF_API_TOKEN == "hf_你的HuggingFaceToken":
        st.error("Error: Hugging Face API Token is not configured. Please get one from Hugging Face settings.")
        return None
    
    # 使用 HuggingFaceHub 連接到開源模型
    # model_kwargs 可以調整模型參數，例如 max_new_tokens
    llm = HuggingFaceHub(
        repo_id=OPEN_SOURCE_LLM_MODEL,
        huggingfacehub_api_token=HF_API_TOKEN,
        model_kwargs={"temperature": 0.1, "max_new_tokens": 150} # max_new_tokens 限制 AI 回覆長度
    )
    return llm

def process_user_input_with_hf(user_text, df):
    time.sleep(2) # 緩解 API 限速

    llm = get_llm_model_hf()
    if llm is None: return None

    history_text = df.tail(15).to_string(index=False) if not df.empty else "No previous transactions."
    
    # 使用 PromptTemplate 構建 Prompt
    prompt_template = PromptTemplate.from_template(
        """You are FinSight AI, a professional AI Finance Assistant.
        Your task is to either log new expenses based on user input or provide helpful financial advice/answers by analyzing the user's transaction history.
        
        --- Transaction History for Context ---
        {history_text}
        --- End of History ---
        
        User Input: "{user_text}"
        
        Return STRICTLY a valid JSON object. Do NOT include markdown code blocks (e.g., ```json) or any conversational text outside the JSON.
        
        If the user is logging a new expense, use this JSON format:
        {{"intent": "log", "amount": 0.0, "category": "Food/Transport/Housing/Entertainment/Others", "description": "lunch"}}
        
        If the user is asking a question or for advice, use this JSON format:
        {{"intent": "chat", "chat_reply": "Your advice/answer here"}}
        """
    )
    
    # 組合 Prompt
    formatted_prompt = prompt_template.format(history_text=history_text, user_text=user_text)
    
    try:
        # LangChain LLM 處理
        response_content = llm.invoke(formatted_prompt)
        
        # 使用正則表達式強行從 AI 回應中提取 JSON 字串
        match = re.search(r'\{.*\}', response_content, re.DOTALL)
        if match:
            clean_json_string = match.group(0)
            return json.loads(clean_json_string)
        else:
            return {"intent": "chat", "chat_reply": f"AI Parsing Error: Could not find valid JSON in response. Raw AI output: {response_content}"}
    except Exception as e:
        st.error(f"AI Processing Critical Error: {e}") 
        return None

# ==========================================
# 4. STREAMLIT UI (Full-Featured Application)
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide", initial_sidebar_state="expanded")
    init_db()

    if "logged_in" not in st.session_state: st.session_state.update({"logged_in": False, "username": None, "messages": []})
    
    # --- 登入/註冊頁面 ---
    if not st.session_state.logged_in:
        st.title("💰 FinSight AI - Access")
        choice = st.selectbox("Action", ["Login", "Signup"])
        user = st.text_input("Username")
        pwd = st.text_input("Password", type='password')
        if st.button("Enter"):
            if choice == "Signup":
                if add_user(user, pwd): st.success("Account created! Please Login.")
                else: st.error("Username already exists!")
            else: # Login logic
                if login_user(user, pwd):
                    st.session_state.update({"logged_in": True, "username": user, "messages": []}) # 登入成功清空訊息
                    st.rerun() 
                else: st.error("Invalid Username or Password")
    
    # --- 主應用程式頁面 (已登入) ---
    else:
        username = st.session_state.username
        
        # 側邊欄 (Sidebar) 內容
        with st.sidebar:
            st.title(f"Welcome, {username}!")
            if st.button("Logout"): st.session_state.update({"logged_in": False, "messages": []}); st.rerun()
            
            df = get_user_transactions(username) # 獲取當前用戶的數據
            
            st.subheader("📊 Spending Analytics")
            if not df.empty:
                category_sums = df.groupby('category')['amount'].sum()
                st.bar_chart(category_sums)
                
                st.divider()
                st.subheader("📥 Export Data")
                csv_data = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Download as CSV",
                    data=csv_data,
                    file_name=f'{username}_transactions.csv',
                    mime='text/csv',
                    help="Download your transaction history as an Excel-compatible CSV file."
                )
            else:
                st.info("No data yet. Log some transactions in the chat to see your analytics!")
            
            st.divider()
            if st.button("🗑️ Clear All My Data"):
                clear_user_data(username)
                st.session_state.messages = [] 
                st.rerun() 

        # 主聊天區域
        st.title("💰 FinSight AI Assistant")
        st.caption("Log your expenses (e.g., 'Spent $50 on coffee') or ask questions about your finances (e.g., 'How much did I spend on Food?').")

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if user_text := st.chat_input("Type your expense or question..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            with st.spinner("AI is thinking..."):
                res = process_user_input_with_hf(user_text, df) # !!! 現在呼叫的是 Hugging Face 模型 !!!
                
                if res:
                    if res.get("intent") == "log" and res.get("amount") is not None:
                        insert_transaction(res['amount'], res['category'], res['description'], username)
                        reply = f"✅ Logged successfully! \n\n**Amount:** ${res['amount']} \n**Category:** {res['category']} \n**Detail:** {res['description']}"
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                        st.rerun() 
                    
                    elif res.get("intent") == "chat":
                        reply = res.get("chat_reply", "I'm not sure how to respond to that. Can you rephrase?")
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                    
                    else:
                        st.error("AI couldn't understand your request. Please try again with clear instructions.")
                else:
                    st.error("An internal AI processing error occurred. Please try again.")

if __name__ == "__main__":
    main()
