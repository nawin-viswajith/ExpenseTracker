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


# ──────────────────────────
# 1) READ SECRETS / CONFIG
# ──────────────────────────

# In Streamlit Cloud → Settings → Secrets → add:
#   client_id     = "YOUR_GOOGLE_CLIENT_ID"
#   redirect_uri  = "https://trackyourexpensenow.streamlit.app"
#
# (Make sure the same URL is in Google Cloud Console’s Authorized redirect URIs.)

GOOGLE_CLIENT_ID = st.secrets["client_id"]
REDIRECT_URI     = st.secrets["redirect_uri"]

# Folder where each user’s DB file will live:
USER_DB_FOLDER = "expense_user_data"
os.makedirs(USER_DB_FOLDER, exist_ok=True)


# ──────────────────────────
# 2) GOOGLE OAUTH (implicit flow)
# ──────────────────────────

def get_google_login_url() -> str:
    """
    Build the Google OAuth “implicit” URL (response_type=token).
    When you click this link, Google will return an access_token
    in the URL fragment (after the ‘#’).
    """
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "token",            # implicit flow
        "scope":         "openid email profile",
        "prompt":        "select_account",    # always let user pick account
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

def parse_fragment(fragment: str) -> str:
    """
    Google returns:  https://app-url#access_token=XYZ&expires_in=3599&...
    We just split off “access_token=…”.
    """
    try:
        return fragment.split("access_token=")[1].split("&")[0]
    except Exception:
        return None

def verify_token(access_token: str) -> dict:
    """
    Verify the Google OAuth2 access token and return the userinfo dict.
    If invalid, returns None.
    """
    try:
        idinfo = id_token.verify_oauth2_token(
            access_token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID
        )
        return idinfo
    except Exception:
        return None


# ──────────────────────────
# 3) PER‐USER SQLITE SETUP
# ──────────────────────────

