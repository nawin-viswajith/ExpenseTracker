# expense_tracker_app.py

import os
import sqlite3
from datetime import datetime
from urllib.parse import urlencode

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from babel.numbers import format_currency
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests


# ────────────────────────────────────────────────────────────────────
# 1) READ SECRETS / CONFIGURATION
# ────────────────────────────────────────────────────────────────────

# These values come from Streamlit Cloud's Secrets (Settings → Secrets)
GOOGLE_CLIENT_ID     = st.secrets["client_id"]
GOOGLE_CLIENT_SECRET = st.secrets["client_secret"]
REDIRECT_URI         = st.secrets["redirect_uri"]
# e.g. "https://trackyourexpensenow.streamlit.app"

# Folder to hold each user’s SQLite file:
USER_DB_FOLDER = "expense_user_data"
os.makedirs(USER_DB_FOLDER, exist_ok=True)


# ────────────────────────────────────────────────────────────────────
# 2) GOOGLE OAUTH (authorization‐code flow)
# ────────────────────────────────────────────────────────────────────

def build_google_auth_url() -> str:
    """
    Build Google’s OAuth2 URL for 'response_type=code'. 
    When clicked, user sees Google consent screen; after they allow, 
    Google redirects back with ?code=ABC... to our REDIRECT_URI.
    """
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",              # authorization‐code flow
        "scope":         "openid email profile",
        "access_type":   "offline",           # ask for refresh_token if you ever need it
        "prompt":        "select_account",    # always prompt account selector
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def exchange_code_for_token(code: str) -> dict:
    """
    Given the 'code' from Google, exchange it for a JSON containing
    access_token, id_token, refresh_token, etc.
    """
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code":          code,
        "client_id":     GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    }
    resp = requests.post(token_url, data=data)
    # If something is wrong (e.g. redirect URI mismatch), resp.status_code != 200, 
    # so .raise_for_status() will throw an HTTPError with details.
    resp.raise_for_status()
    return resp.json()


def verify_token(id_token_str: str) -> dict:
    """
    Verify the OAuth2 ID token (JWT) and return the userinfo dictionary. 
    On failure, returns None.
    """
    try:
        idinfo = id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            GOOGLE_CLIENT_ID
        )
        return idinfo
    except Exception:
        return None


# ────────────────────────────────────────────────────────────────────
# 3) PER‐USER SQLITE DATABASE SETUP
# ────────────────────────────────────────────────────────────────────

def init_schema_if_missing(conn: sqlite3.Connection):
    """
    Create the 'expenses' table in this user's DB file if it doesn't exist.
    """
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            amount       REAL    NOT NULL,
            category     TEXT    NOT NULL,
            date         TEXT    NOT NULL,
            is_necessary INTEGER NOT NULL,
            description  TEXT
        )
    """)
    conn.commit()


def get_connection_for_email(email: str) -> sqlite3.Connection:
    """
    Returns a sqlite3.Connection for this user’s file.
    We sanitize the email (replace @ → _at_, . → _), so the filename is safe.
    """
    safe_fn = email.replace("@", "_at_").replace(".", "_")
    db_path = os.path.join(USER_DB_FOLDER, f"{safe_fn}.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    init_schema_if_missing(conn)
    return conn


def add_expense(email: str, amount: float, category: str, date: str, is_necessary: int, description: str):
    """
    Insert a new expense row into this user’s SQLite file.
    """
    conn = get_connection_for_email(email)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO expenses (amount, category, date, is_necessary, description)
        VALUES (?, ?, ?, ?, ?)
    """, (amount, category, date, is_necessary, description))
    conn.commit()
    conn.close()


def get_expenses_df(email: str) -> pd.DataFrame:
    """
    Fetch all expenses for this user, ordered by date descending.
    Returns an empty DataFrame if no rows exist.
    """
    conn = get_connection_for_email(email)
    df = pd.read_sql_query("SELECT * FROM expenses ORDER BY date DESC", conn)
    conn.close()
    return df


# ────────────────────────────────────────────────────────────────────
# 4) STREAMLIT APPLICATION
# ────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Expense Tracker", layout="centered")
st.title("📊 Google‐Authenticated Expense Tracker")

