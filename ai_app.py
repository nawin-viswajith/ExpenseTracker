# expense_tracker_oauth.py

import streamlit as st
import pandas as pd
import os
from google.oauth2 import id_token
from google.auth.transport import requests
from urllib.parse import urlencode
import sqlite3
from datetime import datetime

CLIENT_ID = st.secrets["client_id"]
REDIRECT_URI = st.secrets["redirect_uri"]

# ------------------------ Google OAuth ------------------------
def get_google_login_url():
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "token",
        "scope": "openid email profile",
        "include_granted_scopes": "true",
        "prompt": "select_account"
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def parse_fragment(fragment):
    try:
        token = fragment.split("access_token=")[1].split("&")[0]
        return token
    except:
        return None


def verify_token(access_token):
    try:
        idinfo = id_token.verify_oauth2_token(
            access_token, requests.Request(), CLIENT_ID
        )
        return idinfo
    except:
        return None

# ------------------------ Database ------------------------
DB = "expenses.db"

def init_db():
    conn = sqlite3.connect(DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS expenses (
                        user_email TEXT,
                        amount REAL,
                        category TEXT,
                        date TEXT,
                        is_necessary INTEGER,
                        description TEXT
                    )''')
    conn.commit()
    conn.close()


def add_expense(user_email, amount, category, date, is_necessary, description):
    conn = sqlite3.connect(DB)
    conn.execute("""
        INSERT INTO expenses (user_email, amount, category, date, is_necessary, description)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (user_email, amount, category, date, is_necessary, description))
    conn.commit()
    conn.close()


def get_user_expenses(user_email):
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT * FROM expenses WHERE user_email=? ORDER BY date DESC", conn, params=(user_email,))
    conn.close()
    return df

# ------------------------ Streamlit App ------------------------
st.set_page_config(page_title="Expense Tracker", layout="centered")
st.title("📊 Google Authenticated Expense Tracker")

init_db()

fragment = st.query_params.get("fragment")
if fragment and len(fragment) > 0:
    access_token = parse_fragment(fragment[0])
    if access_token:
        st.session_state["access_token"] = access_token

if "access_token" not in st.session_state:
    st.markdown(f"[Login with Google]({get_google_login_url()})")
    st.stop()

user_info = verify_token(st.session_state["access_token"])
if not user_info:
    st.error("Invalid login. Please try again.")
    st.markdown(f"[Login with Google]({get_google_login_url()})")
    st.stop()

user_email = user_info['email']
st.success(f"Logged in as {user_email}")

st.subheader("Add Expense")
with st.form("add_form"):
    amt = st.number_input("Amount", min_value=0.0)
    cat = st.selectbox("Category", ["Food", "Transport", "Utilities", "Entertainment", "Misc"])
    dt = st.date_input("Date", value=datetime.now().date())
    nec = st.checkbox("Is it necessary?", value=True)
    desc = st.text_input("Description")
    if st.form_submit_button("Add"):
        add_expense(user_email, amt, cat, dt.strftime("%Y-%m-%d"), int(nec), desc)
        st.success("Expense added.")

st.subheader("My Expenses")
df = get_user_expenses(user_email)
st.dataframe(df)

st.download_button("Download CSV", df.to_csv(index=False), file_name="my_expenses.csv")
