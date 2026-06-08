import streamlit as st
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
import re

# ---------- page config ----------
st.set_page_config(page_title="CodeLume – AI Coding Assistant", page_icon="💡")
st.title("💡 CodeLume")
st.caption("Your personal AI code illuminator – powered by Qwen 2.5 Coder 32B (free via Cloudflare)")

# ---------- database setup ----------
DATABASE_URL = os.environ["DATABASE_URL"]

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

def load_messages():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT role, content FROM messages ORDER BY id ASC;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in rows]

def add_message(role, content):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (role, content) VALUES (%s, %s);",
        (role, content)
    )
    conn.commit()
    cur.close()
    conn.close()

def clear_all_messages():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM messages;")
    conn.commit()
    cur.close()
    conn.close()

init_db()

# ---------- Cloudflare Workers AI setup ----------
ACCOUNT_ID = os.environ["CLOUDFLARE_ACCOUNT_ID"]
API_TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
if not API_TOKEN.startswith("Bearer "):
    API_TOKEN = f"Bearer {API_TOKEN}"

API_BASE = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/"
# The best free coding model on Cloudflare – 32B parameters
MODEL = "@cf/qwen/qwen2.5-coder-32b-instruct"

def get_ai_response(messages):
    headers = {"Authorization": API_TOKEN}
    payload = {
        "messages": messages,
        "max_tokens": 4000,     # Increased for longer, complete code outputs
        "temperature": 0.2      # Low randomness for precise code
    }
    response = requests.post(API_BASE + MODEL, json=payload, headers=headers)
    response.raise_for_status()
    data = response.json()
    if data.get("success"):
        return data["result"]["response"]
    else:
        raise Exception(f"Cloudflare API error: {data.get('errors')}")

# ---------- session state ----------
if "messages" not in st.session_state:
    st.session_state.messages = load_messages()
    if not st.session_state.messages:
        st.session_state.messages = [
            {"role": "assistant", "content": "Hi! I'm your coding assistant. Ask me to write, explain, or fix code. You can also paste code in the sidebar for context."}
        ]
        add_message("assistant", st.session_state.messages[0]["content"])

# ---------- sidebar ----------
with st.sidebar:
    st.header("⚙️ Context & Tools")
    context_code = st.text_area(
        "Paste code you're working on (optional)",
        height=200,
        placeholder="Paste any code here and it will be sent as context to the model..."
    )
    st.divider()
    if st.button("🗑️ Clear entire history"):
        clear_all_messages()
        st.session_state.messages = [
            {"role": "assistant", "content": "History cleared. How can I help?"}
        ]
        add_message("assistant", st.session_state.messages[0]["content"])
        st.rerun()

# ---------- render messages (with code highlighting) ----------
def render_message(content):
    pattern = r"```(\w+)?\n(.*?)```"
    matches = list(re.finditer(pattern, content, re.DOTALL))
    if not matches:
        st.markdown(content)
        return
    last_end = 0
    for match in matches:
        text_before = content[last_end:match.start()]
        if text_before.strip():
            st.markdown(text_before)
        lang = match.group(1) if match.group(1) else "python"
        code = match.group(2).strip()
        st.code(code, language=lang)
        last_end = match.end()
    text_after = content[last_end:]
    if text_after.strip():
        st.markdown(text_after)

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        render_message(msg["content"])

# ---------- chat input ----------
if prompt := st.chat_input("Write a coding request..."):
    if context_code.strip():
        full_prompt = f"Here is some code for context:\n```\n{context_code}\n```\n\nUser request: {prompt}"
    else:
        full_prompt = prompt

    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    add_message("user", prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                conversation = [
                    {"role": "system", "content": "You are an expert software engineer. Write clean, well-commented code. Provide only the code unless the user asks for an explanation. If the user provides context code, use it to inform your answer."}
                ]
                recent = [m for m in st.session_state.messages if m["role"] != "system"][-10:]
                conversation.extend(recent)
                conversation[-1]["content"] = full_prompt

                reply = get_ai_response(conversation)
                render_message(reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})
                add_message("assistant", reply)
            except Exception as e:
                error_msg = f"❌ Error: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
                add_message("assistant", error_msg)