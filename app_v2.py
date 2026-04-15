import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
from google import genai

# ==========================================
# 1. CONFIG & SECURITY
# ==========================================
# 優先嘗試讀取雲端 Secrets，否則使用硬編碼 Key
if "GOOGLE_API_KEY" in st.secrets:
    MY_API_KEY = st.secrets["GOOGLE_API_KEY"]
else:
    MY_API_KEY = "AIzaSyBOWAqxkAKxBBNkUy2-Fck_PkTqZlL6gIQ"

DB_NAME = "finance.db"

# ==========================================
# 2. DATABASE FUNCTIONS
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, category TEXT, description TEXT, username TEXT)''')
    conn.commit(); conn.close()

def insert_transaction(amount, category, description, username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (amount, category, description, username) VALUES (?, ?, ?, ?)", (amount, category, description, username))
    conn.commit(); conn.close()

def get_user_transactions(username):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM transactions WHERE username = ?", conn, params=(username,))
    conn.close()
    return df

# ==========================================
# 3. AI LOGIC ENGINE
# ==========================================
def process_user_input(user_text, df):
    # 如果 API Key 是空的，直接報錯
    if not MY_API_KEY or MY_API_KEY == "PASTE_YOUR_API_KEY_HERE":
        return {"intent": "chat", "chat_reply": "Error: API Key is not set correctly!"}

    client = genai.Client(api_key=MY_API_KEY)
    
    prompt = f"""You are a Finance Assistant. 
    User Input: "{user_text}".
    Return STRICTLY valid JSON.
    If log expense: {{"intent": "log", "amount": 100, "category": "Food", "description": "lunch"}}
    If chat/ask: {{"intent": "chat", "chat_reply": "Your helpful answer"}}
    No markdown, no extra words."""
    
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        # 用正則抓取 JSON
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        else:
            return {"intent": "chat", "chat_reply": f"AI raw response: {response.text}"}
    except Exception as e:
        return {"intent": "chat", "chat_reply": f"Error: {str(e)}"}

# ==========================================
# 4. STREAMLIT UI
# ==========================================
def main():
    st.set_page_config(page_title="FinSight", layout="wide")
    init_db()

    # 模擬登入 (為了測試，簡化流程)
    if "username" not in st.session_state: st.session_state.username = "Anson1642"
    
    username = st.session_state.username
    st.title("💰 FinSight AI Assistant")
    
    # 顯示聊天紀錄
    if "messages" not in st.session_state: st.session_state.messages = []
    for msg in st.session_state.messages: st.chat_message(msg["role"]).markdown(msg["content"])

    # 輸入區
    if user_text := st.chat_input("Log expense or ask question..."):
        st.chat_message("user").markdown(user_text)
        st.session_state.messages.append({"role": "user", "content": user_text})
        
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                result = process_user_input(user_text, get_user_transactions(username))
                
                if result and result.get("intent") == "log":
                    insert_transaction(result["amount"], result["category"], result["description"], username)
                    reply = f"✅ Logged: ${result['amount']} for {result['category']}."
                    st.markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                    st.rerun()
                elif result:
                    reply = result.get("chat_reply", "I couldn't understand that.")
                    st.markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                else:
                    st.error("AI returned nothing.")

if __name__ == "__main__":
    main()
