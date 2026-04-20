import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
import time

# --- LangChain 相關套件 ---
from langchain_google_genai import ChatGoogleGenerativeAI # 用 LangChain 呼叫 Gemini
from langchain_core.messages import HumanMessage, SystemMessage # 訊息格式
from langchain_core.output_parsers import JsonOutputParser # 解析 JSON 輸出

# ==========================================
# 1. CONFIGURATION & SECURITY
# ==========================================
# 優先從 Streamlit Cloud secrets 讀取，若無則使用代碼中的硬編碼 Key (用於本地測試)
if "GOOGLE_API_KEY" in st.secrets:
    MY_API_KEY = st.secrets["GOOGLE_API_KEY"]
else:
    MY_API_KEY = "AIzaSyA7sb3tD6xuAzKvwYvjnK6TQ2lvOe9pE6w" # !!! 請務必填入你自己的 Key !!!

DB_NAME = "finance.db"

def make_hashes(password):
    """Generates a SHA256 hash for the given password."""
    return hashlib.sha256(str.encode(password)).hexdigest()

# ==========================================
# 2. DATABASE FUNCTIONS
# ==========================================
def init_db():
    """Initializes the SQLite database with users and transactions tables."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, category TEXT, description TEXT, username TEXT)''')
    
    # 檢查並自動補上 'username' 欄位 (資料庫遷移邏輯)
    c.execute("PRAGMA table_info(transactions)")
    columns = [info[1] for info in c.fetchall()]
    if 'username' not in columns:
        c.execute("ALTER TABLE transactions ADD COLUMN username TEXT")
    
    conn.commit()
    conn.close()

def add_user(username, password):
    """Adds a new user to the database."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, make_hashes(password)))
        conn.commit()
        return True
    except sqlite3.IntegrityError: # 捕獲 'username' 已經存在的錯誤
        return False
    finally:
        conn.close()

def login_user(username, password):
    """Verifies user credentials for login."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT password FROM users WHERE username = ?", (username,))
    data = c.fetchone()
    conn.close()
    if data and make_hashes(password) == data[0]:
        return True
    return False

def insert_transaction(amount, category, description, username):
    """Inserts a new transaction for a specific user."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (amount, category, description, username) VALUES (?, ?, ?, ?)", 
              (amount, category, description, username))
    conn.commit()
    conn.close()

def get_user_transactions(username):
    """Fetches all transactions for a given user."""
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT id, amount, category, description FROM transactions WHERE username = ?", conn, params=(username,))
    conn.close()
    return df

def clear_user_data(username):
    """Deletes all transaction data for a specific user."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE username = ?", (username,))
    conn.commit()
    conn.close()

# ==========================================
# 3. AI LOGIC ENGINE (Now with LangChain!)
# ==========================================
@st.cache_resource # 將 LangChain 模型快取，避免每次 rerun 都重新載入
def get_llm_model():
    """Initializes and returns the LangChain-wrapped Gemini model."""
    if not MY_API_KEY or MY_API_KEY == "PASTE_YOUR_API_KEY_HERE":
        st.error("Error: API Key is not configured. Please check app settings.")
        return None
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=MY_API_KEY, temperature=0.1)

def process_user_input_with_langchain(user_text, df):
    """
    Uses LangChain to process user text, determine intent, and extract data/generate replies.
    """
    llm = get_llm_model()
    if llm is None: return None

    # 提供 AI 歷史交易紀錄作為上下文
    history_text = df.tail(15).to_string(index=False) if not df.empty else "No previous transactions."
    
    # 定義 JSON 解析器
    parser = JsonOutputParser()

    # AI 的 Prompt (提示詞) - 更明確地定義輸入和輸出
    messages = [
        SystemMessage(content="You are FinSight AI, a professional AI Finance Assistant. "
                              "Your task is to either log new expenses based on user input or provide helpful financial advice/answers by analyzing the user's transaction history. "
                              "Strictly return a JSON object. Do not include markdown code blocks or any conversational text outside the JSON. "
                              "Standard Categories: Food, Transport, Housing, Entertainment, Others. "
                              f"Transaction History: {history_text}"),
        HumanMessage(content=f"User Input: {user_text}\n"
                             f"Return JSON for logging: {{\"intent\": \"log\", \"amount\": 0.0, \"category\": \"Food\", \"description\": \"lunch\"}}\n"
                             f"Return JSON for chatting: {{\"intent\": \"chat\", \"chat_reply\": \"Your advice/answer here\"}}")
    ]
    
    try:
        # 使用 LangChain 的 invoke 方法呼叫 LLM
        response = llm.invoke(messages)
        return parser.parse(response.content) # 使用 parser 解析內容
    except Exception as e:
        # 捕獲 API 連線或執行錯誤，並提供用戶友好的訊息
        error_msg = str(e)
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "UNAVAILABLE" in error_msg:
            return {"intent": "chat", "chat_reply": "⚠️ API limit reached. Please wait a moment or try again later. Google AI servers might be busy."}
        else:
            st.error(f"AI Processing Critical Error: {error_msg}") # 打印到 Streamlit 介面方便除錯
            return None

# ==========================================
# 4. STREAMLIT UI (Full-Featured Application)
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide", initial_sidebar_state="expanded")
    init_db()

    # Session State 初始化和管理
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
                    st.rerun() # 成功登入後重整頁面
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
                
                # 下載 CSV 功能
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
            # 清空個人數據按鈕
            if st.button("🗑️ Clear All My Data"):
                clear_user_data(username)
                st.session_state.messages = [] # 清空聊天紀錄
                st.rerun() # 重整頁面

        # 主聊天區域
        st.title("💰 FinSight AI Assistant")
        st.caption("Log your expenses (e.g., 'Spent $50 on coffee') or ask questions about your finances (e.g., 'How much did I spend on Food?').")

        # 顯示歷史訊息
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # 處理使用者輸入
        if user_text := st.chat_input("Type your expense or question..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            with st.spinner("AI is thinking..."):
                # 使用 LangChain 處理輸入
                res = process_user_input_with_langchain(user_text, df) 
                
                if res:
                    if res.get("intent") == "log" and res.get("amount") is not None:
                        # 記錄交易
                        insert_transaction(res['amount'], res['category'], res['description'], username)
                        reply = f"✅ Logged successfully! \n\n**Amount:** ${res['amount']} \n**Category:** {res['category']} \n**Detail:** {res['description']}"
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                        st.rerun() # 成功記錄後重整頁面，更新側邊欄圖表
                    
                    elif res.get("intent") == "chat":
                        # AI 回答問題或提供建議
                        reply = res.get("chat_reply", "I'm not sure how to respond to that. Can you rephrase?")
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                    
                    else:
                        # AI 判斷意圖失敗或格式不符
                        st.error("AI couldn't process your request. Please try again with clear instructions.")
                else:
                    # process_user_input_with_langchain 返回 None，表示發生了內部錯誤
                    st.error("An internal AI processing error occurred. Please try again.")

if __name__ == "__main__":
    main()
