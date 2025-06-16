import streamlit as st
import os
from authlib.integrations.requests_client import OAuth2Session
from dotenv import load_dotenv
import sqlite3
from hashlib import sha256

load_dotenv()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

DB = "expense_tracker.db"

# ---------------- UTILITY ----------------
def get_connection():
    return sqlite3.connect(DB, check_same_thread=False)

def create_user(username, password, email):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        password_hash = sha256(password.encode()).hexdigest() if password else ""
        cursor.execute("INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
                       (username, password_hash, email))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def login_user(identifier, password):
    conn = get_connection()
    cursor = conn.cursor()
    if password:
        cursor.execute("SELECT id FROM users WHERE (username=? OR email=?) AND password_hash=?",
                       (identifier, identifier, sha256(password.encode()).hexdigest()))
    else:
        cursor.execute("SELECT id FROM users WHERE email=? AND password_hash=''", (identifier,))
    user = cursor.fetchone()
    conn.close()
    return user[0] if user else None

# ---------------- STREAMLIT AUTH ----------------
def get_auth_session():
    return OAuth2Session(
        GOOGLE_CLIENT_ID,
        GOOGLE_CLIENT_SECRET,
        scope="openid email profile",
        redirect_uri=REDIRECT_URI
    )

def login_with_google():
    auth = get_auth_session()
    uri, state = auth.authorization_url(AUTH_URL, access_type="offline", prompt="consent")
    st.session_state.oauth_state = state
    st.markdown(f"[Click here to login with Google]({uri})")

# ---------------- MAIN ----------------
if "user_id" not in st.session_state:
    st.session_state.user_id = None

if st.session_state.user_id is None:
    st.title("Login to Expense Tracker")

    # Regular Login
    st.subheader("Login with Username")
    identifier = st.text_input("Username or Email")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        uid = login_user(identifier, password)
        if uid:
            st.session_state.user_id = uid
            st.rerun()
        else:
            st.error("Invalid credentials")

    # Google OAuth
    st.markdown("---")
    st.subheader("Or Login with Google")
    login_with_google()

    # Handle redirect
    query_params = st.experimental_get_query_params()
    if "code" in query_params:
        code = query_params["code"][0]
        auth = get_auth_session()
        token = auth.fetch_token(TOKEN_URL, code=code)
        user_info = auth.get(USERINFO_URL).json()
        email = user_info["email"]
        name = user_info.get("name", "google_user")

        uid = login_user(email, "")
        if not uid:
            create_user(name, "", email)
            uid = login_user(email, "")
        if uid:
            st.session_state.user_id = uid
            st.success(f"Welcome {name}!")
            st.experimental_set_query_params()  # Clean URL
            st.rerun()

else:
    st.title("Welcome to the Expense Tracker")
    st.write("You're logged in!")
    if st.button("Logout"):
        st.session_state.user_id = None
        st.experimental_set_query_params()
        st.rerun()
