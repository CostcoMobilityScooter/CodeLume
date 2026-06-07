import streamlit as st
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from groq import Groq
import re

# ---------- page config ----------
st.set_page_config(page_title="AI Coding Assistant", page_icon="🤖")
st.title("🤖 AI Coding Assistant")
st.caption("Powered by Llama 3.1 70B (free via Groq)")

# ---------- database setup ----------
DATABASE_URL = os.environ["DATABASE_URL"]

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Create messages table if it doesn't exist."""
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
    """Load all messages from database, ordered by time."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT role, content FROM messages ORDER BY id ASC;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in rows]

def add_message(role, content):
    """Insert a new message into the database."""
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
    """Delete all messages from the database."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM messages;")
    conn.commit()
    cur.close()
    conn.close()

# Initialize DB table on first load
init_db()

# ---------- groq client ----------
groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

# ---------- session state ----------
if "messages" not in st.session_state:
    # Load from database
    st.session_state.messages = load_messages()
    if not st.session_state.messages:
        # Seed with a welcome message
        st.session_state.messages = [
            {"role": "assistant", "content": "Hi! I'm your coding assistant. Ask me to write, explain, or fix code. You can also paste code in the sidebar for context."}
        ]
        # Save welcome message to DB
        add_message("assistant", st.session_state.messages[0]["content"])

# ---------- sidebar: context & tools ----------
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

# ---------- display chat history ----------
def render_message(content):
    """Parse content and render code blocks with st.code() for perfect syntax highlighting."""
    # Split content by markdown code blocks: ```language\n...\n```
    pattern = r"```(\w+)?\n(.*?)```"
    parts = re.split(pattern, content, flags=re.DOTALL)
    # parts will be: [text_before, lang1, code1, text_after, lang2, code2, ...]
    # But re.split with groups yields alternating groups. We'll process chunks.
    # Simpler: iterate over matches and build segments.
    # We'll find all code blocks with their start/end positions.
    matches = list(re.finditer(pattern, content, re.DOTALL))
    if not matches:
        # No code blocks, just render as markdown
        st.markdown(content)
        return

    last_end = 0
    for match in matches:
        # Text before this code block
        text_before = content[last_end:match.start()]
        if text_before.strip():
            st.markdown(text_before)

        lang = match.group(1) if match.group(1) else "python"
        code = match.group(2).strip()
        st.code(code, language=lang)

        last_end = match.end()

    # Remaining text after last code block
    text_after = content[last_end:]
    if text_after.strip():
        st.markdown(text_after)

# Display all messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        render_message(msg["content"])

# ---------- chat input ----------
if prompt := st.chat_input("Write a coding request..."):
    # Build full prompt with optional context
    if context_code.strip():
        full_prompt = f"Here is some code for context:\n```\n{context_code}\n```\n\nUser request: {prompt}"
    else:
        full_prompt = prompt

    # Show user message
    st.chat_message("user").markdown(prompt)  # show original prompt without context in UI
    st.session_state.messages.append({"role": "user", "content": prompt})
    add_message("user", prompt)

    # Generate response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                # Build conversation history for the model (last few exchanges for context)
                # We'll send only the last 10 messages to avoid token waste, plus the system prompt.
                conversation = [
                    {"role": "system", "content": "You are an expert software engineer. Write clean, well-commented code. Provide only the code unless the user asks for an explanation. If the user provides context code, use it to inform your answer."}
                ]
                # Add last 10 messages from history (excluding the system welcome)
                recent_messages = [m for m in st.session_state.messages if m["role"] != "system"][-10:]
                conversation.extend(recent_messages)

                # The last user message is already in the history, but we need to ensure the model gets the
                # full prompt with context. We'll replace the last user message with the full prompt.
                conversation[-1]["content"] = full_prompt

                completion = groq_client.chat.completions.create(
                    model="llama-3.1-70b-versatile",
                    messages=conversation,
                    temperature=0.2,
                    max_tokens=4000,
                )
                reply = completion.choices[0].message.content
                render_message(reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})
                add_message("assistant", reply)
            except Exception as e:
                error_msg = f"❌ Error: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
                add_message("assistant", error_msg)