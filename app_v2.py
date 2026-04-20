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
# 優先讀取 Streamlit Cloud 的 Secrets，若無則使用代碼中的 Key
if "GOOGLE_API_KEY" in st.secrets:
    MY_API_KEY = st.secrets["GOOGLE_API_KEY"]


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
    
    # Check and add 'username' column if it doesn't exist (for migration)
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
    except sqlite3.IntegrityError: # Username already exists
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
# 3. AI LOGIC ENGINE
# ==========================================
def process_user_input(user_text, df):
    """
    Sends user text and transaction history to AI to determine intent (log/chat) 
    and extract data or generate a reply.
    """
    # 強制等待 2 秒，避免觸發 Google API 頻率限制 (429 Error)
    time.sleep(2) 
    
    # 檢查 API Key 是否有效
    if not MY_API_KEY or MY_API_KEY == "PASTE_YOUR_API_KEY_HERE":
        return {"intent": "chat", "chat_reply": "Error: API Key is not set correctly! Please configure it in code or Streamlit Secrets."}

    client = genai.Client(api_key=MY_API_KEY)
    
    # 提供 AI 歷史交易紀錄作為上下文
    history_text = df.tail(15).to_string(index=False) if not df.empty else "No previous transactions."
    
    # AI 的 Prompt (提示詞)，定義其角色和期望的輸出格式
    prompt = f"""You are FinSight AI, a professional AI Finance Assistant.
    Your task is to either log new expenses based on user input or provide helpful financial advice/answers by analyzing the user's transaction history.
    
    --- Transaction History for Context ---
    {history_text}
    --- End of History ---
    
    User Input: "{user_text}"
    
    Return STRICTLY a valid JSON object. Do NOT include markdown code blocks (e.g., ```json) or any conversational text outside the JSON.
    
    If the user is logging a new expense, use this JSON format:
    {{
        "intent": "log",
        "amount": <number_only_e.g._100.50>,
        "category": "<One_word_e.g._Food/Transport/Housing/Entertainment/Others>",
        "description": "<short_text_e.g._Lunch_at_cafe>"
    }}
    
    If the user is asking a question or for advice, use this JSON format:
    {{
        "intent": "chat",
        "chat_reply": "<Your_helpful_and_concise_answer_based_on_history_or_general_financial_knowledge>"
    }}
    """
    
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        # 使用正則表達式強行從 AI 回應中提取 JSON 字串
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            clean_json_string = match.group(0)
            return json.loads(clean_json_string)
        else:
            # 如果 AI 回覆不包含有效 JSON，則返回錯誤訊息
            return {"intent": "chat", "chat_reply": f"AI Parsing Error: Could not find valid JSON in response. Raw AI output: {response.text}"}
    except Exception as e:
        # 捕獲 API 連線或執行錯誤，並提供用戶友好的訊息
        error_msg = str(e)
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "UNAVAILABLE" in error_msg:
            return {"intent": "chat", "chat_reply": "⚠️ API limit reached. Please wait a moment or try again later. Google AI servers might be busy."}
        else:
            print(f"AI Processing Critical Error: {error_msg}") # 打印到終端機方便除錯
            return {"intent": "chat", "chat_reply": f"An unexpected AI error occurred: {error_msg}. Please try again or check console logs."}

# ==========================================
# 4. STREAMLIT UI (FULL FEATURED)
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide")
    init_db()

    # Session State 初始化
    if "logged_in" not in st.session_state: st.session_state.update({"logged_in": False, "username": None, "messages": []})
    if "last_input_processed" not in st.session_state: st.session_state.last_input_processed = ""

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
                    st.session_state.update({"logged_in": True, "username": user, "messages": []})
                    st.rerun() # 成功登入後重整頁面
                else: st.error("Invalid Username or Password")
    
    # --- 主應用程式頁面 (已登入) ---
    else:
        username = st.session_state.username
        
        # 側邊欄 (Sidebar)
        with st.sidebar:
            st.title(f"Welcome, {username}!")
            if st.button("Logout"): st.session_state.update({"logged_in": False, "messages": []}); st.rerun()
            
            df = get_user_transactions(username) # 獲取用戶數據
            
            st.subheader("📊 Analytics")
            if not df.empty:
                category_sums = df.groupby('category')['amount'].sum()
                st.bar_chart(category_sums)
                
                # 下載 CSV 功能
                csv_data = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Download as CSV",
                    data=csv_data,
                    file_name='my_transactions.csv',
                    mime='text/csv',
                    help="Download your transaction history as an Excel-compatible CSV file."
                )
            else:
                st.info("No data yet. Log some transactions!")
            
            st.divider()
            if st.button("🗑️ Clear My Data"):
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
            # 添加使用者訊息到會話狀態，並顯示在聊天框
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            # 使用 spinner 顯示 AI 正在思考
            with st.spinner("AI is thinking..."):
                res = process_user_input(user_text, df) # 呼叫 AI 處理輸入
                
                # 根據 AI 回應的 intent 進行處理
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
                        st.error("AI couldn't understand your request. Please try again with clear instructions.")
                else:
                    # process_user_input 返回 None，表示發生了內部錯誤
                    st.error("An internal processing error occurred. Please try again.")

if __name__ == "__main__":
    main()