def init_schema_if_missing(conn):
    """
    Create the 'expenses' table if it doesn't exist in this new DB.
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
    Each user gets their own SQLite file, named by a sanitized version of email.
    e.g. "alice@example.com" → "alice_at_example_com.db"
    """
    safe_fn = email.replace("@", "_at_").replace(".", "_")
    db_path = os.path.join(USER_DB_FOLDER, f"{safe_fn}.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    init_schema_if_missing(conn)
    return conn

def add_expense(email: str, amount: float, category: str, date: str, is_necessary: int, description: str):
    """
    Insert a new expense into this user’s SQLite file.
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
    Fetch all expenses for this user, newest first.
    Returns an empty DataFrame if no rows yet.
    """
    conn = get_connection_for_email(email)
    df = pd.read_sql_query("SELECT * FROM expenses ORDER BY date DESC", conn)
    conn.close()
    return df


# ──────────────────────────
# 4) STREAMLIT APP
# ──────────────────────────

st.set_page_config(page_title="Expense Tracker", layout="centered")
st.title("📊 Google‐Authenticated Expense Tracker")

# 4a) See if Google returned an “access_token” in the URL fragment
fragment = st.query_params.get("fragment")
if fragment:
    token = parse_fragment(fragment[0])
    if token:
        st.session_state["access_token"] = token

# 4b) If we don’t yet have an access_token, show “Login with Google” link and STOP
if "access_token" not in st.session_state:
    st.markdown(f"[Login with Google]({get_google_login_url()})")
    st.stop()

# 4c) We have an access_token in session_state – verify it
user_info = verify_token(st.session_state["access_token"])
if not user_info:
    st.error("❌ Invalid or expired token. Please log in again.")
    st.markdown(f"[Login with Google]({get_google_login_url()})")
    st.stop()

# 4d) Extract the user’s email (and name if desired)
user_email = user_info.get("email")
user_name  = user_info.get("name", "")
st.success(f"✔️ Logged in as {user_email}")

# ──────────────────────────
# 5) SIDEBAR: SUMMARY & LOGOUT
# ──────────────────────────

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
    if st.button("Logout"):
        # Clear the OAuth token from session_state
        if "access_token" in st.session_state:
            del st.session_state["access_token"]
        st.experimental_rerun()


# ──────────────────────────
# 6) TABS: Dashboard / Add / Reports / All Entries
# ──────────────────────────

tabs = st.tabs(["Dashboard", "Add Expense", "Reports", "All Entries"])

# ────────────────
# TAB 0: Dashboard
# ────────────────
with tabs[0]:
    st.subheader("Dashboard Overview")
    df_dash = get_expenses_df(user_email)

    if df_dash.empty:
        st.info("No expense data to show. Go to “Add Expense” to begin.")
    else:
        # Ensure date column is datetime
        df_dash["date"] = pd.to_datetime(df_dash["date"])

        # 1) Smart Suggestions
        total       = df_dash["amount"].sum()
        necessary   = df_dash[df_dash["is_necessary"] == 1]["amount"].sum()
        non_need    = total - necessary
        ratio       = non_need / total if total > 0 else 0.0

        if ratio > 0.4:
            st.warning("💡 You are spending > 40% on non‐necessary items.")
        avg_monthly = df_dash.groupby(df_dash["date"].dt.to_period("M"))["amount"].sum().mean()

        if avg_monthly > 0 and ratio > 0.3:
            est_sav = ratio * avg_monthly * 0.25
            st.success(f"Tip: Save around {format_currency(est_sav, 'INR', locale='en_IN')} per month by cutting luxury spends.")

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

        # 5) Top 5 Highest Expenses Table
        st.markdown("### Top 5 Highest Expenses")
        top5 = df_dash.sort_values("amount", ascending=False).head(5)
        st.dataframe(top5[["amount", "category", "date", "description"]])

# ────────────────
# TAB 1: Add Expense
# ────────────────
with tabs[1]:
    st.subheader("Add New Expense")
    with st.form("expense_form"):
        amt       = st.number_input("Amount", min_value=0.0, step=1.0)
        cat       = st.selectbox("Category", ["Food", "Transport", "Utilities", "Entertainment", "Miscellaneous"])
        dt        = st.date_input("Date", value=datetime.now().date())
        nec       = st.checkbox("Is this a necessary expense?", value=True)
        desc      = st.text_input("Short Description")

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

# ────────────────
# TAB 2: Reports
# ────────────────
with tabs[2]:
    st.subheader("Reports / Insights")
    df_rep = get_expenses_df(user_email)

    if df_rep.empty:
        st.info("No data to generate reports. Go to ‘Add Expense’ to log some spending.")
    else:
        df_rep["date"] = pd.to_datetime(df_rep["date"])
        df_rep["Month"]   = df_rep["date"].dt.strftime("%B %Y")
        df_rep["Weekday"] = df_rep["date"].dt.day_name()

        # 2a) Spending Habit Table (Category Aggregation)
        st.markdown("### Spending Habit by Category")
        habit_summary = df_rep.groupby("category")["amount"].agg(["count", "sum", "mean"]).reset_index()
        habit_summary.columns = ["Category", "Entries", "Total Spent", "Average Spent"]
        habit_summary["Total Spent"]   = habit_summary["Total Spent"].apply(lambda x: format_currency(x, "INR", locale="en_IN"))
        habit_summary["Average Spent"] = habit_summary["Average Spent"].apply(lambda x: format_currency(x, "INR", locale="en_IN"))
        st.dataframe(habit_summary)

        st.markdown("---")

        # 2b) Monthly Summary Table
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

        # 2c) Category Distribution per Month (Bar Chart)
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

        # 2d) Average Spend by Weekday (Bar + Text)
        st.markdown("### Average Spend by Weekday (with Necessity %)")
        weekday_data = df_rep.groupby("Weekday").agg(
            total_amount=('amount', 'sum'),
            avg_amount=('amount', 'mean'),
            total_necess=('is_necessary', 'sum'),
            count=('is_necessary', 'count')
        ).reindex(["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"])
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

        # 2e) Average Monthly Expense Trend (Line Chart)
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

        # 2f) Overall Category‐Wise Distribution (Donut)
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


# ────────────────
# TAB 3: All Entries
# ────────────────
with tabs[3]:
    st.subheader("All Expense Entries")
    df_all = get_expenses_df(user_email)

    if df_all.empty:
        st.info("No expenses recorded yet.")
    else:
        st.dataframe(df_all)


# ──────────────────────────
# END OF STREAMLIT APP
# ──────────────────────────