# ─ 4a) Has Google already redirected back with ?code=… ?
query_params = st.experimental_get_query_params()
if "code" in query_params:
    code = query_params["code"][0]
    try:
        token_data = exchange_code_for_token(code)
        # In authorization‐code flow, Google’s response JSON includes:
        # {
        #   "access_token":  "ya29.a0Af…",
        #   "expires_in":    3599,
        #   "refresh_token": "1//0g…",      # only on first consent
        #   "scope":         "openid email profile",
        #   "token_type":    "Bearer",
        #   "id_token":      "<JWT here>"
        # }
        #
        # We need the id_token (JWT) to verify the user’s identity (it contains email, sub, etc).
        id_token_str = token_data.get("id_token")
        user_info = verify_token(id_token_str)
        if user_info is None:
            st.error("❌ Failed to verify ID token. Please try logging in again.")
            st.stop()

        # Now we have a verified user. Store their email (and entire user_info) in session_state.
        st.session_state["google_email"]     = user_info.get("email")
        st.session_state["google_user_info"] = user_info

        # Clear the code from the URL so it doesn't loop
        st.experimental_set_query_params()
        st.experimental_rerun()

    except requests.HTTPError as e:
        # If Google returned a non‐200 (e.g. 403 redirect_uri_mismatch), show the JSON error:
        err_json = e.response.json() if e.response is not None else str(e)
        st.error(f"Google token exchange failed: {err_json}")
        st.stop()

# ─ 4b) If we do not yet have "google_email" in session_state, show Login button
if "google_email" not in st.session_state:
    st.markdown("## Please sign in with Google to continue")
    login_url = build_google_auth_url()
    st.markdown(f"<a href='{login_url}'><button style='padding:10px 20px; font-size:16px;'>🔒 Login with Google</button></a>",
                unsafe_allow_html=True)
    st.stop()

# ─ 4c) We now have a logged‐in user
user_email = st.session_state["google_email"]
user_name  = st.session_state["google_user_info"].get("name", "")
st.success(f"✔️ Logged in as: {user_email}")

# ───────────────────────────────────────────────────────────────────
# 5) SIDEBAR: SUMMARY + LOGOUT
# ───────────────────────────────────────────────────────────────────

with st.sidebar:
    df_sidebar = get_expenses_df(user_email)

    st.markdown("### User Summary")
    st.write(f"**Email:** {user_email}")
    if user_name:
        st.write(f"**Name:**  {user_name}")

    if not df_sidebar.empty:
        total = df_sidebar["amount"].sum()
        st.write(f"**Total Spent:** {format_currency(total, 'INR', locale='en_IN')}")
        st.write(f"**Entries:** {len(df_sidebar)}")
        st.write(f"**Avg per Entry:** {format_currency(df_sidebar['amount'].mean(), 'INR', locale='en_IN')}")
    else:
        st.write("No expenses yet.")

    st.markdown("---")
    if st.button("🚪 Logout"):
        # Clear session_state and rerun
        for key in ["google_email", "google_user_info"]:
            if key in st.session_state:
                del st.session_state[key]
        st.experimental_rerun()


# ───────────────────────────────────────────────────────────────────
# 6) MAIN TABS: Dashboard / Add Expense / Reports / All Entries
# ───────────────────────────────────────────────────────────────────

tabs = st.tabs(["Dashboard", "Add Expense", "Reports", "All Entries"])

