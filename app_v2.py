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
# 嚴格從 Streamlit Cloud 的 Secrets 讀取
MY_API_KEY = st.secrets.get("GOOGLE_API_KEY")
DB_NAME = "finance.db"

def make_hashes(password):
    """Generates a SHA256 hash for the given password."""
    return hashlib.sha256(str.encode(password)).hexdigest()

# ==========================================
# 2. DATABASE FUNCTIONS (User-Scoped and Robust)
# ==========================================
def init_db():
    """Initializes the SQLite database with users and transactions tables."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # 建立 users 表
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
    # 建立 transactions 表
    c.execute('''CREATE TABLE IF NOT EXISTS transactions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, category TEXT, description TEXT, username TEXT)''')
    
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
    except sqlite3.IntegrityError: 
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
# 3. AI LOGIC ENGINE (Updated with Local Filtering)
# ==========================================
def process_user_input(user_text, df):
    # --- [新增功能] 本地過濾邏輯：減少 API 額度消耗 ---
    clean_input = user_text.lower().strip()
    greetings = ["hi", "hello", "你好", "hey", "早安", "午安", "晚安", "thanks", "謝謝", "再見", "bye"]
    
    if clean_input in greetings:
        return {
            "intent": "chat", 
            "chat_reply": "Hello! I am your AI Finance Assistant. How can I help you with your budget or expenses today?"
        }
    # ----------------------------------------------

    # 強制等待 2 秒，避免觸發 Google API 頻率限制 (429 Error)
    time.sleep(2) 
    
    if not MY_API_KEY:
        return {"intent": "chat", "chat_reply": "Error: API Key is not configured in Streamlit Secrets."}

    client = genai.Client(api_key=MY_API_KEY)
    history_text = df.tail(15).to_string(index=False) if not df.empty else "No previous transactions."
    
    prompt = f"""You are FinSight AI, a professional AI Finance Assistant.
    Your task is to either log new expenses based on user input or provide helpful financial advice/answers by analyzing the user's transaction history.
    
    --- Transaction History for Context ---
    {history_text}
    --- End of History ---
    
    User Input: "{user_text}"
    
    Return STRICTLY a valid JSON object. Do NOT include markdown code blocks.
    
    If logging a new expense:
    {{
        "intent": "log",
        "amount": <number>,
        "category": "<Food/Transport/Housing/Entertainment/Others>",
        "description": "<text>"
    }}
    
    If asking a question:
    {{
        "intent": "chat",
        "chat_reply": "<Your concise answer based on history>"
    }}
    """
    
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        else:
            return {"intent": "chat", "chat_reply": f"AI Parsing Error. Raw output: {response.text}"}
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
            return {"intent": "chat", "chat_reply": "⚠️ API limit reached. Please wait a moment or use the Quick Analysis buttons."}
        else:
            return {"intent": "chat", "chat_reply": f"An unexpected error occurred: {error_msg}"}

# ==========================================
# 4. STREAMLIT UI (Full-Featured Application)
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide", initial_sidebar_state="expanded")
    init_db()

    if "logged_in" not in st.session_state: st.session_state.update({"logged_in": False, "username": None, "messages": []})
    
    if not st.session_state.logged_in:
        st.title("💰 FinSight AI - Access")
        choice = st.selectbox("Action", ["Login", "Signup"])
        user = st.text_input("Username")
        pwd = st.text_input("Password", type='password')
        if st.button("Enter"):
            if choice == "Signup":
                if add_user(user, pwd): st.success("Account created! Please Login.")
                else: st.error("Username already exists!")
            else:
                if login_user(user, pwd):
                    st.session_state.update({"logged_in": True, "username": user, "messages": []})
                    st.rerun()
                else: st.error("Invalid Username or Password")
    
    else:
        username = st.session_state.username
        
        # --- SIDEBAR (包含快速查詢按鈕) ---
        with st.sidebar:
            st.title(f"Welcome, {username}!")
            if st.button("Logout"):
                st.session_state.update({"logged_in": False, "messages": []})
                st.rerun() 
            
            df = get_user_transactions(username)
            
            # --- [新增功能] 快速查詢按鈕 (完全不消耗 API) ---
            st.divider()
            st.subheader("⚡ Quick Analysis (No API)")
            if not df.empty:
                c1, c2 = st.columns(2)
                if c1.button("💰 Total"):
                    st.info(f"Total Spent: ${df['amount'].sum():.2f}")
                if c2.button("🍕 Top"):
                    top_cat = df.groupby('category')['amount'].sum().idxmax()
                    st.info(f"Top Category: {top_cat}")
            # ----------------------------------------------

            st.subheader("📊 Spending Analytics")
            if not df.empty:
                category_sums = df.groupby('category')['amount'].sum()
                st.bar_chart(category_sums)
                
                # 下載 CSV
                csv_data = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Download as CSV",
                    data=csv_data,
                    file_name=f'{username}_transactions.csv',
                    mime='text/csv'
                )
            else:
                st.info("No data yet.")
            
            st.divider()
            if st.button("🗑️ Clear All My Data"):
                clear_user_data(username)
                st.session_state.messages = []
                st.rerun()

        # --- MAIN CHAT AREA ---
        st.title("💰 FinSight AI Assistant")
        st.caption("Log expenses naturally or ask questions. Greetings are now processed instantly!")

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if user_text := st.chat_input("Type here..."):
            st.chat_message("user").markdown(user_text)
            st.session_state.messages.append({"role": "user", "content": user_text})
            
            with st.spinner("Processing..."):
                res = process_user_input(user_text, df)
                
                if res:
                    if res.get("intent") == "log" and res.get("amount") is not None:
                        insert_transaction(res['amount'], res['category'], res['description'], username)
                        reply = f"✅ Logged successfully! \n\n**Amount:** ${res['amount']} \n**Category:** {res['category']} \n**Detail:** {res['description']}"
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                        st.rerun()
                    
                    elif res.get("intent") == "chat":
                        reply = res.get("chat_reply", "I'm not sure how to respond.")
                        st.chat_message("assistant").markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                    
                    else:
                        st.error("AI couldn't understand. Please try again.")
                else:
                    st.error("An internal processing error occurred.")

if __name__ == "__main__":
    main()
