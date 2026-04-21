import streamlit as st
import sqlite3
import json
import pandas as pd
import hashlib
import re
import time
import plotly.express as px
from google import genai

# ==========================================
# 1. CONFIGURATION & CSS
# ==========================================
MY_API_KEY = st.secrets.get("GOOGLE_API_KEY")
DB_NAME = "finance.db"

def apply_custom_style():
    st.markdown("""
        <style>
        .main { background-color: #f8f9fa; }
        div.stButton > button { border-radius: 8px; font-weight: bold; }
        .stChatMessage { border-radius: 12px; border: 1px solid #e9ecef; }
        </style>
    """, unsafe_allow_html=True)

# ==========================================
# 2. DATABASE FUNCTIONS
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, category TEXT, description TEXT, username TEXT)')
    c.execute("PRAGMA table_info(transactions)")
    if 'username' not in [i[1] for i in c.fetchall()]: c.execute("ALTER TABLE transactions ADD COLUMN username TEXT")
    conn.commit(); conn.close()

def make_hashes(pwd): return hashlib.sha256(str.encode(pwd)).hexdigest()

def insert_transaction(amt, cat, desc, user):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("INSERT INTO transactions (amount, category, description, username) VALUES (?,?,?,?)", (amt, cat, desc, user))
    conn.commit(); conn.close()

def get_user_transactions(user):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT amount, category, description FROM transactions WHERE username = ?", conn, params=(user,))
    conn.close()
    return df

# ==========================================
# 3. ROBUST AI ENGINE (With Graceful Error Handling)
# ==========================================
def process_user_input(user_text, df):
    # 本地過濾：打招呼
    greetings = ["hi", "hello", "你好", "hey", "thanks", "謝謝"]
    if user_text.lower().strip() in greetings:
        return {"intent": "chat", "chat_reply": "Hello! I am your FinSight assistant. I can help you log expenses or analyze your data."}

    if not MY_API_KEY:
        return {"intent": "chat", "chat_reply": "❌ Error: API Key is missing. Please check Secrets."}

    try:
        client = genai.Client(api_key=MY_API_KEY)
        history = df.tail(10).to_string(index=False) if not df.empty else "No history."
        
        prompt = f"""You are a professional AI Finance Assistant. 
        Context: {history}
        Input: "{user_text}"
        Return JSON ONLY:
        - If logging: {{"intent": "log", "amount": 100, "category": "Food/Transport/Housing/Entertainment/Others", "description": "text"}}
        - If asking: {{"intent": "chat", "chat_reply": "Your concise answer"}}
        No markdown."""
        
        time.sleep(2) # 強制延遲，避免 429/503 錯誤
        # 使用更穩定的 1.5 Flash 模型
        response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match: return json.loads(match.group(0))
        raise Exception("Invalid AI Response")
        
    except Exception as e:
        # 捕捉伺服器繁忙錯誤並提供友好的回覆
        error_msg = str(e)
        if "503" in error_msg or "UNAVAILABLE" in error_msg:
            return {"intent": "chat", "chat_reply": "⚠️ The AI server is currently busy. Please wait 10 seconds or use the **Quick Analysis** buttons in the sidebar for instant data."}
        elif "429" in error_msg:
            return {"intent": "chat", "chat_reply": "⚠️ API limit reached. I need a short break. Please try again in a few seconds."}
        else:
            return {"intent": "chat", "chat_reply": f"🤖 AI is having a minor issue. Please try again or rephrase your sentence."}

# ==========================================
# 4. MAIN UI
# ==========================================
def main():
    st.set_page_config(page_title="FinSight Pro", layout="wide", page_icon="💰")
    apply_custom_style(); init_db()

    if "logged_in" not in st.session_state: 
        st.session_state.update({"logged_in": False, "username": None, "messages": []})

    if not st.session_state.logged_in:
        st.title("💰 FinSight Pro - Access")
        choice = st.radio("Action", ["Login", "Signup"], horizontal=True)
        u = st.text_input("Username")
        p = st.text_input("Password", type='password')
        if st.button("Enter Dashboard"):
            if choice == "Signup":
                conn = sqlite3.connect(DB_NAME); c = conn.cursor()
                try:
                    c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (u, make_hashes(p)))
                    conn.commit(); st.success("Account created! Please Login.")
                except: st.error("User already exists.")
                conn.close()
            elif u and p:
                conn = sqlite3.connect(DB_NAME); c = conn.cursor()
                c.execute("SELECT password FROM users WHERE username = ?", (u,))
                res = c.fetchone()
                conn.close()
                if res and make_hashes(p) == res[0]:
                    st.session_state.update({"logged_in": True, "username": u}); st.rerun()
                else: st.error("Access denied.")
    else:
        username = st.session_state.username
        df = get_user_transactions(username)

        with st.sidebar:
            st.title(f"👋 Hi, {username}!")
            # 側邊欄快速按鈕 (完全不扣 API，Demo 保險)
            st.subheader("⚡ Quick Analysis (No API)")
            if not df.empty:
                c1, c2 = st.columns(2)
                if c1.button("💰 Total"): st.info(f"Total spent: ${df['amount'].sum():,.1f}")
                if c2.button("🍕 Top"): 
                    top_cat = df.groupby('category')['amount'].sum().idxmax()
                    st.info(f"Top: {top_cat}")
            
            st.divider()
            if st.button("Logout"): 
                st.session_state.update({"logged_in": False, "username": None, "messages": []}); st.rerun()

        st.title("💼 Financial Dashboard")
        # 頂部指標
        m1, m2, m3 = st.columns(3)
        total_val = df['amount'].sum() if not df.empty else 0
        m1.metric("Total Expenses", f"${total_val:,.1f}")
        m2.metric("Total Records", len(df))
        m3.metric("Top Category", df.groupby('category')['amount'].sum().idxmax() if not df.empty else "N/A")
        st.divider()

        tab_chat, tab_data = st.tabs(["💬 AI Assistant", "📊 Detailed Analytics"])

        with tab_chat:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]): st.markdown(msg["content"])

            if prompt := st.chat_input("Spent $50 on pizza..."):
                st.chat_message("user").markdown(prompt)
                st.session_state.messages.append({"role": "user", "content": prompt})
                
                with st.spinner("Analyzing..."):
                    res = process_user_input(prompt, df)
                    if res:
                        if res.get("intent") == "log" and res.get("amount") is not None:
                            insert_transaction(res['amount'], res['category'], res['description'], username)
                            msg = f"✅ **Logged successfully:** ${res['amount']} for {res['category']}"
                            st.session_state.messages.append({"role": "assistant", "content": msg})
                            st.rerun()
                        elif res.get("intent") == "chat":
                            reply = res.get("chat_reply")
                            st.chat_message("assistant").markdown(reply)
                            st.session_state.messages.append({"role": "assistant", "content": reply})
                    else:
                        st.error("AI connection lost. Try again in 5 seconds.")

        with tab_data:
            if not df.empty:
                fig = px.pie(df, values='amount', names='category', hole=0.4, title="Expense Distribution")
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True)
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download Report (CSV)", csv, "fin_report.csv", "text/csv")
            else: st.warning("No data recorded yet.")

if __name__ == "__main__":
    main()