# ───────────────
# Tab 0: Dashboard
# ───────────────
with tabs[0]:
    st.subheader("Dashboard Overview")
    df_dash = get_expenses_df(user_email)

    if df_dash.empty:
        st.info("No expense data to display. Go to “Add Expense” to get started.")
    else:
        df_dash["date"] = pd.to_datetime(df_dash["date"])

        # 1) Smart Suggestions
        total    = df_dash["amount"].sum()
        necessary   = df_dash[df_dash["is_necessary"] == 1]["amount"].sum()
        non_need    = total - necessary
        ratio       = non_need / total if total > 0 else 0.0

        if ratio > 0.4:
            st.warning("💡 You are spending over 40% on non‐necessary expenses. Consider reviewing luxuries.")
        avg_monthly = df_dash.groupby(df_dash["date"].dt.to_period("M"))["amount"].sum().mean()
        if avg_monthly > 0 and ratio > 0.3:
            est_saves = ratio * avg_monthly * 0.25
            st.success(f"Tip: You could save around {format_currency(est_saves, 'INR', locale='en_IN')} per month by reducing luxuries.")

        st.markdown("---")

        # 2) Key Metrics
        total_spent = total
        avg_spent   = df_dash["amount"].mean()
        max_spent   = df_dash["amount"].max()
        min_spent   = df_dash["amount"].min()

        c1, c2 = st.columns(2)
        with c1:
            st.metric("Total Spent",       format_currency(total_spent, "INR", locale="en_IN"))
            st.metric("Highest Expense",   format_currency(max_spent,   "INR", locale="en_IN"))
        with c2:
            st.metric("Average per Entry", format_currency(avg_spent,   "INR", locale="en_IN"))
            st.metric("Lowest Expense",    format_currency(min_spent,   "INR", locale="en_IN"))

        st.markdown("---")

        # 3) Category‐Wise Pie Chart
        cat_data = df_dash.groupby("category")["amount"].sum().reset_index()
        cat_data["formatted"] = cat_data["amount"].apply(lambda x: format_currency(x, "INR", locale="en_IN"))

        pie = px.pie(
            cat_data,
            names="category",
            values="amount",
            hole=0.3,
            custom_data=["formatted"],
        )
        pie.update_traces(
            textinfo="percent+label",
            hovertemplate="%{label}<br>Total: %{customdata[0]}<extra></extra>"
        )
        st.plotly_chart(pie, use_container_width=True)

        st.markdown("---")

        # 4) Necessary vs Non‐Necessary Donut
        necessity_data = df_dash.groupby("is_necessary")["amount"].sum().reset_index()
        necessity_data["label"] = necessity_data["is_necessary"].map({1: "Necessary", 0: "Non‐Necessary"})

        donut = px.pie(
            necessity_data,
            names="label",
            values="amount",
            hole=0.4,
        )
        donut.update_traces(
            textinfo="percent+label",
            hovertemplate="%{label}: ₹%{value:,.2f}<extra></extra>"
        )
        st.plotly_chart(donut, use_container_width=True)

        st.markdown("---")

        # 5) Top 5 Highest Expenses
        st.markdown("### Top 5 Highest Expenses")
        top5 = df_dash.sort_values("amount", ascending=False).head(5)
        st.dataframe(top5[["amount", "category", "date", "description"]])

# ───────────────
# Tab 1: Add Expense
# ───────────────
with tabs[1]:
    st.subheader("Add New Expense")
    with st.form("expense_form"):
        amt  = st.number_input("Amount", min_value=0.0, step=1.0)
        cat  = st.selectbox("Category", ["Food", "Transport", "Utilities", "Entertainment", "Miscellaneous"])
        dt   = st.date_input("Date", value=datetime.now().date())
        nec  = st.checkbox("Is this necessary?", value=True)
        desc = st.text_input("Short Description")

        if st.form_submit_button("Add Expense"):
            add_expense(
                user_email,
                float(amt),
                cat,
                dt.strftime("%Y-%m-%d"),
                int(nec),
                desc
            )
            st.success("✅ Expense added successfully!")

