import streamlit as st
from dotenv import load_dotenv
import os
import sqlite3
from datetime import datetime, date
import pandas as pd
import requests
import json
import time

# Load environment
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
SQLITE_DB = os.getenv("SQLITE_DB", "dayforge.db")

# === Gemini client code ===
USE_GOOGLE_GENAI = False
try:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    USE_GOOGLE_GENAI = True
except Exception as e:
    st.error(f"Failed to load Gemini: {e}")
    USE_GOOGLE_GENAI = False

def call_gemini(prompt, max_tokens=512, temperature=0.2):
    if not GEMINI_API_KEY:
        return "❌ Gemini API key not found. Please check your .env file."
    
    if not USE_GOOGLE_GENAI:
        return "❌ Gemini SDK not available. Please install google-generativeai."
    
    try:
        # Using the correct Gemini 2.5 Flash model
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                top_p=0.95
            )
        )
        
        # Check if response was blocked
        if not response.parts:
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                return f"❌ Response blocked: {response.prompt_feedback.block_reason}"
            return "❌ No response generated. The content may have been blocked by safety filters."
        
        return response.text
        
    except Exception as e:
        return f"❌ Gemini Error: {str(e)}"

# === SQLite persistence helpers ===
def get_db_conn():
    return sqlite3.connect(SQLITE_DB, check_same_thread=False)