# ───────────────
# Tab 2: Reports
# ───────────────
with tabs[2]:
    st.subheader("Reports / Insights")
    df_rep = get_expenses_df(user_email)

    if df_rep.empty:
        st.info("No data yet. Go to ‘Add Expense’ to record spending.")
    else:
        df_rep["date"]   = pd.to_datetime(df_rep["date"])
        df_rep["Month"]  = df_rep["date"].dt.strftime("%B %Y")
        df_rep["Weekday"] = df_rep["date"].dt.day_name()

        # a) Spending Habit by Category
        st.markdown("### Spending Habit by Category")
        habit_summary = df_rep.groupby("category")["amount"].agg(["count", "sum", "mean"]).reset_index()
        habit_summary.columns = ["Category", "Entries", "Total Spent", "Average Spent"]
        habit_summary["Total Spent"]   = habit_summary["Total Spent"].apply(lambda x: format_currency(x, "INR", locale="en_IN"))
        habit_summary["Average Spent"] = habit_summary["Average Spent"].apply(lambda x: format_currency(x, "INR", locale="en_IN"))
        st.dataframe(habit_summary)

        st.markdown("---")

        # b) Monthly Summary Table
        st.markdown("### Monthly Summary Table")
        monthly_summary = df_rep.groupby(df_rep["date"].dt.to_period("M"))["amount"].agg(
            ["count", "sum", "mean", "max", "min"]
        ).reset_index()
        monthly_summary.columns = ["MonthPeriod", "Total Entries", "Total Spent", "Average", "Max", "Min"]
        monthly_summary["Month"] = monthly_summary["MonthPeriod"].dt.strftime("%B %Y")
        for col in ["Total Spent", "Average", "Max", "Min"]:
            monthly_summary[col] = monthly_summary[col].apply(lambda x: format_currency(x, "INR", locale="en_IN"))
        st.dataframe(monthly_summary[["Month", "Total Entries", "Total Spent", "Average", "Max", "Min"]])

        st.markdown("---")

        # c) Category Distribution per Month (Bar Chart)
        st.markdown("### Spending per Category Over Time")
        monthly_cat = df_rep.groupby([df_rep["date"].dt.to_period("M"), "category"])["amount"].sum().reset_index()
        monthly_cat["Month"] = monthly_cat["date"].dt.to_timestamp()
        bar_fig = px.bar(
            monthly_cat,
            x="Month",
            y="amount",
            color="category",
            barmode="group",
            labels={"amount": "Total Spent", "Month": "Month"},
            title="Spending per Category Over Time"
        )
        st.plotly_chart(bar_fig, use_container_width=True)

        st.markdown("---")

        # d) Average Spend by Weekday (Bar + Text)
        st.markdown("### Average Spend by Weekday (with Necessity %)")
        weekday_data = df_rep.groupby("Weekday").agg(
            total_amount=('amount', 'sum'),
            avg_amount=('amount', 'mean'),
            total_necess=('is_necessary', 'sum'),
            count=('is_necessary', 'count')
        ).reindex(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
        weekday_data["necessity_ratio"] = (weekday_data["total_necess"] / weekday_data["count"]) * 100

        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=weekday_data.index,
            y=weekday_data["avg_amount"],
            text=[f"Necessity %: {n:.1f}%" for n in weekday_data["necessity_ratio"]],
            hovertemplate="%{x}<br>Avg Spend: ₹%{y:.2f}<extra></extra>",
        ))
        fig.update_layout(
            title="Average Spending by Day of Week",
            xaxis_title="Day",
            yaxis_title="Avg Spend (₹)",
            template="plotly_white"
        )
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        # e) Average Monthly Expense Trend (Line Chart)
        st.markdown("### Average Monthly Expense Over Time")
        monthly_avg = df_rep.groupby(df_rep["date"].dt.to_period("M"))["amount"].mean().reset_index()
        monthly_avg["month_str"] = monthly_avg["date"].dt.strftime("%b %Y")
        monthly_avg["MonthTs"]   = monthly_avg["date"].dt.to_timestamp()
        line_fig = px.line(
            monthly_avg,
            x="month_str",
            y="amount",
            markers=True,
            title="Average Monthly Expense Over Time"
        )
        line_fig.update_layout(
            xaxis_title="Month",
            yaxis_title="Average Expense (₹)",
            template="plotly_white",
            xaxis_rangeslider_visible=True,
            xaxis=dict(
                type="category",
                range=[monthly_avg["month_str"].iloc[-12], monthly_avg["month_str"].iloc[-1]],
                rangeselector=dict(
                    buttons=[
                        dict(count=12, label="Last 12M", step="month", stepmode="backward"),
                        dict(step="all", label="All")
                    ]
                )
            )
        )
        st.plotly_chart(line_fig, use_container_width=True)

        st.markdown("---")

        # f) Overall Category‐Wise Distribution (Donut)
        st.markdown("### Overall Category‐Wise Distribution")
        category_total = df_rep.groupby("category")["amount"].sum().reset_index()
        category_total["formatted"] = category_total["amount"].apply(lambda x: format_currency(x, "INR", locale="en_IN"))

        pie2 = px.pie(
            category_total,
            names="category",
            values="amount",
            hole=0.4,
            custom_data=["formatted"]
        )
        pie2.update_traces(
            textinfo="percent+label",
            hovertemplate="%{label}<br>Total: %{customdata[0]}<extra></extra>"
        )
        st.plotly_chart(pie2, use_container_width=True)

# ────────────────────────────────────────────────────────────────────
# Tab 3: All Entries
# ────────────────────────────────────────────────────────────────────
with tabs[3]:
    st.subheader("All Expense Entries")
    df_all = get_expenses_df(user_email)
    if df_all.empty:
        st.info("No expenses recorded yet.")
    else:
        st.dataframe(df_all)

# ────────────────────────────────────────────────────────────────────
# END OF APP
# ────────────────────────────────────────────────────────────────────