def init_db():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        details TEXT,
        priority INTEGER DEFAULT 2,
        due_date TEXT,
        done INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        content TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount REAL,
        category TEXT,
        note TEXT,
        date TEXT DEFAULT (date('now'))
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS habits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        streak INTEGER DEFAULT 0,
        last_done DATE
    )""")
    conn.commit()
    return conn

conn = init_db()

# === Task/Notes/Expenses/Habits ===
def add_task(title, details, priority, due_date):
    cur = conn.cursor()
    cur.execute("INSERT INTO tasks (title, details, priority, due_date) VALUES (?, ?, ?, ?)",
                (title, details, priority, due_date))
    conn.commit()

def list_tasks():
    cur = conn.cursor()
    cur.execute("SELECT id, title, details, priority, due_date, done FROM tasks ORDER BY priority, due_date")
    return cur.fetchall()

def toggle_task_done(task_id, done):
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET done=? WHERE id=?", (1 if done else 0, task_id))
    conn.commit()

def delete_task(task_id):
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.commit()

def save_note(title, content):
    cur = conn.cursor()
    cur.execute("INSERT INTO notes (title, content) VALUES (?, ?)", (title, content))
    conn.commit()

def get_notes():
    cur = conn.cursor()
    cur.execute("SELECT id, title, content, created_at FROM notes ORDER BY created_at DESC")
    return cur.fetchall()

def add_expense(amount, category, note):
    cur = conn.cursor()
    cur.execute("INSERT INTO expenses (amount, category, note) VALUES (?, ?, ?)", (amount, category, note))
    conn.commit()

def get_expenses():
    cur = conn.cursor()
    cur.execute("SELECT id, amount, category, note, date FROM expenses ORDER BY date DESC")
    return cur.fetchall()

def add_habit(name):
    cur = conn.cursor()
    cur.execute("INSERT INTO habits (name) VALUES (?)", (name,))
    conn.commit()

def list_habits():
    cur = conn.cursor()
    cur.execute("SELECT id, name, streak, last_done FROM habits ORDER BY id")
    return cur.fetchall()

def mark_habit_done(habit_id):
    cur = conn.cursor()
    today = date.today().isoformat()
    cur.execute("SELECT last_done, streak FROM habits WHERE id=?", (habit_id,))
    r = cur.fetchone()
    if not r:
        return
    last_done, streak = r
    if last_done == today:
        return
    new_streak = streak + 1 if last_done else 1
    cur.execute("UPDATE habits SET streak=?, last_done=? WHERE id=?", (new_streak, today, habit_id))
    conn.commit()

# === Weather / Unsplash ===
def get_weather(city):
    if not OPENWEATHER_API_KEY:
        return {"error": "OPENWEATHER_API_KEY not set"}
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": OPENWEATHER_API_KEY, "units": "metric"}
    r = requests.get(url, params=params, timeout=10)
    if r.status_code == 200:
        return r.json()
    return {"error": f"Weather API error {r.status_code}"}

def unsplash_search(query, per_page=1):
    if not UNSPLASH_ACCESS_KEY:
        return None
    url = "https://api.unsplash.com/search/photos"
    headers = {"Accept-Version": "v1", "Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    params = {"query": query, "per_page": per_page}
    r = requests.get(url, headers=headers, params=params, timeout=10)
    if r.status_code == 200:
        data = r.json()
        if data.get("results"):
            return data["results"][0]["urls"]["regular"]
    return None

# === Streamlit UI ===
st.set_page_config(page_title="DayForge", layout="wide", page_icon="🔥")
st.sidebar.title("🔥 DayForge")
page = st.sidebar.radio("Navigate", [
    "AI Chat", "Daily Planner", "Smart Notes", "Expenses", "Habits",
    "Weather", "Images", "Recipes", "Finance", "Resume / Cover Letter"
])
st.title("🔥 DayForge — Your AI Daily Assistant")

# --- AI Chat ---
if page == "AI Chat":
    st.header("AI Chat — powered by Gemini")
    prompt = st.text_area("Ask DayForge", placeholder="Type your question here...")
    temp = st.slider("Creativity (temperature)", 0.0, 1.0, 0.25)
    max_tokens = st.slider("Max tokens", 50, 1500, 400)
    
    if st.button("Ask Gemini"):
        if not prompt.strip():
            st.warning("Please enter a question.")
        elif not GEMINI_API_KEY:
            st.error("Gemini API key not configured. Please check your .env file.")
        else:
            with st.spinner("Thinking..."):
                out = call_gemini(prompt, max_tokens=max_tokens, temperature=temp)
                st.subheader("Gemini answer:")
                st.write(out)

# --- Daily Planner ---
elif page == "Daily Planner":
    st.header("Daily Planner — Tasks")
    with st.form("add_task_form", clear_on_submit=True):
        title = st.text_input("Title")
        details = st.text_area("Details")
        priority = st.select_slider("Priority (1=high)", [1,2,3], value=2)
        due = st.date_input("Due date", value=None)
        submitted = st.form_submit_button("Add Task")
        if submitted and title.strip():
            add_task(title, details, priority, due.isoformat() if due else None)
            st.success("Task added.")
        elif submitted:
            st.warning("Please enter a task title.")

    rows = list_tasks()
    if rows:
        for tid, ttitle, tdetails, tpriority, tdue, tdone in rows:
            cols = st.columns([.05, .7, .1, .15])
            with cols[0]:
                c = st.checkbox("", value=bool(tdone), key=f"done_{tid}")
                if c != bool(tdone):
                    toggle_task_done(tid, c)
            with cols[1]:
                st.markdown(f"**{ttitle}**  \n{tdetails if tdetails else ''}")
            with cols[2]:
                st.markdown(f"Priority: {tpriority}")
            with cols[3]:
                if tdue:
                    st.markdown(f"Due: {tdue}")
                if st.button("Delete", key=f"del_{tid}"):
                    delete_task(tid)
                    st.rerun()
    else:
        st.info("No tasks yet. Add your first task above!")

# --- Smart Notes ---
elif page == "Smart Notes":
    st.header("Smart Notes")
    note_title = st.text_input("Note title")
    note_content = st.text_area("Note content")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save Note") and note_title.strip():
            save_note(note_title, note_content)
            st.success("Note saved!")
        elif st.button("Save Note"):
            st.warning("Please enter a note title.")
    with col2:
        if st.button("Summarize with Gemini") and note_content.strip():
            prompt = f"Please summarize this note and extract key action items: {note_content}"
            out = call_gemini(prompt, max_tokens=300)
            st.subheader("Summary & Actions")
            st.write(out)
        elif st.button("Summarize with Gemini"):
            st.warning("Please enter note content to summarize.")

    notes = get_notes()
    if notes:
        for nid, nt, nc, ncreated in notes:
            with st.expander(f"{nt} — {ncreated}"):
                st.write(nc)
                if st.button("Delete Note", key=f"del_note_{nid}"):
                    cur = conn.cursor()
                    cur.execute("DELETE FROM notes WHERE id=?", (nid,))
                    conn.commit()
                    st.rerun()
    else:
        st.info("No notes yet. Create your first note above!")

# --- Expenses ---
elif page == "Expenses":
    st.header("Expenses")
    amt = st.number_input("Amount", min_value=0.0, step=0.01)
    cat = st.text_input("Category", placeholder="e.g., Food, Transport, Entertainment")
    note = st.text_input("Note", placeholder="Optional description")
    if st.button("Add Expense") and amt > 0 and cat.strip():
        add_expense(amt, cat, note)
        st.success("Expense added!")
    elif st.button("Add Expense"):
        st.warning("Please enter amount and category.")

    ex = get_expenses()
    if ex:
        df = pd.DataFrame(ex, columns=["id", "amount","category","note","date"])
        st.subheader("Expense History")
        st.dataframe(df)
        
        # Show summary
        total = df['amount'].sum()
        st.metric("Total Expenses", f"${total:.2f}")
    else:
        st.info("No expenses recorded yet.")

# --- Habits ---
elif page == "Habits":
    st.header("Habit Tracker")
    new_habit = st.text_input("Add habit", placeholder="e.g., Exercise, Read, Meditate")
    if st.button("Add Habit") and new_habit.strip():
        add_habit(new_habit)
        st.success("Habit added!")
    elif st.button("Add Habit"):
        st.warning("Please enter a habit name.")

    habits = list_habits()
    if habits:
        st.subheader("Your Habits")
        for hid, name, streak, last_done in habits:
            cols = st.columns([.6,.15,.15,.1])
            cols[0].markdown(f"**{name}**")
            cols[1].markdown(f"🔥 {streak} days")
            cols[2].markdown(f"Last: {last_done if last_done else 'Never'}")
            with cols[3]:
                if st.button("✓", key=f"habit_{hid}"):
                    mark_habit_done(hid)
                    st.rerun()
    else:
        st.info("No habits yet. Add your first habit above!")

# --- Weather ---
elif page == "Weather":
    st.header("Weather")
    city = st.text_input("City", placeholder="Enter city name")
    if st.button("Get Weather") and city.strip():
        with st.spinner("Fetching weather..."):
            w = get_weather(city)
            if w.get("error"):
                st.error(w["error"])
            else:
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Temperature", f"{w['main']['temp']}°C")
                with col2:
                    st.metric("Humidity", f"{w['main']['humidity']}%")
                with col3:
                    st.metric("Condition", f"{w['weather'][0]['description'].title()}")
    elif st.button("Get Weather"):
        st.warning("Please enter a city name.")

# --- Images ---
elif page == "Images":
    st.header("Image Search")
    q = st.text_input("Search images", placeholder="Enter search term")
    if st.button("Search") and q.strip():
        with st.spinner("Searching for images..."):
            img_url = unsplash_search(q)
            if img_url:
                st.image(img_url, caption=q, use_column_width=True)
            else:
                st.error("No image found or API key not configured.")
    elif st.button("Search"):
        st.warning("Please enter a search term.")

# --- Recipes ---
elif page == "Recipes":
    st.header("Recipe Ideas")
    ingr = st.text_input("Ingredients", placeholder="What ingredients do you have?")
    if st.button("Get Recipe") and ingr.strip():
        with st.spinner("Generating recipe..."):
            prompt = f"Suggest a simple, practical recipe using these ingredients: {ingr}. Include preparation steps and cooking time."
            st.write(call_gemini(prompt, max_tokens=800))
    elif st.button("Get Recipe"):
        st.warning("Please enter some ingredients.")

# --- Finance ---
elif page == "Finance":
    st.header("Finance Assistant")
    q = st.text_input("Your finance question", placeholder="Ask about budgeting, investing, savings, etc.")
    if st.button("Ask Finance Bot") and q.strip():
        with st.spinner("Consulting finance advisor..."):
            prompt = f"As a professional financial advisor, provide practical advice for: {q}. Keep it concise and actionable."
            st.write(call_gemini(prompt))
    elif st.button("Ask Finance Bot"):
        st.warning("Please enter a finance question.")

# --- Resume / Cover Letter ---
elif page == "Resume / Cover Letter":
    st.header("Resume / Cover Letter Generator")
    role = st.text_input("Role applying for", placeholder="e.g., Software Engineer, Marketing Manager")
    bullets = st.text_area("Your achievements / bullets", placeholder="List your key achievements, skills, and experiences")
    tone = st.selectbox("Tone", ["Professional","Concise","Confident", "Enthusiastic"])
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Generate Cover Letter") and role.strip() and bullets.strip():
            with st.spinner("Writing cover letter..."):
                prompt = f"Write a {tone.lower()} cover letter for a {role} position using these achievements: {bullets}. Make it professional and tailored to the role."
                st.write(call_gemini(prompt, max_tokens=1000))
        elif st.button("Generate Cover Letter"):
            st.warning("Please enter role and achievements.")
    
    with col2:
        if st.button("Generate Resume Summary") and role.strip() and bullets.strip():
            with st.spinner("Creating resume summary..."):
                prompt = f"Write a compelling 3-4 line resume summary for a {role} position highlighting these achievements: {bullets}. Make it impactful and concise."
                st.write(call_gemini(prompt, max_tokens=300))
        elif st.button("Generate Resume Summary"):
            st.warning("Please enter role and achievements.")

# Footer
st.sidebar.markdown("---")
st.sidebar.caption("DayForge • Gemini-powered • Local SQLite storage")

# Configuration check
st.sidebar.markdown("---")
st.sidebar.subheader("Configuration Status")
if GEMINI_API_KEY:
    st.sidebar.success("✅ Gemini API: Configured")
else:
    st.sidebar.error("❌ Gemini API: Missing")

if OPENWEATHER_API_KEY:
    st.sidebar.success("✅ Weather API: Configured")
else:
    st.sidebar.warning("⚠️ Weather API: Missing")

if UNSPLASH_ACCESS_KEY:
    st.sidebar.success("✅ Unsplash API: Configured")
else:
    st.sidebar.warning("⚠️ Unsplash API: Missing")
    
